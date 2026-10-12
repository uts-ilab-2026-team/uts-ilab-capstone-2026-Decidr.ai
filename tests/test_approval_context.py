"""Regression for the exported POL-01 assessment and unsafe surrounding clauses."""

import pytest

from decidr.approval_context import check_approval_context

RULE = "Any discount of **15% or greater** off list price on a new-business deal requires written approval from the Head of Finance & People Ops before the deal is marked Closed Won in the CRM."
CONTEXT = "\n2. Approval must be recorded in the CRM's `approval_record` field, referencing the approver and date.\n3. Discounts below 15% may be approved by the deal's Account Executive without further sign-off.\n4. This policy applies to new-business deals. Renewal discounting is governed separately by POL-06."


def test_real_numbered_policy_context():
    result = check_approval_context("1. " + RULE + CONTEXT, 3, 3 + len(RULE))
    assert result["compatible"]
    assert len(result["clauses"]) == 4


@pytest.mark.parametrize(
    "context",
    [
        " Except for urgent deals.",
        " This policy applies to renewal deals.",
        " Discounts below 20% may be approved by the deal's Account Executive without further sign-off.",
        " Approval is not required.",
        " This requirement is waived during October.",
        " Approval must be recorded only if requested.",
        "\n2. Any discount of 15% or greater off list price on a new-business deal requires written approval from Sales before the deal is marked Closed Won in the CRM.",
    ],
)
def test_unsupported_or_overlapping_context_blocks_support(context):
    assert not check_approval_context(RULE + context, 0, len(RULE))["compatible"]


def test_preceding_exception_is_not_discarded():
    prefix = "Except for urgent deals.\n1. "
    assert not check_approval_context(prefix + RULE, len(prefix), len(prefix) + len(RULE))[
        "compatible"
    ]
