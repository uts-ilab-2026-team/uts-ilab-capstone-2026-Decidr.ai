import pytest

from decidr.explanation import render_explanation
from decidr.models import (
    AtomicClaim,
    ClaimOutcome,
    CredibilityAssessment,
    EvidenceMode,
    EvidenceRelationship,
    EvidenceTarget,
)
from decidr.reasoning import ReviewedEvidence, assess_claim, load_reasoning_config


def _credibility(identifier: str, mode: EvidenceMode) -> CredibilityAssessment:
    return CredibilityAssessment(
        assessment_id=f"CA-{identifier}",
        link_id=f"L-{identifier}",
        relevance=0.9,
        institutional_authority=0.8,
        directness=0.9,
        temporal_validity=0.9,
        independence=0.8,
        completeness=0.8,
        organisational_applicability=0.9,
        evidence_mode=mode,
        reviewer_justification="Direct and applicable evidence.",
    )


def _evidence(
    identifier: str,
    relationship: EvidenceRelationship,
    mode: EvidenceMode = EvidenceMode.OTHER,
    duplicate_group: str | None = None,
) -> ReviewedEvidence:
    return ReviewedEvidence(
        evidence_id=f"E-{identifier}",
        source_id=f"S-{identifier}",
        locator=f"section:test#block:{identifier}",
        relationship=relationship,
        target_match=True,
        scope_match=True,
        condition_match=True,
        temporal_match=True,
        credibility=_credibility(identifier, mode),
        duplicate_group=duplicate_group,
    )


@pytest.mark.parametrize(
    ("items", "outcome"),
    [
        ([_evidence("1", EvidenceRelationship.SUPPORT)], ClaimOutcome.SUPPORTED),
        ([_evidence("1", EvidenceRelationship.CONTRADICT)], ClaimOutcome.CONTRADICTED),
        (
            [
                _evidence("1", EvidenceRelationship.SUPPORT),
                _evidence("2", EvidenceRelationship.CONTRADICT),
            ],
            ClaimOutcome.CONTESTED,
        ),
        ([], ClaimOutcome.INSUFFICIENT),
    ],
)
def test_all_four_outcome_paths(items, outcome):
    assert assess_claim(items).outcome == outcome


def test_duplicates_do_not_increase_independent_corroboration():
    result = assess_claim(
        [
            _evidence("1", EvidenceRelationship.SUPPORT, duplicate_group="copy-a"),
            _evidence("2", EvidenceRelationship.SUPPORT, duplicate_group="copy-a"),
        ]
    )

    assert len(result.applicable) == 1
    assert any("dependent duplicate" in reason for _, reason in result.excluded)


def test_policy_practice_divergence_remains_contested_and_visible():
    result = assess_claim(
        [
            _evidence("1", EvidenceRelationship.SUPPORT, EvidenceMode.FORMAL_RULE),
            _evidence("2", EvidenceRelationship.CONTRADICT, EvidenceMode.OBSERVED_PRACTICE),
        ]
    )

    assert result.outcome == ClaimOutcome.CONTESTED
    assert result.traces[2]["details"]["divergence_visible"] is True


def test_policy_violation_does_not_contradict_existential_prescribed_rule_claim():
    result = assess_claim(
        [
            _evidence("1", EvidenceRelationship.SUPPORT, EvidenceMode.FORMAL_RULE),
            _evidence("2", EvidenceRelationship.CONTRADICT, EvidenceMode.OBSERVED_PRACTICE),
        ],
        evidence_target=EvidenceTarget.PRESCRIBED_RULE,
    )

    assert result.outcome == ClaimOutcome.SUPPORTED
    assert result.traces[2]["details"][
        "practice_violations_excluded_from_rule_contradiction"
    ] == ["E-2"]


def test_missing_record_is_gap_not_contradiction_and_explanation_is_cited():
    claim = AtomicClaim(
        claim_id="C1",
        subject="discount",
        predicate="requires",
        object="approval",
        claim_type="control",
        claim_text="Discount requires approval.",
    )
    item = _evidence("1", EvidenceRelationship.SUPPORT)
    result = assess_claim([item], expected_evidence_gaps=["Expected CRM approval record is absent."])
    explanation = render_explanation(claim, result)

    assert result.outcome == ClaimOutcome.SUPPORTED
    assert "not contradiction" in explanation
    assert item.evidence_id in explanation
    assert item.locator in explanation


def test_reasoning_threshold_is_configurable(tmp_path):
    config_path = tmp_path / "reasoning.json"
    config_path.write_text(
        '{"materiality_threshold": 0.99, "dimension_weights": '
        '{"relevance": 1, "institutional_authority": 1, "directness": 1, '
        '"temporal_validity": 1, "independence": 1, "completeness": 1, '
        '"organisational_applicability": 1}}',
        encoding="utf-8",
    )

    result = assess_claim(
        [_evidence("1", EvidenceRelationship.SUPPORT)],
        config=load_reasoning_config(config_path),
    )

    assert result.outcome == ClaimOutcome.INSUFFICIENT
