"""Deterministic, traceable claim-outcome reasoning."""

from dataclasses import dataclass, field
import json
from pathlib import Path

from decidr.models import (
    ClaimOutcome,
    ConfidenceLevel,
    CredibilityAssessment,
    EvidenceMode,
    EvidenceRelationship,
    EvidenceTarget,
)


@dataclass(frozen=True, slots=True)
class ReviewedEvidence:
    evidence_id: str
    source_id: str
    locator: str
    relationship: EvidenceRelationship
    target_match: bool
    scope_match: bool
    condition_match: bool
    temporal_match: bool
    credibility: CredibilityAssessment
    duplicate_group: str | None = None
    lifecycle_status: str = "current"
    superseded_is_temporally_justified: bool = False
    policy_practice_violation: bool = False


@dataclass(frozen=True, slots=True)
class ReasoningConfig:
    materiality_threshold: float = 0.5
    dimension_weights: dict[str, float] = field(
        default_factory=lambda: {
            "relevance": 1.0,
            "institutional_authority": 1.0,
            "directness": 1.0,
            "temporal_validity": 1.0,
            "independence": 1.0,
            "completeness": 1.0,
            "organisational_applicability": 1.0,
        }
    )


@dataclass(frozen=True, slots=True)
class ReasoningResult:
    outcome: ClaimOutcome
    confidence: ConfidenceLevel
    applicable: tuple[ReviewedEvidence, ...]
    excluded: tuple[tuple[ReviewedEvidence, str], ...]
    traces: tuple[dict[str, object], ...]
    gaps: tuple[str, ...]


def load_reasoning_config(path: Path) -> ReasoningConfig:
    """Load reviewable thresholds and dimension weights from JSON."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    return ReasoningConfig(
        materiality_threshold=float(payload["materiality_threshold"]),
        dimension_weights={
            key: float(value) for key, value in payload["dimension_weights"].items()
        },
    )


def credibility_value(item: CredibilityAssessment, config: ReasoningConfig) -> float:
    """Calculate a transparent configurable materiality value, not truth probability."""
    values = {
        "relevance": item.relevance,
        "institutional_authority": item.institutional_authority,
        "directness": item.directness,
        "temporal_validity": item.temporal_validity,
        "independence": item.independence,
        "completeness": item.completeness,
        "organisational_applicability": item.organisational_applicability,
    }
    total_weight = sum(config.dimension_weights.values())
    if total_weight <= 0:
        raise ValueError("Credibility dimension weights must sum to more than zero")
    return (
        sum(values[key] * weight for key, weight in config.dimension_weights.items())
        / total_weight
    )


def assess_claim(
    reviewed: list[ReviewedEvidence],
    expected_evidence_gaps: list[str] | None = None,
    config: ReasoningConfig | None = None,
    evidence_target: EvidenceTarget | None = None,
) -> ReasoningResult:
    """Apply applicability, version, dependence, divergence, and outcome rules."""
    config = config or ReasoningConfig()
    traces: list[dict[str, object]] = []
    excluded: list[tuple[ReviewedEvidence, str]] = []
    applicable: list[ReviewedEvidence] = []
    for item in reviewed:
        if item.source_id.startswith("phase1:"):
            excluded.append((item, "framework-development-only release; excluded from modelling"))
            continue
        matches = (item.target_match, item.scope_match, item.condition_match, item.temporal_match)
        if item.relationship == EvidenceRelationship.NOT_APPLICABLE or not all(matches):
            excluded.append((item, "failed applicability dimensions or marked not applicable"))
        elif item.lifecycle_status == "superseded" and not item.superseded_is_temporally_justified:
            excluded.append((item, "superseded source without period justification"))
        else:
            applicable.append(item)
    traces.append(
        {
            "rule_id": "R1_APPLICABILITY_AND_TIME",
            "evidence_ids": [item.evidence_id for item in applicable],
            "details": {"excluded_count": len(excluded)},
        }
    )

    independent: list[ReviewedEvidence] = []
    seen_groups: set[tuple[str, EvidenceRelationship]] = set()
    for item in sorted(
        applicable, key=lambda value: credibility_value(value.credibility, config), reverse=True
    ):
        group = item.duplicate_group or item.source_id
        key = (group, item.relationship)
        if key in seen_groups and item.relationship != EvidenceRelationship.CONTEXTUAL:
            excluded.append((item, f"dependent duplicate group {group}"))
            continue
        seen_groups.add(key)
        independent.append(item)
    traces.append(
        {
            "rule_id": "R2_DEPENDENCE_ADJUSTMENT",
            "evidence_ids": [item.evidence_id for item in independent],
            "details": {
                "duplicate_groups_counted_once": sorted({group for group, _ in seen_groups})
            },
        }
    )

    material = [
        item
        for item in independent
        if credibility_value(item.credibility, config) >= config.materiality_threshold
    ]
    supporting = [item for item in material if item.relationship == EvidenceRelationship.SUPPORT]
    all_contradicting = [
        item for item in material if item.relationship == EvidenceRelationship.CONTRADICT
    ]
    practice_divergence = [
        item
        for item in all_contradicting
        if evidence_target == EvidenceTarget.PRESCRIBED_RULE
        and item.credibility.evidence_mode == EvidenceMode.OBSERVED_PRACTICE
    ]
    contradicting = [item for item in all_contradicting if item not in practice_divergence]
    modes = {
        "support": sorted({item.credibility.evidence_mode.value for item in supporting}),
        "contradict": sorted({item.credibility.evidence_mode.value for item in all_contradicting}),
    }
    explicit_divergence = [
        item
        for item in material
        if item.policy_practice_violation
        and evidence_target == EvidenceTarget.PRESCRIBED_RULE
        and item.credibility.evidence_mode == EvidenceMode.OBSERVED_PRACTICE
    ]
    divergence = (
        bool((supporting or contradicting) and explicit_divergence)
        or bool(supporting and all_contradicting)
        and (
            EvidenceMode.FORMAL_RULE.value in modes["support"] + modes["contradict"]
            and EvidenceMode.OBSERVED_PRACTICE.value in modes["support"] + modes["contradict"]
        )
    )
    traces.append(
        {
            "rule_id": "R3_POLICY_PRACTICE_SEPARATION",
            "evidence_ids": [
                item.evidence_id for item in supporting + all_contradicting + explicit_divergence
            ],
            "details": {
                "modes": modes,
                "divergence_visible": divergence,
                "practice_violations_excluded_from_rule_contradiction": [
                    item.evidence_id for item in practice_divergence + explicit_divergence
                ],
            },
        }
    )

    if supporting and contradicting:
        outcome = ClaimOutcome.CONTESTED
        outcome_rule = "R4_MATERIAL_CONFLICT"
    elif supporting:
        outcome = ClaimOutcome.SUPPORTED
        outcome_rule = "R4_SUPPORT_WITHOUT_MATERIAL_CONTRADICTION"
    elif contradicting:
        outcome = ClaimOutcome.CONTRADICTED
        outcome_rule = "R4_CONTRADICTION_WITHOUT_MATERIAL_SUPPORT"
    else:
        outcome = ClaimOutcome.INSUFFICIENT
        outcome_rule = "R4_NO_DECISIVE_APPLICABLE_EVIDENCE"
    traces.append(
        {
            "rule_id": outcome_rule,
            "evidence_ids": [item.evidence_id for item in supporting + contradicting],
            "details": {
                "outcome": outcome.value,
                "materiality_threshold": config.materiality_threshold,
            },
        }
    )

    gaps = tuple(expected_evidence_gaps or [])
    if gaps:
        traces.append(
            {
                "rule_id": "R5_MISSINGNESS_IS_A_GAP",
                "evidence_ids": [],
                "details": {"gaps": list(gaps), "treated_as_contradiction": False},
            }
        )
    decisive_count = len(
        {item.duplicate_group or item.source_id for item in supporting + contradicting}
    )
    if decisive_count >= 2 and not gaps:
        confidence = ConfidenceLevel.HIGHER
    elif decisive_count >= 1:
        confidence = ConfidenceLevel.MODERATE if not gaps else ConfidenceLevel.LOWER
    else:
        confidence = ConfidenceLevel.LOWER
    return ReasoningResult(
        outcome=outcome,
        confidence=confidence,
        applicable=tuple(independent),
        excluded=tuple(excluded),
        traces=tuple(traces),
        gaps=gaps,
    )
