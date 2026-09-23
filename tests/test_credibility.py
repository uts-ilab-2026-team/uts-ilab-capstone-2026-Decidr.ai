import pytest

from decidr.credibility import CredibilityFramework, CredibilityFrameworkError
from decidr.models import (
    ClaimEvidenceLink,
    CredibilityAssessment,
    EvidenceMode,
    EvidenceRelationship,
)
from decidr.reasoning import ReasoningConfig


def _link(**updates) -> ClaimEvidenceLink:
    values = {
        "link_id": "L1",
        "claim_id": "C1",
        "evidence_id": "E1",
        "relationship": EvidenceRelationship.SUPPORT,
        "applicability_reason": "The target, scope, conditions and period match.",
        "target_match": True,
        "scope_match": True,
        "condition_match": True,
        "temporal_match": True,
        "reviewer": "reviewer-a",
    }
    values.update(updates)
    return ClaimEvidenceLink(**values)


def _assessment(**updates) -> CredibilityAssessment:
    values = {
        "assessment_id": "CR1",
        "link_id": "L1",
        "relevance": 1.0,
        "institutional_authority": 0.5,
        "directness": 1.0,
        "temporal_validity": 0.5,
        "independence": 1.0,
        "completeness": 0.5,
        "organisational_applicability": 1.0,
        "evidence_mode": EvidenceMode.FORMAL_RULE,
        "reviewer_justification": "Direct, current and in scope.",
    }
    values.update(updates)
    return CredibilityAssessment(**values)


def test_framework_calculates_explainable_materiality_not_truth_probability():
    decision = CredibilityFramework().evaluate_evidence(_link(), _assessment())

    assert decision["applicable"] is True
    assert decision["material"] is True
    assert decision["materiality_score"] == pytest.approx(5.5 / 7)
    assert len(decision["dimension_breakdown"]) == 7
    assert "probability" not in decision["explanation"].casefold()


def test_failed_applicability_gate_prevents_credibility_scoring():
    decision = CredibilityFramework().evaluate_evidence(_link(scope_match=False), _assessment())

    assert decision["applicable"] is False
    assert decision["materiality_score"] is None
    assert decision["failed_applicability_checks"] == ["scope_match"]


def test_assessment_must_belong_to_the_reviewed_link():
    with pytest.raises(CredibilityFrameworkError, match="must refer"):
        CredibilityFramework().evaluate_evidence(_link(), _assessment(link_id="L2"))


def test_framework_rejects_incomplete_dimension_configuration():
    with pytest.raises(CredibilityFrameworkError, match="exactly seven"):
        CredibilityFramework(ReasoningConfig(dimension_weights={"relevance": 1.0}))
