"""Bounded retrieval -> grounded candidate values -> claims -> deterministic reasoning.

Extraction is replaceable and untrusted. No live LLM extractor is installed here.
"""

from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import Field

from decidr.approach_b import BoundedGraphExpander, HybridGraphRetriever
from decidr.models import AtomicClaim as LedgerClaim
from decidr.models import EvidenceTarget
from decidr.query_frames import (
    AtomicClaim,
    QueryFrame,
    RequestedField,
    StrictModel,
    query_frame_to_atomic_claim,
)
from decidr.reasoning import ReasoningResult, ReviewedEvidence, assess_claim


class RetrievedEvidence(StrictModel):
    source_id: str = Field(pattern=r"^phase2:", min_length=8)
    evidence_unit_id: str = Field(min_length=1)
    text: str = Field(min_length=1, max_length=8000)


class EvidencePacket(StrictModel):
    items: list[RetrievedEvidence] = Field(max_length=20)

    def bounded(self):
        if sum(len(item.text) for item in self.items) > 40000:
            raise ValueError("Retrieved evidence packet exceeds the 40000-character budget")
        ids = [(i.source_id, i.evidence_unit_id) for i in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("Evidence packet contains duplicate evidence identities")
        return self


class CandidateBinding(StrictModel):
    requested_field: RequestedField
    extracted_value: str = Field(min_length=1)
    source_id: str = Field(pattern=r"^phase2:")
    evidence_unit_id: str = Field(min_length=1)
    exact_supporting_span: str = Field(min_length=1)
    extraction_status: Literal["candidate"]


class EvidenceBinder(Protocol):
    def bind(self, frame: QueryFrame, evidence: EvidencePacket) -> list[CandidateBinding]: ...


class PendingEvidenceBinder:
    """Explicitly pending extraction, never pretend an organisational answer was found."""
    def bind(self, frame: QueryFrame, evidence: EvidencePacket) -> list[CandidateBinding]:
        return []


def grounded_bindings(frame: QueryFrame, packet: EvidencePacket,
                      binder: EvidenceBinder) -> tuple[CandidateBinding, ...]:
    packet = EvidencePacket.model_validate(packet.model_dump()).bounded()
    # The adapter receives only this validated bounded Phase 2 packet.
    proposed = binder.bind(frame.model_copy(deep=True), packet.model_copy(deep=True))
    if len(proposed) > 40:
        raise ValueError("Too many candidate bindings")
    accepted = []
    for proposal in proposed:
        candidate = CandidateBinding.model_validate(
            proposal.model_dump() if isinstance(proposal, CandidateBinding) else proposal
        )
        if candidate.requested_field not in frame.requested_fields:
            raise ValueError("Binding answers an unrequested field")
        if candidate.requested_field in {"truth_status", "unknown"}:
            raise ValueError("Extraction cannot bind a truth status or verdict")
        source = next((i for i in packet.items if i.source_id == candidate.source_id
                       and i.evidence_unit_id == candidate.evidence_unit_id), None)
        if (not source or candidate.exact_supporting_span not in source.text
                or candidate.extracted_value not in candidate.exact_supporting_span):
            raise ValueError("Binding value/span is not grounded in the cited retrieved evidence")
        accepted.append(candidate)
    return tuple(accepted)


def claim_from_binding(frame: QueryFrame, binding: CandidateBinding,
                       packet: EvidencePacket) -> AtomicClaim:
    class SuppliedBinding:
        def bind(self, frame, evidence):
            return [binding]
    binding = grounded_bindings(frame, packet, SuppliedBinding())[0]
    if frame.needs_clarification or not frame.business_action or not frame.business_object:
        raise ValueError("Resolve the query frame before constructing a factual claim")
    if binding.requested_field == "authorised_role":
        subject = binding.extracted_value
        predicate = ("has formally documented authority to " if frame.assessment_target == "prescribed_rule"
                     else "has authority to ") + frame.business_action
        obj = frame.business_object
    else:
        # Other lookup values remain literal candidates, never an LLM truth classification.
        subject = frame.known_actor or frame.process or frame.business_object
        predicate = {
            "threshold": "has prescribed threshold", "timing": "has prescribed timing",
            "procedure": "has prescribed procedure", "recorded_value": "has recorded value",
            "practice_description": "has described practice",
        }[binding.requested_field]
        obj = binding.extracted_value
    base = query_frame_to_atomic_claim(frame, subject=subject, object_override=obj)
    return base.model_copy(update={
        "predicate": predicate,
        "conditions": list(dict.fromkeys([
            *base.conditions,
            *([] if binding.requested_field == "authorised_role"
              else [f"{frame.business_action} {frame.business_object}"]),
        ])),
    })


def to_ledger_claim(claim: AtomicClaim, frame: QueryFrame, identifier: str) -> LedgerClaim:
    return LedgerClaim(
        claim_id=identifier, subject=claim.subject, predicate=claim.predicate, object=claim.object,
        process=claim.process, scope=claim.scope,
        conditions=[*claim.conditions, *claim.temporal_scope],
        claim_text=f"{claim.subject} {claim.predicate} {claim.object}.",
        claim_type=frame.query_operator, evidence_target=EvidenceTarget(claim.assessment_target),
        proposition_polarity="negative" if claim.polarity == "negative" else "positive",
        original_claim_text=frame.original_question, atomicity_status="user_confirmed",
    )


class DeterministicEvidenceReviewer(Protocol):
    """Trusted assessment boundary, NOT an extraction model.

    Implementations must establish applicability, credibility and explicit incompatibility
    from source metadata/reviewed evidence. Two different roles are not automatically
    incompatible: joint authority is possible.
    """
    def review(self, claim: LedgerClaim, packet: EvidencePacket) -> list[ReviewedEvidence]: ...


@dataclass(frozen=True)
class BoundAssessment:
    claim: LedgerClaim | None
    reasoning: ReasoningResult
    status: str


def assess_query_bindings(frame: QueryFrame, packet: EvidencePacket, binder: EvidenceBinder,
                          reviewer: DeterministicEvidenceReviewer, *, employee_confirmed: bool
                          ) -> tuple[BoundAssessment, ...]:
    if not employee_confirmed or frame.needs_clarification:
        raise ValueError("Employee confirmation of a resolved query frame is mandatory")
    bindings = grounded_bindings(frame, packet, binder)
    if not bindings:
        return (BoundAssessment(None, assess_claim([], expected_evidence_gaps=[
            "No grounded candidate binding is available; an extraction adapter may still be pending."
        ]), "extraction_pending" if isinstance(binder, PendingEvidenceBinder) else "no_grounded_binding"),)
    results = []
    for index, binding in enumerate(bindings, 1):
        claim = to_ledger_claim(claim_from_binding(frame, binding, packet), frame, f"QUERY-BOUND-{index}")
        reviewed = reviewer.review(claim, packet)
        allowed = {(i.source_id, i.evidence_unit_id) for i in packet.items}
        if any((r.source_id, r.evidence_id) not in allowed for r in reviewed):
            raise ValueError("Assessment review cites evidence outside the retrieved packet")
        results.append(BoundAssessment(claim, assess_claim(
            reviewed, evidence_target=claim.evidence_target,
        ), "assessed"))
    return tuple(results)


@dataclass(frozen=True)
class QuerySearchProjection:
    """Search text/constraints only. This is NOT an AtomicClaim or a truth assertion."""
    subject: str
    predicate: str
    object: str
    process: str | None
    scope: str | None
    conditions: list[str]
    claim_text: str


def retrieve_query_frame(connection, frame: QueryFrame, profile: dict, *, employee_confirmed: bool
                         ) -> EvidencePacket:
    if not employee_confirmed or frame.needs_clarification:
        raise ValueError("Confirm a resolved query frame before retrieval")
    projection = QuerySearchProjection(
        frame.known_actor or "", frame.business_action or "", frame.business_object or "",
        frame.process,
        frame.scope, [*frame.conditions, *frame.numeric_values, *frame.temporal_scope], frame.original_question,
    )
    retriever = HybridGraphRetriever(connection, semantic=profile.get("semantic_enabled", False),
                                     embedding_model=profile["embedding_model"])
    retrieved = retriever.retrieve(projection, limit=20)
    expanded = BoundedGraphExpander(connection).expand(projection, retrieved)
    items, total = [], 0
    for item in expanded:
        if not item["source_id"].startswith("phase2:"):
            continue
        text = item["text"][:min(8000, 40000-total)]
        if not text or len(items) == 20:
            break
        items.append(RetrievedEvidence(source_id=item["source_id"],
                                       evidence_unit_id=item["evidence_id"], text=text))
        total += len(text)
    return EvidencePacket(items=items).bounded()
