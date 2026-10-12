"""Stored non-approval cannot be bypassed by positive supplied judgements."""

from dataclasses import replace

from framework import CONFIG_PATH
from framework.config import GraphCredibilityConfig
import pytest
from test_assessment_adapter import CLAIM, DAY, FACET, make_item

from decidr.assessment_adapter import assess_prepared_facet


def assess(status, mode="formal", approval_key="approved"):
    item, passage = make_item()
    item = replace(
        item, source_class="approved_policy", approval_key=approval_key,
        source=item.source.model_copy(update={"approval_status": status}),
        interpretation=item.interpretation.model_copy(update={"mode": mode}),
        evidence_target="formal_rule" if mode == "formal" else "recorded_statement",
        target_basis="Synthetic supplied target judgement.",
    )
    return assess_prepared_facet(
        claim_text=CLAIM, facet=FACET, as_of=DAY, prepared=[item], evidence=[passage],
        assessment_target=item.evidence_target,
        config=GraphCredibilityConfig.load(CONFIG_PATH),
    )


@pytest.mark.parametrize("status", [
    "Not approved", "Not yet approved", "Never approved", "Unapproved",
    "Approved; not yet approved", "Not formally approved",
])
def test_negative_stored_approval_blocks_formal_even_with_positive_supplied_flags(status):
    result = assess(status)
    assert result.inputs[0].edge_id is None
    assert result.inputs[0].supplied_judgements["authority_verified"] is True
    assert result.inputs[0].source.approval_status == status
    assert any("Stored own-document approval" in r for r in result.inputs[0].reasons)
    assert result.assessment.overall_outcome == "Insufficient evidence"


@pytest.mark.parametrize("key", ["draft", "unapproved"])
def test_negative_supplied_status_cannot_be_promoted_by_quality_scores(key):
    result = assess("Approved", approval_key=key)
    assert result.inputs[0].edge_id is None


def test_referenced_nonapproval_does_not_block_own_approved_rule():
    result = assess("Approved (see REF-999, never approved)")
    assert result.inputs[0].edge_id is not None


def test_recorded_statement_does_not_require_policy_adoption():
    result = assess("Never approved", mode="observed")
    assert result.inputs[0].edge_id is not None
    assert not any("Stored own-document approval" in r for r in result.inputs[0].reasons)
