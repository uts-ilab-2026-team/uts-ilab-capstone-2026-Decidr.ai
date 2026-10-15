"""Claim-interpretation pipeline: interpret, verify, salvage, and retry control flow."""

from datetime import date

from decidr.claim_interpreter.llm_completion import _complete, _record_validation
from decidr.claim_interpreter.prompts import (
    _INTERPRETATION_INSTRUCTION,
    _VERIFICATION_INSTRUCTION,
)
from decidr.claim_interpreter.providers import (
    NUMERIC_VALIDATION_LIMITATIONS,
    NUMERIC_VALIDATION_METHOD,
    VALIDATION_METHOD,
    Provider,
    ProviderError,
    _EvidenceMeaningError,
)
from decidr.claim_interpreter.schemas import (
    Component,
    _claim_verifier_model,
    _interpretation_model,
    _verbatim_claim_kind,
)
from decidr.claim_interpreter.text_numeric import _normative_threshold_claim
from decidr.claim_interpreter.validation import _validate_claim_numbers
from decidr.claim_spans import exact_claim_span


def _interpret_claim_once(
    claim: str, as_of: date | str, provider: Provider, feedback: str = ""
) -> dict:
    if not isinstance(claim, str) or not claim.strip():
        raise ProviderError("interpretation_failure", "A non-empty claim is required.")
    data = {
        "original_claim": claim,
        "assessment_date": str(as_of),
        "validation_feedback": feedback,
    }
    model = _interpretation_model(claim)
    output = _complete(
        provider,
        model,
        _INTERPRETATION_INSTRUCTION,
        data,
    )
    ids = [component["id"] for component in output["components"]]
    if len(ids) != len(set(ids)):
        raise ProviderError(
            "invalid_model_output", "Interpretation component identifiers are not unique."
        )
    _validate_claim_numbers(claim, output)
    verification = _complete(
        provider,
        _claim_verifier_model(ids),
        _VERIFICATION_INSTRUCTION,
        {
            **{key: value for key, value in data.items() if key != "validation_feedback"},
            "proposed_interpretation": output,
        },
    )
    checks = [
        {"component_id": component_id, **check}
        for component_id, check in verification["component_checks"].items()
    ]
    if sorted(check["component_id"] for check in checks) != sorted(ids):
        raise ProviderError(
            "invalid_model_output",
            "Semantic verification did not check every component exactly once.",
        )
    omissions = verification["omitted_claim_spans"]
    for omission in omissions:
        original_span = exact_claim_span(claim, omission["claim_quote"])
        if original_span is None:
            raise ProviderError(
                "invalid_model_output",
                "A claimed interpretation omission is not an exact original-claim span.",
            )
        omission["claim_quote"] = original_span
    if omissions or any(not check["valid"] for check in checks):
        raise ProviderError(
            "interpretation_failure",
            "Semantic validation rejected the claim interpretation: "
            + "; ".join(
                [item["reason"] for item in omissions]
                + [check["reason"] for check in checks if not check["valid"]]
            )[:1200],
        )
    output["semantic_validation"] = {
        "method": VALIDATION_METHOD,
        "component_checks": checks,
        "numeric_validation_method": NUMERIC_VALIDATION_METHOD,
        "numeric_validation_limitations": list(NUMERIC_VALIDATION_LIMITATIONS),
    }
    kind = _verbatim_claim_kind(claim)
    if kind:
        output["semantic_validation"][kind + "_claim_method"] = "lexical-cue-verbatim-component-v1"
    if _normative_threshold_claim(claim):
        output["semantic_validation"]["target_constraint_method"] = (
            "unqualified-normative-approval-threshold-v1"
        )
    return output


def _evidence_data(interpretation, claim, passages, as_of) -> dict:
    return {
        "original_claim": claim,
        "interpretation": {
            "target": interpretation["target"],
            "components": [
                {key: component[key] for key in Component.model_fields if key in component}
                for component in interpretation["components"]
            ],
            "ambiguities": interpretation.get("ambiguities", []),
        },
        "assessment_date": str(as_of),
        "selected_passages": [
            {
                key: passage[key]
                for key in ("evidence_id", "source_id", "locator", "text", "heading")
                if key in passage
            }
            for passage in passages
        ],
        "sources_by_id": {passage["source_id"]: passage.get("source", {}) for passage in passages},
    }


def _retain_verified_evidence(
    error: _EvidenceMeaningError, *, require_applicable: bool = False
) -> dict | None:
    validation = error.interpretation.get("semantic_validation", {})
    claim_checks = validation.get("component_checks", [])
    ids = [component["id"] for component in error.interpretation["components"]]
    if (
        validation.get("method") != VALIDATION_METHOD
        or sorted(check.get("component_id", "") for check in claim_checks) != sorted(ids)
        or any(check.get("valid") is not True for check in claim_checks)
    ):
        return None
    output = error.output
    verified_material = [
        check["finding_index"]
        for check in error.checks
        if check["valid"]
        and output["findings"][check["finding_index"]]["relationship"]
        in {"supports", "contradicts", "qualifies"}
        and output["findings"][check["finding_index"]]["scope_fit"] != "no"
        and output["findings"][check["finding_index"]]["time_fit"] != "no"
    ]
    contributed = [
        index
        for index in verified_material
        if output["findings"][index]["scope_fit"] == "yes"
        and output["findings"][index]["time_fit"] == "yes"
    ]
    if not verified_material or (require_applicable and not contributed):
        return None
    uncertain = set(verified_material) - set(contributed)
    for index in sorted(uncertain):
        finding = output["findings"][index]
        finding["semantic_validation"]["original_proposal"] = {
            key: finding[key]
            for key in (
                "relationship",
                "scope_fit",
                "time_fit",
                "directness",
                "basis",
                "reason",
                "limitations",
            )
        }
        gaps = [
            label
            for field, label in (("scope_fit", "scope"), ("time_fit", "temporal applicability"))
            if finding[field] == "unknown"
        ]
        reason = (
            "This verified evidence relation remains unresolved because its "
            + " and ".join(gaps)
            + " is not established."
        )
        finding.update(
            relationship="unresolved",
            reason=reason,
            limitations=[*finding["limitations"], reason],
        )
        output["unresolved_questions"].append(
            f"Establish {' and '.join(gaps)} for {finding['component_id']} against {finding['evidence_id']}."
        )
    binding_fields = ("component_id", "evidence_id", "relationship")
    verified_bindings = {
        tuple(output["findings"][index][key] for key in binding_fields): index
        for index in contributed
    }
    rejected = [check for check in error.checks if not check["valid"]]
    redundant = {}
    for check in rejected:
        finding = output["findings"][check["finding_index"]]
        binding = tuple(finding[key] for key in binding_fields)
        if (
            binding in verified_bindings
            and check["expected_relationship"] == finding["relationship"]
            and not check.get("grounding_error")
        ):
            redundant[check["finding_index"]] = {
                "original_finding_index": check["finding_index"],
                "verified_peer_original_index": verified_bindings[binding],
                "finding": finding,
            }
            continue
        finding["semantic_validation"]["original_proposal"] = {
            key: finding[key]
            for key in (
                "relationship",
                "scope_fit",
                "time_fit",
                "directness",
                "basis",
                "reason",
                "limitations",
            )
        }
        reason = "This evidence interpretation remains unverified: " + check["reason"]
        finding.update(
            relationship="unresolved",
            scope_fit="unknown",
            time_fit="unknown",
            directness="indirect",
            basis="contextual",
            reason=reason,
            limitations=[*finding["limitations"], reason],
        )
        output["unresolved_questions"].append(
            f"Resolve {finding['component_id']} against {finding['evidence_id']}: {reason}"
        )
    for omission in error.omissions:
        passage = error.evidence[omission["evidence_id"]]
        reason = "Material evidence was not successfully evaluated: " + omission["reason"]
        output["findings"].append(
            {
                "component_id": omission["component_id"],
                "evidence_id": passage["evidence_id"],
                "source_id": passage["source_id"],
                "quotation": passage["text"],
                "locator": passage.get("locator", ""),
                "start": 0,
                "end": len(passage["text"]),
                "relationship": "unresolved",
                "reason": reason,
                "scope_fit": "unknown",
                "time_fit": "unknown",
                "directness": "indirect",
                "basis": "contextual",
                "limitations": [reason],
                "semantic_validation": {
                    "method": VALIDATION_METHOD,
                    "valid": False,
                    "reason": omission["reason"],
                    "omitted_evidence": True,
                    "grounding_quote": omission["grounding_quote"],
                },
            }
        )
        output["unresolved_questions"].append(
            f"Resolve {omission['component_id']} against {omission['evidence_id']}: {reason}"
        )
    if redundant:
        output["semantic_validation"]["redundant_rejections"] = list(redundant.values())
        output["findings"] = [
            finding for index, finding in enumerate(output["findings"]) if index not in redundant
        ]
    unresolved_count = len(rejected) - len(redundant)
    output["semantic_validation"].update(
        status="partially_validated"
        if unresolved_count or error.omissions or uncertain
        else "validated",
        verified_contributing_findings=len(contributed),
        verified_uncertain_findings=len(uncertain),
        rejected_findings=unresolved_count,
        omitted_passages=len(error.omissions),
    )
    return output


def _validated_retry(stage: str, provider: Provider, operation) -> dict:
    try:
        result = operation("")
    except ProviderError as initial:
        if initial.code not in {"invalid_model_output", "interpretation_failure"}:
            raise
        _record_validation(provider, stage, initial.code, False)
        feedback = (
            "A prior attempt failed independent validation: "
            + initial.message
            + " Re-read all original data and produce a corrected COMPLETE result. "
            "Retain every material clause and all counterevidence; do not drop difficult "
            "findings, change quotations, or invent values to make validation pass. "
            "Every value, citation and semantic relation will be checked again."
        )
        try:
            result = operation(feedback)
        except ProviderError as final:
            if final.code not in {"invalid_model_output", "interpretation_failure"}:
                raise
            result = None
            if isinstance(final, _EvidenceMeaningError):
                result = _retain_verified_evidence(final)
            elif final.code == "invalid_model_output" and isinstance(
                initial, _EvidenceMeaningError
            ):
                # A malformed repair supplies no replacement audit; retain only the complete one.
                result = _retain_verified_evidence(initial, require_applicable=True)
                if result is not None:
                    result["semantic_validation"].update(
                        retained_attempt="initial",
                        repair_failure={"code": final.code, "message": final.message[:1200]},
                    )
            if result is None:
                raise ProviderError(
                    initial.code, "Validation failed after one complete repair: " + final.message
                ) from final
        _record_validation(
            provider,
            stage,
            initial.code,
            result["semantic_validation"].get("status") != "partially_validated"
            and result["semantic_validation"].get("retained_attempt") != "initial",
        )
        result["semantic_validation"]["complete_repair_attempted"] = True
        result["semantic_validation"]["initial_error_code"] = initial.code
    return result


def interpret_claim(claim: str, as_of: date | str, provider: Provider) -> dict:
    if not isinstance(claim, str) or not claim.strip():
        raise ProviderError("interpretation_failure", "A non-empty claim is required.")
    return _validated_retry(
        "claim_interpretation",
        provider,
        lambda feedback: _interpret_claim_once(claim, as_of, provider, feedback),
    )
