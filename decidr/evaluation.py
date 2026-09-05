"""Guarded evaluation utilities for small, adjudicated research samples."""

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from enum import StrEnum

from decidr.models import ClaimOutcome


class ErrorCategory(StrEnum):
    CLAIM_AMBIGUITY = "claim_ambiguity"
    RETRIEVAL_FAILURE = "retrieval_failure"
    APPLICABILITY_ERROR = "applicability_error"
    RELATIONSHIP_MISCLASSIFICATION = "relationship_misclassification"
    PROVENANCE_LOSS = "provenance_loss"
    TEMPORAL_ERROR = "temporal_error"
    DEPENDENCE_ERROR = "dependence_error"
    INAPPROPRIATE_REASONING = "inappropriate_reasoning"
    UNFAITHFUL_EXPLANATION = "unfaithful_explanation"
    DATA_EXTRACTION_FAILURE = "data_extraction_failure"
    REFERENCE_REVIEW_DISAGREEMENT = "reference_review_disagreement"


@dataclass(frozen=True, slots=True)
class RetrievalEvaluation:
    relevant_applicable_found: int
    irrelevant_returned: int
    material_missed: int
    precision: float | None
    recall: float | None
    f1: float | None
    pool_complete: bool
    limitation: str | None


def retrieval_metrics(
    retrieved_ids: set[str],
    relevant_applicable_ids: set[str],
    *,
    pool_complete: bool,
) -> RetrievalEvaluation:
    """Calculate metrics only when the adjudicated evidence pool is complete."""
    found = len(retrieved_ids & relevant_applicable_ids)
    irrelevant = len(retrieved_ids - relevant_applicable_ids)
    missed = len(relevant_applicable_ids - retrieved_ids)
    if not pool_complete:
        return RetrievalEvaluation(
            found,
            irrelevant,
            missed,
            None,
            None,
            None,
            False,
            "Precision, recall, and F1 withheld because the adjudicated evidence pool is incomplete.",
        )
    precision = found / len(retrieved_ids) if retrieved_ids else 0.0
    recall = found / len(relevant_applicable_ids) if relevant_applicable_ids else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return RetrievalEvaluation(found, irrelevant, missed, precision, recall, f1, True, None)


@dataclass(frozen=True, slots=True)
class OutcomeEvaluation:
    evaluated_claims: int
    agreements: int
    agreement_rate: float | None
    confusion_matrix: dict[str, dict[str, int]]
    disagreements: tuple[str, ...]


def outcome_metrics(
    reference: dict[str, ClaimOutcome], automated: dict[str, ClaimOutcome]
) -> OutcomeEvaluation:
    """Compare only claims that have both an adjudicated and automated outcome."""
    claim_ids = sorted(reference.keys() & automated.keys())
    labels = [item.value for item in ClaimOutcome]
    matrix = {expected: {observed: 0 for observed in labels} for expected in labels}
    disagreements = []
    agreements = 0
    for claim_id in claim_ids:
        expected = reference[claim_id].value
        observed = automated[claim_id].value
        matrix[expected][observed] += 1
        if expected == observed:
            agreements += 1
        else:
            disagreements.append(claim_id)
    rate = agreements / len(claim_ids) if claim_ids else None
    return OutcomeEvaluation(len(claim_ids), agreements, rate, matrix, tuple(disagreements))


def reviewer_agreement(
    reviewer_a: dict[str, ClaimOutcome], reviewer_b: dict[str, ClaimOutcome]
) -> dict[str, float | int | None]:
    """Return raw agreement and Cohen's kappa without overinterpreting tiny samples."""
    claim_ids = sorted(reviewer_a.keys() & reviewer_b.keys())
    if not claim_ids:
        return {"common_claims": 0, "raw_agreement": None, "cohen_kappa": None}
    agreements = sum(reviewer_a[key] == reviewer_b[key] for key in claim_ids)
    raw = agreements / len(claim_ids)
    labels = list(ClaimOutcome)
    a_counts = {label: sum(reviewer_a[key] == label for key in claim_ids) for label in labels}
    b_counts = {label: sum(reviewer_b[key] == label for key in claim_ids) for label in labels}
    expected = sum(a_counts[label] * b_counts[label] for label in labels) / len(claim_ids) ** 2
    kappa = (raw - expected) / (1 - expected) if expected < 1 else None
    return {"common_claims": len(claim_ids), "raw_agreement": raw, "cohen_kappa": kappa}


TRACEABILITY_FIELDS = (
    "source_id",
    "locator",
    "date_or_version",
    "provenance",
    "relationship",
    "reasoning_rule",
)


def traceability_check(records: Iterable[dict[str, object]]) -> dict[str, object]:
    """Check whether decisive evidence can reconstruct an explanation."""
    records = list(records)
    missing = {
        str(record.get("evidence_id", f"record-{index}")): [
            field for field in TRACEABILITY_FIELDS if not record.get(field)
        ]
        for index, record in enumerate(records, start=1)
    }
    missing = {key: value for key, value in missing.items() if value}
    return {
        "decisive_evidence_count": len(records),
        "faithful": not missing and bool(records),
        "missing_fields": missing,
        "limitation": "No decisive evidence was supplied." if not records else None,
    }


def serialise_evaluation(value: object) -> object:
    """Convert dataclass evaluation records into JSON-compatible data."""
    return asdict(value) if hasattr(value, "__dataclass_fields__") else value
