"""Tests for the outcome-aligned confidence-in-evidence score (to_payload).

The score is a 0-1 measure of how strongly the evidence backs the STATED outcome (not a probability
the claim is true). It is tied to the outcome so the number can never disagree with the verdict:
Supported -> strongest material support; Contradicted -> strongest material contradict;
Insufficient/Contested -> 0.0.
"""

from types import SimpleNamespace

from decidr.assess_claim import _facet_confidence_score


def _edge(stance: str, material: bool, score: float | None):
    return SimpleNamespace(stance=stance, material=material, materiality_score=score)


def _assessment(*edges):
    return SimpleNamespace(evidence=list(edges))


def test_supported_uses_strongest_material_support():
    a = _assessment(
        _edge("support", True, 0.938),
        _edge("contradict", True, 0.50),  # opposing side ignored for a Supported outcome
        _edge("support", False, 0.99),  # non-material ignored
    )
    assert _facet_confidence_score(a, "Supported") == 0.938


def test_contradicted_uses_strongest_material_contradict():
    a = _assessment(
        _edge("contradict", True, 0.737),
        _edge("support", False, 0.184),
        _edge("qualify", True, 0.90),  # qualify never counts
    )
    assert _facet_confidence_score(a, "Contradicted") == 0.737


def test_insufficient_is_zero_even_with_a_strong_edge():
    # The flaw we fixed: a lone strong edge must NOT inflate an Insufficient verdict.
    a = _assessment(_edge("support", True, 0.875))
    assert _facet_confidence_score(a, "Insufficient evidence") == 0.0


def test_contested_is_zero():
    a = _assessment(_edge("support", True, 0.80), _edge("contradict", True, 0.80))
    assert _facet_confidence_score(a, "Contested") == 0.0


def test_supported_without_material_support_is_zero():
    a = _assessment(_edge("support", False, 0.90), _edge("contradict", True, 0.70))
    assert _facet_confidence_score(a, "Supported") == 0.0


def test_qualify_and_context_are_excluded():
    a = _assessment(
        _edge("qualify", True, 0.95),
        _edge("context", True, 0.95),
        _edge("support", True, 0.60),
    )
    assert _facet_confidence_score(a, "Supported") == 0.60


def test_none_assessment_is_zero():
    assert _facet_confidence_score(None, "Supported") == 0.0
