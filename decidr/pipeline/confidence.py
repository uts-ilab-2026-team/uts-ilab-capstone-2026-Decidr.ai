"""Confidence — one reconciled (score, tier) axis per facet and per whole claim."""

from __future__ import annotations

from typing import TYPE_CHECKING

from decidr.graph.models import FactAssessment

if TYPE_CHECKING:
    from decidr.pipeline.types import ClaimAssessment

# Confidence is ONE reconciled axis: the 0-1 score and its categorical tier come from the same
# calculation, so the number and the label can never disagree. The score rewards BOTH evidence
# strength (peak + mean of the aligned material sources, so more strong evidence scores higher and
# weak evidence lower) AND corroboration (independent origins): a lone strong source lands in
# Moderate, two independent decisive sources unlock Higher. This is confidence-in-evidence for the
# STATED outcome, never a probability the claim is true (per the system card).
_HIGHER_BAND = 0.75
_MODERATE_BAND = 0.45
_PEAK_WEIGHT = 0.5  # strength = _PEAK_WEIGHT * peak + (1 - _PEAK_WEIGHT) * mean
_CORROB_BASE = 0.65  # multiplier for a single independent origin
_CORROB_STEP = 0.20  # added per extra independent origin, capped at 1.0
_TIER_ORDER = {"Lower confidence": 0, "Moderate confidence": 1, "Higher confidence": 2}


def _confidence_band(score: float) -> str:
    """Map a 0-1 confidence score to its tier — the single source of the categorical label."""
    if score >= _HIGHER_BAND:
        return "Higher confidence"
    if score >= _MODERATE_BAND:
        return "Moderate confidence"
    return "Lower confidence"


def _facet_confidence(
    assessment: FactAssessment | None, outcome: str, gaps: tuple[str, ...]
) -> tuple[float, str]:
    """Reconciled (score, tier) for one facet, aligned to the decided outcome.

    For a decided outcome the score blends strength and corroboration of the aligned material
    evidence and the tier is exactly its band, so ``_confidence_band(score) == tier`` always holds.
    Non-decided outcomes carry no single-direction confidence: Insufficient -> (0.0, Lower),
    Contested -> (0.0, Moderate), where the categorical label does the explaining.
    """
    if outcome == "Insufficient evidence":
        return 0.0, "Lower confidence"
    if outcome == "Contested":
        return 0.0, "Moderate confidence"
    if outcome not in {"Supported", "Contradicted"} or assessment is None:
        return 0.0, "Lower confidence"

    stance = "support" if outcome == "Supported" else "contradict"
    # Collapse to independent origins: each distinct document counts once, at its strongest score.
    best_by_origin: dict[str, float] = {}
    non_material_divergence = False
    for edge in assessment.evidence:
        if edge.stance == "contradict" and edge.applicable and not edge.material:
            non_material_divergence = True
        if edge.material and edge.stance == stance and edge.materiality_score is not None:
            prev = best_by_origin.get(edge.document_id, 0.0)
            if edge.materiality_score > prev:
                best_by_origin[edge.document_id] = edge.materiality_score
    if not best_by_origin:
        return 0.0, "Lower confidence"

    scores = list(best_by_origin.values())
    origins = len(scores)
    peak = max(scores)
    mean = sum(scores) / origins
    strength = _PEAK_WEIGHT * peak + (1.0 - _PEAK_WEIGHT) * mean
    corroboration = min(1.0, _CORROB_BASE + _CORROB_STEP * (origins - 1))
    score = strength * corroboration
    # Caveat cap: an unresolved gap or applicable non-material dissent keeps a facet out of Higher.
    if (gaps or non_material_divergence) and score >= _HIGHER_BAND:
        score = _HIGHER_BAND - 0.001
    score = round(score, 3)
    return score, _confidence_band(score)


def _reconcile_confidence(
    result: ClaimAssessment,
) -> tuple[dict[str, tuple[float, str]], float, str]:
    """Recompute per-facet and whole-claim confidence as one consistent (score, tier) per level.

    Whole-claim confidence is weakest-link: a conjunctive claim is only as sure as its weakest
    decisive facet, so the claim score is the minimum facet score and the claim tier the lowest
    facet tier (both drawn from the same per-facet pairs).
    """
    facet_conf: dict[str, tuple[float, str]] = {}
    for facet in result.verdict.facets:
        assessment = result.facet_assessments.get(facet.facet)
        gaps = assessment.gaps if assessment else ()
        facet_conf[facet.facet] = _facet_confidence(assessment, facet.outcome, gaps)

    decisive = [facet_conf[facet.facet] for facet in result.verdict.facets if facet.decisive]
    if not decisive:
        return facet_conf, 0.0, "Lower confidence"
    claim_score = round(min(score for score, _ in decisive), 3)
    claim_tier = min((tier for _, tier in decisive), key=lambda tier: _TIER_ORDER[tier])
    return facet_conf, claim_score, claim_tier
