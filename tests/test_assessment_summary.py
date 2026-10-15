"""Assessment summaries must accurately describe the supplied evidence."""

from dataclasses import replace

import pytest

from decidr.graph.credibility import GraphCredibilityFramework
from decidr.graph.models import EdgeAssessment


@pytest.fixture
def evidence():
    return EdgeAssessment(
        edge_id="edge:test",
        document_id="document:test",
        document_title="Test source",
        mode="formal",
        attests_value="A competing assertion.",
        stance="contradict",
        source_class="approved_policy",
        lifecycle_status="current",
        applicable=True,
        materiality_score=0.8,
        material=True,
        dimensions={},
        limitations=(),
        trace=(),
    )


def summarize(reviewed=(), related=()):
    return GraphCredibilityFramework._summary(
        formal="Contested",
        observed="Insufficient evidence",
        overall="Contested",
        confidence="Moderate confidence",
        reviewed=reviewed,
        related=related,
    )


@pytest.mark.parametrize("mode,label", [("formal", "Formal"), ("observed", "Observed")])
@pytest.mark.parametrize("material", [True, False])
def test_counterevidence_uses_its_own_mode_and_materiality(evidence, mode, label, material):
    item = replace(
        evidence,
        mode=mode,
        material=material,
        materiality_score=0.8 if material else 0.2,
    )
    summary = summarize((item,))
    other_label = "Observed" if mode == "formal" else "Formal"

    if material:
        assert f"{label} evidence includes material counterevidence." in summary
        assert "non-material counterevidence" not in summary
    else:
        assert (
            f"{label} evidence includes non-material counterevidence retained for context."
        ) in summary
        assert "includes material counterevidence" not in summary

    assert f"{other_label} evidence includes" not in summary
    assert "practice divergence" not in summary.lower()


@pytest.mark.parametrize("mode", ["formal", "observed"])
def test_excluded_counterevidence_is_not_described_as_applicable(evidence, mode):
    item = replace(
        evidence,
        mode=mode,
        applicable=False,
        material=False,
        materiality_score=None,
    )

    assert "counterevidence" not in summarize((item,))


@pytest.mark.parametrize("mode", ["formal", "observed"])
@pytest.mark.parametrize("stance", ["support", "qualify"])
def test_support_and_qualifications_are_not_called_counterevidence(evidence, mode, stance):
    item = replace(evidence, mode=mode, stance=stance)

    assert "counterevidence" not in summarize((item,))


def test_summary_preserves_supplied_outcomes_and_confidence():
    assert summarize() == (
        "Formal evidence: Contested. "
        "Observed evidence: Insufficient evidence. "
        "Combined outcome: Contested; moderate confidence."
    )


def test_mixed_counterevidence_is_reported_once_per_category(evidence):
    formal_material = evidence
    formal_context = replace(
        evidence, edge_id="edge:context", material=False, materiality_score=0.2
    )
    observed_material = replace(
        evidence, edge_id="edge:observed", mode="observed"
    )
    reviewed = (
        formal_material,
        formal_context,
        observed_material,
        replace(formal_material, edge_id="edge:copy"),
    )
    summary = summarize(reviewed)

    assert summary.count("Formal evidence includes material counterevidence.") == 1
    assert summary.count(
        "Formal evidence includes non-material counterevidence retained for context."
    ) == 1
    assert summary.count("Observed evidence includes material counterevidence.") == 1
    assert summary == summarize(tuple(reversed(reviewed)))


def test_related_facts_do_not_automatically_claim_to_narrow_scope():
    assert "Related Facts" not in summarize()

    summary = summarize(related=("A linked contextual fact.",))

    assert "Related Facts are included as contextual qualifications." in summary
    assert "narrow the scope" not in summary
