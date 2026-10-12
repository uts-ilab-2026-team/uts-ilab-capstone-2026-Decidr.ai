"""Expense rules share authority safeguards; operational rights never grant adoption."""

import pytest
from test_authority_resolution import chain, resolve


def expense_chain():
    sources, passages = chain()
    passages[
        0
    ].text = (
        "Expense claims over $500 require approval from Finance before reimbursement is processed."
    )
    for p in passages[2:]:
        p.text = p.text.replace("new-business deals", "expense claims")
    return sources, passages


def test_explicit_expense_chain_resolves_with_exact_citations():
    sources, passages = expense_chain()
    result = resolve(sources, passages)
    assert result["authority_verified"] is True
    for c in result["citations"]:
        p = next(p for p in passages if p.evidence_id == c["evidence_id"])
        assert p.text[c["start"] : c["end"]] == c["quotation"]


@pytest.mark.parametrize(
    "index,before,after",
    [
        (2, "adopted", "discussed"),
        (2, "version 3.0", "version 2.0"),
        (2, "expense claims", "new-business deals"),
        (3, "Alex Smith", "Pat Jones"),
        (3, "to adopt", "to approve expenses under"),
        (3, "2024-01-01", "2025-03-01"),
        (3, "2025-12-31", "2025-01-01"),
        (3, "expense claims", "new-business deals"),
    ],
)
def test_mismatched_expense_chains_abstain(index, before, after):
    sources, passages = expense_chain()
    passages[index].text = passages[index].text.replace(before, after)
    assert resolve(sources, passages)["authority_verified"] is None


def test_deferred_meeting_is_not_expense_adoption():
    sources, passages = expense_chain()
    passages[2].text = "POL-01: Deferred. No option was selected."
    result = resolve(sources, passages)
    assert result["authority_verified"] is None
    assert not next(c for c in result["checks"] if c["name"] == "adoption")["passed"]
    assert any(c["quotation"] == passages[2].text for c in result["citations"])


def test_missing_rights_requests_expense_specific_review():
    sources, passages = expense_chain()
    result = resolve(sources, passages[:3])
    assert result["authority_verified"] is None
    assert "for expense claims on 2025-02-24" in " ".join(result["review_guidance"])


def test_undated_rights_cannot_verify_expense_chain():
    sources, passages = expense_chain()
    sources["test:rights"].creation_date = None
    assert resolve(sources, passages)["authority_verified"] is None
