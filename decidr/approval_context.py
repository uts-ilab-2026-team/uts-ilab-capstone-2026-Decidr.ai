"""Bounded checks of adjacent policy statements, without discarding exceptions."""

from decimal import Decimal
import re

from decidr.approval_propositions import parse_approval_rule
from decidr.expense_approval import expense_context_reason, parse_expense_rule
from decidr.interpretation_engine import _sentences
from decidr.renewal_cap import parse_renewal_cap, renewal_context_reason


def check_approval_context(text: str, start: int, end: int) -> dict:
    """Recognise only explicit compatible clauses; unknown context blocks support."""
    rule = parse_approval_rule(text[start:end])
    expense = parse_expense_rule(text[start:end])
    renewal = parse_renewal_cap(text[start:end])
    findings = []
    for remainder in (text[:start], text[end:]):
        # List markers are formatting, including the marker before the focal quote.
        remainder = re.sub(r"(?m)^\s*\d+[.)]\s*", "", remainder)
        for left, right in _sentences(remainder):
            clause = " ".join(
                remainder[left:right]
                .casefold()
                .replace("**", "")
                .replace("`", "")
                .rstrip(".")
                .split()
            )
            if not clause:
                continue
            reason = expense_context_reason(clause, expense) if expense else None
            if renewal:
                reason = renewal_context_reason(clause)
            if rule:
                if (
                    clause
                    == "approval must be recorded in the crm's approval_record field, referencing the approver and date"
                ):
                    reason = (
                        "Approval recording requirement retained; it does not remove the rule."
                    )
                elif clause == f"this policy applies to {rule.deal_scope} deals":
                    reason = "The surrounding scope agrees with the cited rule."
                elif rule.deal_scope == "new-business" and re.fullmatch(
                    r"renewal discounting is governed separately by [a-z][a-z0-9]*-\d+", clause
                ):
                    reason = "The renewal reference concerns a different business scope."
                else:
                    below = re.fullmatch(
                        r"discounts below (\d+(?:\.\d+)?)% may be approved by the deal's account executive without further sign-off",
                        clause,
                    )
                    if (
                        below
                        and rule.boundary in {"ge", "gt", "eq"}
                        and Decimal(below[1]) <= Decimal(rule.percentage)
                    ):
                        reason = "The lower-discount permission does not overlap the cited rule's range."
            findings.append(
                {
                    "text": remainder[left:right],
                    "compatible": reason is not None,
                    "reason": reason
                    or "Unrecognised or potentially qualifying context requires review.",
                }
            )
    return {
        "method": "approval-context-v1",
        "compatible": (rule is not None or expense is not None or renewal is not None)
        and all(item["compatible"] for item in findings),
        "clauses": findings,
        "limitation": "Only adjacent statements in this stored passage were checked; this is not a whole-document interpretation.",
    }
