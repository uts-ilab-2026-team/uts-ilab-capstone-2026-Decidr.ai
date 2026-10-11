"""Bounded automatic assessment, followed by optional parent-linked human review."""

from dataclasses import asdict, replace
import json
import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from framework import CONFIG_PATH
from framework.config import GraphCredibilityConfig
from pydantic import Field

from decidr import assessment_history as history
from decidr.api import auth
from decidr.api.assessment_history import (
    Owner,
    history_errors,
    history_path,
    implementation_manifest,
)
from decidr.api.corpus import corpus_database_path
from decidr.api.interpretation import InterpretationProposalRequest, build_interpretation
from decidr.approval_context import check_approval_context
from decidr.approval_propositions import compare_approval_rules
from decidr.assessment_adapter import InputDisposition, PreparedAttestation, assess_prepared_facet
from decidr.assessment_response import serialize_facet_assessment
from decidr.authority_resolution import resolve_authority
from decidr.deployment_signoff import deployment_event_findings
from decidr.evidence_synthesis import build_evidence_synthesis
from decidr.interpretation_engine import propose_interpretation
from decidr.interpretation_models import (
    EvidenceInterpretation,
    InterpretationCitation,
    validate_interpretation,
)
from decidr.practice_assessment import assess_practice
from decidr.transaction_claims import assess_transaction_claim, transaction_conclusion

router = APIRouter(dependencies=[Depends(auth.current_user)])
METHOD = "automatic-approval-assessment-v1"


class SaveAutomaticRequest(InterpretationProposalRequest):
    request_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


def set_primary_conclusion(response, conclusion, components, basis):
    """One saved primary result; framework admission remains separately inspectable."""
    response["claim_conclusion"] = conclusion
    response["credibility_assessment"] = response["assessment"]
    response["assessment"] = {
        **response["assessment"],
        "basis": basis,
        "overall_outcome": conclusion["label"],
        "observed_outcome": conclusion["label"],
        "formal_outcome": "Not assessed for this event claim",
        "summary": conclusion["summary"],
        "confidence": "Not independently verified",
        "components": components,
        "evidence": [],
        "gaps": [c["label"] for c in components if c["status"] != "supported"],
        "rules_applied": [basis.upper()],
    }


def build_automatic_assessment(request: InterpretationProposalRequest) -> dict:
    # The old deterministic engine remains explicit opt-in for reproducible legacy checks.
    if os.environ.get("DECIDR_ASSESSMENT_PROVIDER", "").strip() != "bounded":
        from decidr.general_assessment import build_general_bundle

        try:
            path = corpus_database_path()
        except HTTPException:
            path = None
        return build_general_bundle(request, path)
    return build_bounded_assessment(request)


def build_bounded_assessment(request: InterpretationProposalRequest) -> dict:
    # Retrieval, interpretation, citations and frozen context share one read transaction.
    draft = build_interpretation(request, capture=True)
    snapshot = draft.pop("corpus_snapshot")
    try:
        config = GraphCredibilityConfig(**json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError) as error:
        raise HTTPException(503, "Assessment configuration is unavailable.") from error
    scope_prefix = request.claim + "\n\nScope supplied by user: "
    supplied_scope = (
        draft["facet"][len(scope_prefix) :] if draft["facet"].startswith(scope_prefix) else None
    )
    transaction = (
        assess_transaction_claim(
            request.claim if supplied_scope is not None else draft["facet"],
            list(snapshot["evidence"].values()),
            snapshot["sources"],
            request.as_of,
            scope_answer=supplied_scope,
        )
        if draft["assessment_target"] == "underlying_event"
        else None
    )
    if transaction:
        used_ids = list(
            dict.fromkeys(
                o["evidence_id"]
                for component in transaction["components"]
                for o in component["observations"]
            )
        )
        proposals_by_id = {p["evidence_id"]: p for p in draft["proposals"]}
        # Linked component evidence takes priority over retrieval-only context.
        for evidence_id in used_ids[:50]:
            if evidence_id in proposals_by_id:
                continue
            passage = snapshot["evidence"][evidence_id]
            source = snapshot["sources"][passage.source_id]
            proposal = propose_interpretation(
                claim_text=request.claim,
                facet=draft["facet"],
                assessment_target="underlying_event",
                as_of=request.as_of,
                evidence=passage,
                source=source,
            ).review_payload()
            proposal.update(
                evidence=passage.model_dump(mode="json"),
                source_context=source.model_dump(
                    mode="json", exclude={"original_file_path", "metadata_notes"}
                ),
                authority_context={},
                authority_links={},
                retrieval=None,
                record_references=[
                    c for c in transaction["connections"] if c["evidence_id"] == evidence_id
                ],
            )
            proposals_by_id[evidence_id] = proposal
        ordered_ids = list(dict.fromkeys([*used_ids[:50], *proposals_by_id]))[:50]
        draft["proposals"] = [proposals_by_id[key] for key in ordered_ids]
        draft["proposal_count"] = len(draft["proposals"])
        if len(used_ids) > 50:
            transaction["components"].append(
                {
                    "field": "review_coverage",
                    "label": "More than 50 contributing passages require review",
                    "status": "unresolved",
                    "observations": [],
                }
            )
            if transaction["status"] == "supported_by_records":
                transaction["status"] = "partially_supported"
    prepared, excluded, inputs = [], [], []
    for proposal in draft["proposals"]:
        item = dict(proposal["suggested_input"])
        citation = item["citations"][0]
        passage = snapshot["evidence"][proposal["evidence_id"]]
        if transaction:
            observations = [
                observation
                for component in transaction["components"]
                for observation in component["observations"]
                if observation["evidence_id"] == passage.evidence_id
            ]
            per_component = [
                {o["status"] for o in c["observations"] if o["evidence_id"] == passage.evidence_id}
                for c in transaction["components"]
            ]
            full_support = all(states == {"supported"} for states in per_component)
            conflict = any(
                "conflicting" in states or {"supported", "contradicted"} <= states
                for states in per_component
            )
            contradicts = (
                any("contradicted" in states for states in per_component) and not conflict
            )
            scope_component = next(
                (c for c in transaction["components"] if c["field"] == "scope"), None
            )
            scope_matches = True if observations else None
            if scope_component:
                passage_scope_states = {
                    o["status"]
                    for o in scope_component["observations"]
                    if o["evidence_id"] == passage.evidence_id
                }
                scope_matches = (
                    True
                    if scope_component["status"] == "supported"
                    and passage_scope_states == {"supported"}
                    else False
                    if passage_scope_states == {"contradicted"}
                    else None
                )
            item.update(
                stance="support"
                if full_support
                else "contradict"
                if contradicts
                else "qualify"
                if observations and not conflict
                else "unresolved",
                mode="observed",
                evidence_target="underlying_event",
                scope_matches=scope_matches,
                rationale=" ".join(o["reason"] for o in observations)
                or "No explicit transaction component is established by this passage.",
                directness=1.0 if full_support or contradicts else 0.0,
                specificity=1.0 if full_support or contradicts else 0.0,
                completeness=1.0 if full_support else 0.0,
                judgement_basis="Explicit transaction component comparison. Source authority, independence and availability remain separate credibility checks.",
            )
            proposal["transaction_components"] = observations
        elif draft["assessment_target"] == "underlying_event":
            item.update(
                stance="unresolved",
                mode="observed",
                directness=0.0,
                specificity=0.0,
                completeness=0.0,
                rationale="The event claim cannot be fully interpreted automatically. This passage is retained for human review; no support or contradiction is inferred.",
                judgement_basis="Unsupported event comparison; no automatic semantic judgement.",
            )
        else:
            heading = (
                passage.heading
                if snapshot["sources"][proposal["source_id"]].source_type
                in {"organisational_information", "role_description"}
                else None
            )
            comparison = compare_approval_rules(draft["facet"], citation["quotation"], heading)
            context = check_approval_context(
                passage.text, citation["start"], citation["end"], heading
            )
            context["citation"] = {
                "evidence_id": passage.evidence_id,
                "source_id": passage.source_id,
                "locator": passage.locator,
                "quotation": passage.text,
                "start": 0,
                "end": len(passage.text),
            }
            proposal["passage_context"] = context
            supported = (
                comparison is not None
                and comparison["evidence_entails_claim"]
                and item["stance"] == "support"
                and draft["assessment_target"] == "formal_rule"
                and context["compatible"]
            )
            if not supported:
                item["stance"] = "context" if item["stance"] == "context" else "unresolved"
                if comparison is not None and not comparison["evidence_entails_claim"]:
                    item["rationale"] = (
                        "The rule comparison does not establish support. Different fields: "
                        + ", ".join(comparison["differences"])
                        + ". A difference alone does not prove contradiction."
                    )
                elif comparison is not None and not context["compatible"]:
                    item["rationale"] = (
                        "Rule wording matches, but surrounding conditions require review: "
                        + " ".join(c["reason"] for c in context["clauses"] if not c["compatible"])
                    )
                elif comparison is None and item["stance"] != "context":
                    item["rationale"] = (
                        "This passage does not contain a complete approval rule in a supported form. "
                        "It is retained for review; similarity alone does not establish support or contradiction."
                    )
            item.update(
                directness=1.0 if supported else 0.0,
                specificity=1.0 if supported else 0.0,
                completeness=1.0 if supported else 0.0,
                judgement_basis=(
                    "Deterministic approval-rule field comparison with bounded surrounding-clause checks. "
                    "Quality dimensions are binary grammar checks, not calibrated probabilities. "
                    "Authority and independence remain unverified."
                ),
            )
            if supported:
                resolution = resolve_authority(
                    source=snapshot["sources"][proposal["source_id"]],
                    focal=passage,
                    citation=InterpretationCitation.model_validate(citation),
                    sources=snapshot["sources"],
                    passages=list(snapshot["evidence"].values()),
                    as_of=request.as_of,
                )
                proposal["authority_resolution"] = resolution
                item["authority_verified"] = resolution["authority_verified"]
                item["judgement_basis"] = (
                    "Bounded rule and context comparison; authority checked using explicit-policy-adoption-v1. "
                    "Quality dimensions are grammar checks. Independence remains unverified."
                )
        proposal["automatic_input"] = item
        inputs.append(item)
        interpretation = EvidenceInterpretation(
            claim_text=request.claim,
            facet=draft["facet"],
            citations=tuple(InterpretationCitation.model_validate(c) for c in item["citations"]),
            **{key: item[key] for key in ("stance", "mode", "rationale")},
        )
        validate_interpretation(
            interpretation, snapshot["evidence"].values(), claim_text=request.claim
        )
        source = snapshot["sources"][proposal["source_id"]]
        judgements = {
            key: value
            for key, value in item.items()
            if key not in {"stance", "mode", "rationale", "citations"}
        }
        if source.derived_from_source_id:
            # Keep provenance intact; do not invent parent attestations to satisfy admission.
            excluded.append(
                InputDisposition(
                    f"excluded:{len(excluded) + 1}",
                    interpretation,
                    source,
                    judgements,
                    None,
                    ("Derived-source provenance requires review before automatic admission.",),
                )
            )
        else:
            prepared.append(
                PreparedAttestation(
                    interpretation=interpretation,
                    source=source,
                    **judgements,
                )
            )
    result = assess_prepared_facet(
        claim_text=request.claim,
        facet=draft["facet"],
        as_of=request.as_of,
        assessment_target=draft["assessment_target"],
        prepared=prepared,
        evidence=snapshot["evidence"].values(),
        config=config,
    )
    result = replace(result, inputs=(*result.inputs, *excluded))
    response = serialize_facet_assessment(result)
    response.update(
        status="assessed_automatically",
        interpretation_basis=METHOD,
        target_validation="bounded_approval_rule_comparison",
        persisted=False,
        index_scope="current",
        config_version=config.config_version,
        review_status="unreviewed",
        proposals=draft["proposals"],
    )
    matches = [p for p in draft["proposals"] if p["automatic_input"]["stance"] == "support"]
    resolved = any(p["automatic_input"]["authority_verified"] is True for p in matches)
    response["rule_comparison"] = {
        "status": "wording_matches_authority_resolved"
        if resolved
        else "wording_matches_authority_unresolved"
        if matches
        else "unresolved",
        "message": "Rule wording matches; documented authority resolved"
        if resolved
        else "Rule wording matches; authority unresolved"
        if matches
        else "Rule comparison unresolved",
        "matching_evidence_ids": [p["evidence_id"] for p in matches],
        "notice": "This describes the rule comparison, not a verified credibility verdict. Admission safeguards still apply.",
    }
    response["assurance"].update(
        outcome_basis="conditional_on_automatic_judgements",
        semantic_verification="bounded_rule_fields_v3",
        authority_verification="explicit_dated_adoption_and_person_specific_rights_checked",
        independence_verification="unverified_origins_conservatively_grouped",
        quality_scores="binary_complete_grammar_checks_not_calibrated",
        source_class_and_approval_key="deterministic_metadata_mapping",
        human_review="pending",
        notice=(
            "Automatic result for this facet; human review is pending. "
            "Supported wording does not establish authority or independent corroboration."
        ),
    )
    response["limitations"] = [
        "Supported approval rules are compared with bounded checks of adjacent passage statements.",
        "Unsupported comparisons remain unresolved; differences alone are not contradictions.",
        "Authority resolves only for explicit dated adoption and matching rights; independence remains unverified.",
        "Derived sources require provenance review before admission.",
        "Retrieval limits can omit relevant evidence; this is not an exhaustive corpus verdict.",
        "Quality dimensions describe grammar coverage, not calibrated credibility probabilities.",
        "The assessment concerns the facet; the original claim is retained unchanged.",
    ]
    response["deployment_event_findings"] = deployment_event_findings(
        draft["facet"], list(snapshot["evidence"].values()), request.as_of
    )
    response["practice_assessment"] = assess_practice(
        draft["facet"], list(snapshot["evidence"].values()), snapshot["sources"], request.as_of
    )
    if transaction:
        response["transaction_assessment"] = transaction
        response["claim_conclusion"] = transaction_conclusion(transaction)
        conclusion = response["claim_conclusion"]
        set_primary_conclusion(
            response, conclusion, transaction["components"], "transaction_components_v1"
        )
        response["target_validation"] = "explicit_transaction_components"
        response["assurance"].update(
            outcome_basis="conditional_on_recorded_event_components",
            semantic_verification="explicit_transaction_components_v1",
            quality_scores="binary_component_coverage_not_calibrated",
            authority_verification="unverified_event_authority",
            notice=conclusion["notice"],
        )
        response["limitations"] = [
            transaction["notice"],
            "The primary outcome describes explicit recorded components; it is not a verified credibility probability.",
            "Missing, pending, qualified or conflicting approval assertions cannot establish completed approval.",
            "Unknown dates, authority and source independence remain separate credibility limitations.",
            "Unsupported transaction wording and unstructured narrative comparisons still require review.",
        ]
        response.pop("rule_comparison", None)
        response.pop("practice_assessment", None)
    elif draft["assessment_target"] == "underlying_event":
        conclusion = {
            "status": "unsupported_interpretation",
            "label": "Not assessed automatically",
            "summary": "This event claim contains wording or assertions the automatic interpreter cannot fully compare. Retrieved passages remain available for review; this is not a finding that the claim is false or that evidence is absent.",
            "basis": "unsupported_interpretation",
            "notice": "Review the exact claim and passages, or assess its individual assertions separately. The original claim is preserved.",
        }
        set_primary_conclusion(
            response,
            conclusion,
            [
                {
                    "field": "interpretation",
                    "label": "Complete interpretation of the event claim",
                    "status": "unresolved",
                    "observations": [],
                }
            ],
            "unsupported_interpretation_v1",
        )
        response["target_validation"] = "unsupported_event_interpretation"
        response["assurance"].update(
            outcome_basis="interpretation_incomplete",
            semantic_verification="not_established",
            authority_verification="unverified_event_authority",
            notice=conclusion["notice"],
        )
        response.pop("rule_comparison", None)
        response.pop("practice_assessment", None)
        response["limitations"] = [conclusion["summary"], conclusion["notice"]]
    response["evidence_synthesis"] = build_evidence_synthesis(
        draft["facet"],
        list(snapshot["evidence"].values()),
        snapshot["sources"],
        request.as_of,
        resolved_record_ids=[transaction["record_id"]]
        if transaction
        and transaction.get("record_resolution") in {"explicit_id", "unique_actor_amount_match"}
        else None,
    )
    packet = {
        "claim_text": request.claim,
        "facet": draft["facet"],
        "assessment_target": draft["assessment_target"],
        "as_of": request.as_of.isoformat(),
        "inputs": inputs,
    }
    frozen = {
        key: [value.model_dump(mode="json") for value in values.values()]
        for key, values in snapshot.items()
    }
    return dict(
        response=response,
        request=packet,
        **frozen,
        configuration=asdict(config),
        interpretation=draft,
        provenance={
            "assessment_method": METHOD,
            "corpus_index_sha256": history.content_hash(frozen),
            "corpus_revision_method": "validated-corpus-snapshot-v1",
            "evidence_scope": "complete_index_snapshot",
        },
    )


@router.post("/api/corpus/assess-automatic")
def assess_automatic(request: InterpretationProposalRequest):
    return build_automatic_assessment(request)["response"]


@router.post("/api/assessments/automatic")
def save_automatic(request: SaveAutomaticRequest, user: Owner):
    with history_errors():
        path = history_path()
        from decidr.general_assessment import METHOD as GENERAL_METHOD

        method = (
            METHOD
            if os.environ.get("DECIDR_ASSESSMENT_PROVIDER", "").strip() == "bounded"
            else GENERAL_METHOD
        )
        command = {**request.model_dump(mode="json"), "method": method}
        previous = history.existing_retry(path, user["id"], command)
        if previous is not None:
            return JSONResponse(previous, status_code=200)
        query = InterpretationProposalRequest.model_validate(
            request.model_dump(exclude={"request_id"})
        )
        bundle = build_automatic_assessment(query)
        bundle["provenance"]["implementation"] = implementation_manifest()
        record, created = history.append_run(path, user["id"], command, bundle)
    return JSONResponse(record, status_code=201 if created else 200)
