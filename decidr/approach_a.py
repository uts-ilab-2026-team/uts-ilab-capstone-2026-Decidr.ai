"""Approach A adapter emitting the shared assessment response schema."""

from datetime import UTC, datetime
from typing import Any

from decidr.contracts import AssessmentResult, StructuredClaimResult
from decidr.explanation import render_explanation
from decidr.models import AtomicClaim, EvidenceRelationship
from decidr.reasoning import ReasoningResult


def to_assessment_result(
    claim: AtomicClaim,
    reasoning: ReasoningResult,
    *,
    query: str,
    runtime_metadata: dict[str, Any],
) -> AssessmentResult:
    """Translate the relational lexical baseline into the common comparison contract."""
    buckets = {relationship: [] for relationship in EvidenceRelationship}
    citations = []
    for item in reasoning.applicable:
        record = {
            "evidence_id": item.evidence_id,
            "source_id": item.source_id,
            "locator": item.locator,
            "relationship": item.relationship.value,
        }
        buckets[item.relationship].append(record)
        citations.append({key: record[key] for key in ("evidence_id", "source_id", "locator")})
    metadata = {
        **runtime_metadata,
        "timestamp": datetime.now(UTC).isoformat(),
        "claim_version": claim.portfolio_version,
    }
    return AssessmentResult(
        approach_id="approach_a_relational_lexical",
        query=query,
        structured_claim=StructuredClaimResult(
            subject=claim.subject, predicate=claim.predicate, target_object=claim.object,
            scope=claim.scope, conditions=claim.conditions,
            applicable_period={
                "start": claim.applicable_start_date.isoformat() if claim.applicable_start_date else None,
                "end": claim.applicable_end_date.isoformat() if claim.applicable_end_date else None,
            }, evidence_target=claim.evidence_target.value if claim.evidence_target else "unspecified",
        ),
        outcome=reasoning.outcome, confidence=reasoning.confidence,
        supporting_evidence=buckets[EvidenceRelationship.SUPPORT],
        contradicting_evidence=buckets[EvidenceRelationship.CONTRADICT],
        qualifying_evidence=buckets[EvidenceRelationship.QUALIFY],
        contextual_evidence=buckets[EvidenceRelationship.CONTEXTUAL],
        not_applicable_evidence=buckets[EvidenceRelationship.NOT_APPLICABLE],
        dependent_evidence_groups=[
            {"evidence_id": item.evidence_id, "reason": reason}
            for item, reason in reasoning.excluded if "duplicate" in reason
        ],
        evidence_gaps=list(reasoning.gaps), rules_applied=list(reasoning.traces),
        explanation=render_explanation(claim, reasoning), citations=citations,
        runtime_metadata=metadata,
    )
