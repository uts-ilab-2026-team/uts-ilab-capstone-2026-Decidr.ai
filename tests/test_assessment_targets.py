"""Declared targets constrain admission; labels never prove semantic correctness."""

from dataclasses import replace
from datetime import date

from framework import CONFIG_PATH
from framework.config import GraphCredibilityConfig
import pytest
from test_assessment_adapter import CLAIM, FACET, make_item

from decidr.assessment_adapter import assess_prepared_facet
from decidr.assessment_response import serialize_facet_assessment


def run_target(target="unspecified", evidence_target="unspecified", mode="observed", **changes):
    item, passage = make_item()
    item = replace(
        item,
        source_class="approved_policy",
        interpretation=item.interpretation.model_copy(update={"mode": mode}),
        evidence_target=evidence_target,
        target_basis="Synthetic assertion about what this passage establishes.",
        **changes,
    )
    return assess_prepared_facet(
        claim_text=CLAIM,
        facet=FACET,
        as_of=date(2026, 7, 31),
        prepared=[item],
        evidence=[passage],
        config=GraphCredibilityConfig.load(CONFIG_PATH),
        assessment_target=target,
    )


@pytest.mark.parametrize(
    "target,mode",
    [
        ("recorded_statement", "observed"),
        ("underlying_event", "observed"),
        ("formal_rule", "formal"),
    ],
)
def test_matching_targets_preserved_without_rescoring(target, mode):
    legacy = run_target(mode=mode)
    targeted = run_target(target, target, mode)
    assert targeted.assessment == legacy.assessment
    assert targeted.inputs[0].edge_id is not None
    payload = serialize_facet_assessment(targeted)
    assert payload["assessment_target"] == target
    assert payload["target_validation"] == "supplied_declarations_checked"
    judgements = payload["inputs"][0]["supplied_judgements"]
    assert judgements["evidence_target"] == target
    assert judgements["target_basis"]
    assert payload["inputs"][0]["interpretation"]["citations"]


@pytest.mark.parametrize(
    "target,evidence_target",
    [
        (target, evidence_target)
        for target in ("recorded_statement", "underlying_event", "formal_rule")
        for evidence_target in (
            "recorded_statement",
            "underlying_event",
            "formal_rule",
            "unspecified",
        )
        if target != evidence_target
    ],
)
def test_cross_target_evidence_retained_without_decisive_edge(target, evidence_target):
    result = run_target(target, evidence_target)
    assert result.assessment.overall_outcome == "Insufficient evidence"
    assert result.inputs[0].edge_id is None
    assert result.inputs[0].reasons
    payload = serialize_facet_assessment(result)
    assert payload["inputs"][0]["interpretation"]["citations"]
    assert payload["inputs"][0]["supplied_judgements"]["evidence_target"] == evidence_target


@pytest.mark.parametrize(
    "target,mode",
    [
        ("recorded_statement", "formal"),
        ("underlying_event", "formal"),
        ("formal_rule", "observed"),
    ],
)
def test_lane_mismatch_is_not_scored(target, mode):
    result = run_target(target, target, mode)
    assert result.inputs[0].edge_id is None
    assert any("requires mode" in reason for reason in result.inputs[0].reasons)


def test_evidence_target_cannot_silently_use_legacy_request():
    result = run_target(evidence_target="recorded_statement")
    assert result.inputs[0].edge_id is None


def test_legacy_is_explicitly_unchecked():
    payload = serialize_facet_assessment(run_target())
    assert payload["assessment_target"] == "unspecified"
    assert payload["target_validation"] == "not_performed_legacy"
    assert any("Legacy target unspecified" in note for note in payload["limitations"])


@pytest.mark.parametrize("target", ["invented", None, True])
def test_invalid_target_rejected(target):
    with pytest.raises(ValueError):
        run_target(target=target)


def test_matching_target_does_not_override_scope_gate():
    result = run_target("recorded_statement", "recorded_statement", scope_matches=None)
    assert result.inputs[0].edge_id is None
    assert "scope_matches is false or unresolved." in result.inputs[0].reasons
