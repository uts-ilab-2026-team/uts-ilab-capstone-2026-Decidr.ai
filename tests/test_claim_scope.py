"""Scope questions are optional, corpus-backed and preserve original wording."""

import pytest

from decidr.claim_scope import scope_context
from decidr.corpus.models import Evidence, Source


def corpus():
    sources = {name: Source(source_id=name, title=name, original_file_path="test.md",
                           source_type="policy", checksum="a" * 64, ingestion_status="ingested")
               for name in ("new", "renewal")}
    evidence = [Evidence(evidence_id=name, source_id=name, locator="p:1", text=text,
                          source_type="policy", heading="Formal requirements", extraction_method="test")
                for name, text in [("new", "Approval is required for new-business deals."),
                                   ("renewal", "Renewal discounts are capped.")]]
    return sources, evidence


def check(claim, answer=None):
    return scope_context(claim, answer, *corpus())


def test_missing_scope_question_requires_two_documented_scopes():
    claim = "  Discounts above 15% require Finance approval.  "
    result = check(claim)
    assert result["status"] == "clarification_available"
    assert result["facet"] == claim
    assert result["answer"] is None
    assert len(result["basis"]) == 2
    assert "All deal types" in result["options"]
    sources, evidence = corpus()
    assert scope_context(claim, None, sources, evidence[:1])["status"] == "not_requested"


@pytest.mark.parametrize("claim", [
    "New-business discounts require approval.", "Renewal discounts require approval.",
    "All discounts require approval.", "Any discount requires approval.",
    "Both deal types require discount approval.", "DEAL-789 needs discount approval.",
    "New hires finish onboarding.", "The discount was 15%.",
])
def test_explicit_scope_universal_claim_record_or_unrelated_claim_not_interrupted(claim):
    assert check(claim)["status"] == "not_requested"


def test_answer_is_attached_without_rewriting_or_verifying_claim():
    claim = "Discounts need approval."
    result = check(claim, "Government renewals only")
    assert result["status"] == "scope_supplied"
    assert result["facet"] == claim + "\n\nScope supplied by user: Government renewals only"
    assert result["answer"] == "Government renewals only"


def test_body_mention_outside_rule_section_does_not_generate_question():
    sources, evidence = corpus()
    evidence[1].heading = "References"
    assert scope_context("Discounts require approval", None, sources, evidence)["status"] == "not_requested"


@pytest.mark.parametrize(
    "claim",
    [
        "Alex approved a 32% discount on Teams.",
        "The 41% discount was authorised by Sam Patel before signing.",
    ],
)
def test_recognised_transaction_does_not_request_unnecessary_policy_scope(claim):
    assert check(claim)["status"] == "not_requested"
    result = check(claim, "New-business deals")
    assert result["status"] == "scope_supplied"
    assert result["facet"] == claim + "\n\nScope supplied by user: New-business deals"
