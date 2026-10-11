"""Bounded automatic assessment, followed by optional parent-linked human review."""

from dataclasses import asdict, replace
import json

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
from decidr.api.interpretation import InterpretationProposalRequest, build_interpretation
from decidr.approval_context import check_approval_context
from decidr.approval_propositions import compare_approval_rules
from decidr.assessment_adapter import InputDisposition, PreparedAttestation, assess_prepared_facet
from decidr.assessment_response import serialize_facet_assessment
from decidr.authority_resolution import resolve_authority
from decidr.interpretation_models import (
    EvidenceInterpretation,
    InterpretationCitation,
    validate_interpretation,
)

router = APIRouter(dependencies=[Depends(auth.current_user)])
METHOD = "automatic-approval-assessment-v1"


class SaveAutomaticRequest(InterpretationProposalRequest):
    request_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


def build_automatic_assessment(request: InterpretationProposalRequest) -> dict:
    # Retrieval, interpretation, citations and frozen context share one read transaction.
    draft = build_interpretation(request, capture=True)
    snapshot = draft.pop("corpus_snapshot")
    try:
        config = GraphCredibilityConfig(**json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError) as error:
        raise HTTPException(503, "Assessment configuration is unavailable.") from error
    prepared, excluded, inputs = [], [], []
    for proposal in draft["proposals"]:
        item = dict(proposal["suggested_input"])
        citation = item["citations"][0]
        comparison = compare_approval_rules(draft["facet"], citation["quotation"])
        passage = snapshot["evidence"][proposal["evidence_id"]]
        context = check_approval_context(passage.text, citation["start"], citation["end"])
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
            item["rationale"] = (
                "No supported complete approval-rule comparison establishes this relationship. "
                "Field differences and surrounding qualifications require review."
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
        semantic_verification="bounded_discount_and_expense_approval_fields",
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
        command = {**request.model_dump(mode="json"), "method": METHOD}
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
