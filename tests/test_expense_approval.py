"""Expense thresholds, context, and explicit unsupported-family evaluation."""

import json
from pathlib import Path

import pytest

from decidr.approval_context import check_approval_context
from decidr.approval_propositions import compare_approval_rules
from decidr.expense_approval import parse_expense_rule

RULE = "Expense claims over $500 require approval from Finance before reimbursement is processed."


@pytest.mark.parametrize(
    "claim,expected",
    [
        (RULE, True),
        (RULE.replace("over $500", "over $600"), True),
        (RULE.replace("over $500", "at least $500"), False),
        (RULE.replace("over $500", "exactly $500"), False),
        (RULE.replace("over $500", "exactly $500.01"), True),
        (RULE.replace("$500", "£500"), False),
        (RULE.replace("Finance", "Sales"), False),
        (RULE.replace("before", "after"), False),
        (RULE.replace("require approval", "require written approval"), False),
    ],
)
def test_expense_comparison(claim, expected):
    assert compare_approval_rules(claim, RULE)["evidence_entails_claim"] is expected


@pytest.mark.parametrize(
    "text",
    [
        RULE + " Unless urgent.",
        RULE.replace("Finance", "Finance or Sales"),
        RULE.replace("over $500", "over $500 or less"),
        RULE.replace("$500", "500"),
        RULE.replace("over $500", "below $-1"),
        "Expense claims require Finance approval.",
    ],
)
def test_incomplete_or_qualified_rules_abstain(text):
    assert parse_expense_rule(text) is None


@pytest.mark.parametrize("threshold,compatible", [("500", True), ("499", True), ("501", False)])
def test_context_does_not_ignore_overlapping_permissions(threshold, compatible):
    text = (
        RULE
        + f"\n2. Expense claims of ${threshold} or less may be approved by the employee's direct manager.\n3. All expense claims must include an itemised receipt."
    )
    assert check_approval_context(text, 0, len(RULE))["compatible"] is compatible


def test_unknown_expense_exception_blocks_support():
    assert not check_approval_context(RULE + " Except urgent claims.", 0, len(RULE))["compatible"]


def test_corpus_shaped_evaluation_set():
    cases = json.loads(
        (Path(__file__).parents[1] / "evaluation/approval_rules/cases.json").read_text()
    )
    for case in cases:
        comparison = compare_approval_rules(case["claim"], case["evidence"])
        outcome = (
            "unsupported"
            if comparison is None
            else "match"
            if comparison["evidence_entails_claim"]
            else "unresolved_difference"
        )
        assert outcome == case["expected_wording"], case["id"]
