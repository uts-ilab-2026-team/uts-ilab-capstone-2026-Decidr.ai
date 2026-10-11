"""Authenticated retrieval-to-interpretation proposal endpoint."""

from contextlib import closing
from dataclasses import asdict
from datetime import date
import re
import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from decidr.api import auth
from decidr.api.corpus import corpus_database_path
from decidr.assessment_targets import AssessmentTarget
from decidr.authority_context import authority_context
from decidr.authority_links import explicit_authority_links
from decidr.hybrid import search_corpus
from decidr.interpretation_engine import infer_target, propose_interpretation
from decidr.retrieval_models import Evidence, Source

router = APIRouter(
    prefix="/api/corpus",
    dependencies=[Depends(auth.current_user)],
)


class InterpretationProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    claim: str = Field(min_length=1, max_length=10000)
    facet: str | None = Field(default=None, min_length=1, max_length=10000)
    assessment_target: AssessmentTarget = "unspecified"
    as_of: date
    ranked_group_limit: int = Field(default=8, ge=1, le=50, strict=True)
    max_inputs: int = Field(default=12, ge=1, le=50, strict=True)

    @field_validator("claim")
    @classmethod
    def reject_blank_claim(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Claim must not be blank")
        return value

    @field_validator("facet")
    @classmethod
    def reject_blank_facet(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Facet must not be blank")
        return value

    @field_validator("as_of", mode="before")
    @classmethod
    def explicit_iso_date(cls, value):
        if type(value) is date:
            return value
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("as_of must be an explicit YYYY-MM-DD date")
        return date.fromisoformat(value)


@router.post("/interpret")
def interpret_retrieved_evidence(request: InterpretationProposalRequest) -> dict:
    """Retrieve passages and propose reviewable assessment inputs.

    No proposal is persisted or treated as a human judgement.  The returned
    ``assessment_request`` can be edited and then submitted to
    ``/api/corpus/assess-supplied`` after explicit review.
    """
    return build_interpretation(request)


def build_interpretation(request: InterpretationProposalRequest, *, capture: bool = False) -> dict:
    facet = request.facet or request.claim
    path = corpus_database_path()
    try:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only = ON")
            connection.execute("BEGIN")
            sources = {
                row["source_id"]: Source.model_validate_json(row["payload_json"])
                for row in connection.execute(
                    "SELECT source_id, payload_json FROM sources ORDER BY source_id"
                )
            }
            evidence = {
                row["evidence_id"]: Evidence.model_validate_json(row["payload_json"])
                for row in connection.execute(
                    "SELECT evidence_id, payload_json FROM evidence ORDER BY evidence_id"
                )
            }
            if not sources or not evidence:
                raise HTTPException(
                    status_code=503,
                    detail="The corpus index contains no interpretable evidence.",
                )
            result = search_corpus(
                connection,
                facet,
                limit=request.ranked_group_limit,
            )
    except (sqlite3.Error, ValueError) as error:
        raise HTTPException(
            status_code=503,
            detail="The corpus index could not be read; check its configuration and schema.",
        ) from error

    selected_ids = []
    for group in (*result.ranked_groups, *result.additional_linked_groups):
        for evidence_id in group.matched_evidence_ids:
            if evidence_id not in selected_ids:
                selected_ids.append(evidence_id)
    selected_ids = selected_ids[: request.max_inputs]
    if request.assessment_target == "unspecified":
        assessment_target = infer_target(facet)
        target_inferred = True
    else:
        assessment_target = request.assessment_target
        target_inferred = False

    proposals = []
    candidates = {candidate.evidence_id: candidate for candidate in result.candidates}
    for evidence_id in selected_ids:
        passage = evidence[evidence_id]
        source = sources.get(passage.source_id)
        if source is None:
            raise HTTPException(
                status_code=503,
                detail=f"Evidence source is missing from the corpus index: {passage.source_id}",
            )
        proposals.append(
            propose_interpretation(
                claim_text=request.claim,
                facet=facet,
                assessment_target=assessment_target,
                as_of=request.as_of,
                evidence=passage,
                source=source,
            )
        )

    assessment_request = {
        "claim_text": request.claim,
        "facet": facet,
        "assessment_target": assessment_target,
        "as_of": request.as_of.isoformat(),
        "inputs": [proposal.assessment_input() for proposal in proposals],
    }
    proposal_payloads = []
    authority_links_by_source = {}
    for proposal in proposals:
        payload = proposal.review_payload()
        passage = evidence[proposal.evidence_id]
        source = sources[proposal.source_id]
        if source.source_id not in authority_links_by_source:
            authority_links_by_source[source.source_id] = explicit_authority_links(
                source=source,
                sources=list(sources.values()),
                passages=list(evidence.values()),
                as_of=request.as_of,
            )
        payload["evidence"] = passage.model_dump(mode="json")
        payload["authority_links"] = authority_links_by_source[source.source_id]
        payload["authority_context"] = authority_context(
            source=source,
            focal=passage,
            citation=proposal.citation,
            passages=evidence.values(),
            facet=facet,
            as_of=request.as_of.isoformat(),
        )
        payload["source_context"] = source.model_dump(
            mode="json", exclude={"original_file_path", "metadata_notes"}
        )
        candidate = candidates.get(proposal.evidence_id)
        payload["retrieval"] = (
            asdict(candidate.retrieval) if candidate and candidate.retrieval else None
        )
        payload["record_references"] = (
            [asdict(reference) for reference in candidate.record_references] if candidate else []
        )
        proposal_payloads.append(payload)

    # The adapter requires parent-origin declarations for derived sources. Do
    # not present a mechanically unsubmitable packet as a ready assessment draft.
    selected_sources = {proposal.source_id for proposal in proposals}
    draft_blockers = []
    for proposal in proposals:
        parent = sources[proposal.source_id].derived_from_source_id
        if parent and parent not in selected_sources:
            draft_blockers.append(
                "Derived-source parent provenance is missing from the proposal packet."
            )
    origins = {proposal.source_id: proposal.origin_id for proposal in proposals}
    for source_id in selected_sources:
        parent = sources[source_id].derived_from_source_id
        if parent in origins and origins[parent] != origins[source_id]:
            draft_blockers.append("Derived-source origin declarations need reconciliation.")
    if not proposals:
        draft_blockers.append("No matching evidence was retrieved; there is no assessment draft.")

    payload = {
        "status": "interpretation_proposed_review_required",
        "persisted": False,
        "interpreter_version": "bounded-proposals-v2",
        "review_status": "unreviewed",
        "assessment_ready": False,
        "quality_status": "not_assessed",
        "facet": facet,
        "claim": request.claim,
        "assessment_target": assessment_target,
        "assessment_target_inferred": target_inferred,
        "candidate_count": len(result.candidates),
        "ranked_group_count": len(result.ranked_groups),
        "additional_linked_group_count": len(result.additional_linked_groups),
        "proposal_count": len(proposals),
        "proposals": proposal_payloads,
        "assessment_request": assessment_request if not draft_blockers else None,
        "draft_blockers": list(dict.fromkeys(draft_blockers)),
        "review_checklist": [
            "Confirm support, contradiction, qualification or context against the exact citation.",
            "Confirm the assessment and evidence targets before admitting an edge.",
            "Resolve every unknown scope, temporal or authority judgement.",
            "Verify origin and independence from provenance, not retrieval rank.",
            "Edit the packet before submitting it to /api/corpus/assess-supplied.",
        ],
        "limitations": [
            "These are deterministic proposals, not human-reviewed judgements.",
            "Retrieval score is never used as a credibility probability.",
            "Authority remains unresolved; quality values are zero placeholders, not scores.",
            "Only bounded wording comparisons are proposed; paraphrase entailment is not implemented.",
            "Source and evidence snapshots describe the current index, not immutable review history.",
            "No proposal is persisted or promoted to the facts register automatically.",
        ],
    }

    if capture:
        payload["corpus_snapshot"] = {"sources": sources, "evidence": evidence}
    return payload
