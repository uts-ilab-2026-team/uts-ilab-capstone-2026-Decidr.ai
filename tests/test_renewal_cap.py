"""Renewal cap semantics and conservative exception/authority gates."""

import pytest
from test_authority_resolution import chain, resolve

from decidr.approval_context import check_approval_context
from decidr.approval_propositions import compare_approval_rules
from decidr.renewal_cap import parse_renewal_cap

RULE = "Renewal discounts are capped at 10% off the account's current contracted rate."
CONTEXT = "\n2. No exceptions to the renewal discount cap are provided for under this policy.\n3. Renewal discount decisions are made by the Account Executive responsible for the account, in consultation with Customer Success on relationship health."


@pytest.mark.parametrize(
    "claim,expected",
    [
        (RULE, True),
        (RULE.replace("10%", "10.0%"), True),
        (RULE.replace("Renewal discounts are capped at", "The renewal discount cap is"), True),
        (RULE.replace("10%", "15%"), False),
        (RULE.replace("10%", "5%"), False),
    ],
)
def test_explicit_cap_comparison(claim, expected):
    assert compare_approval_rules(claim, RULE)["evidence_entails_claim"] is expected


@pytest.mark.parametrize(
    "claim",
    [
        RULE.replace("current contracted rate", "list price"),
        RULE.replace("Renewal", "New-business"),
        RULE + " With exceptions.",
        RULE.replace("10%", "101%"),
        RULE.replace("10%", "-1%"),
        RULE.replace("capped at", "not capped at"),
        "Renewal discounts are capped at 10%.",
    ],
)
def test_incomplete_or_different_basis_abstains(claim):
    assert parse_renewal_cap(claim) is None
    assert compare_approval_rules(claim, RULE) is None


def test_adjacent_policy_conditions_retained():
    r = check_approval_context(RULE + CONTEXT, 0, len(RULE))
    assert r["compatible"]
    assert len(r["clauses"]) == 2
    assert not check_approval_context(
        RULE + CONTEXT + " Managers may waive the cap.", 0, len(RULE)
    )["compatible"]


def renewal_chain():
    sources, passages = chain()
    passages[0].text = RULE
    for p in passages[2:]:
        p.text = p.text.replace("new-business deals", "renewal discounts")
    return sources, passages


def test_renewal_explicit_authority_chain():
    sources, passages = renewal_chain()
    assert resolve(sources, passages)["authority_verified"] is True
    passages[3].text = passages[3].text.replace("renewal discounts", "expense claims")
    assert resolve(sources, passages)["authority_verified"] is None


def test_renewal_authority_cannot_come_from_title_or_operational_rights():
    sources, passages = renewal_chain()
    passages[3].text = "POL-01: Alex Smith is Head of Sales and approves renewal discounts."
    r = resolve(sources, passages)
    assert r["authority_verified"] is None
    assert "for renewal discounts on" in " ".join(r["review_guidance"])
