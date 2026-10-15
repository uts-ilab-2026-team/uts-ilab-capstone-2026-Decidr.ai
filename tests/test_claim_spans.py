"""Typography repair preserves exact source text and rejects uncertain bindings."""

import pytest

from decidr.claims.spans import exact_claim_span, exact_evidence_span


@pytest.mark.parametrize(
    "text",
    [
        "~~~text\nStored literal: **confirmed**.\n~~~",
        "    Stored literal: **confirmed**.",
        "\tStored literal: **confirmed**.",
        "<pre>Stored literal: **confirmed**.</pre>",
        "<code>Stored literal: **confirmed**.</code>",
    ],
)
def test_evidence_markdown_code_blocks_and_html_remain_literal(text):
    assert exact_evidence_span(text, "Stored literal: confirmed.") is None
    assert (
        exact_evidence_span(text, "Stored literal: **confirmed**.")
        == "Stored literal: **confirmed**."
    )


@pytest.mark.parametrize(
    "claim,quote,expected",
    [
        ("The customer’s discount was approved.", "customer's discount", "customer’s discount"),
        ("The employee’s request was denied.", "employee's request", "employee’s request"),
        ("The customer‘s request was denied.", "customer's request", "customer‘s request"),
        ("The customer's request was denied.", "customer’s request", "customer's request"),
        ("The status is “approved”.", '"approved"', "“approved”"),
        ('The status is "approved".', "“approved”", '"approved"'),
        ("The status is ‘approved’.", "'approved'", "‘approved’"),
        ("At most\u00a037% is allowed.", "most 37%", "most\u00a037%"),
        ("At most 37% is allowed.", "most\u00a037%", "most 37%"),
        (
            "The employee’s ‘request’\u00a0was denied.",
            "employee's 'request' was",
            "employee’s ‘request’\u00a0was",
        ),
    ],
)
def test_unique_typography_match_returns_original_substring(claim, quote, expected):
    result = exact_claim_span(claim, quote)
    assert result == expected
    assert result in claim


def test_unicode_prefix_does_not_shift_original_span_offsets():
    prefix = "📋 Cafe\u0301 — 前言: "
    original = "the employee’s ‘request’\u00a0was denied"
    claim = prefix + original + ". Further context."
    result = exact_claim_span(claim, "the employee's 'request' was denied")
    assert result == claim[len(prefix) : len(prefix) + len(original)] == original


def test_repeated_exact_quote_keeps_existing_exact_match_behavior():
    assert (
        exact_claim_span("The customer’s request; the customer’s request.", "customer’s request")
        == "customer’s request"
    )


def test_exact_quote_takes_precedence_over_other_typographic_variants():
    claim = "The customer’s request; the customer's request."
    assert exact_claim_span(claim, "customer's request") == "customer's request"


@pytest.mark.parametrize(
    "claim,quote",
    [
        ("The customer’s request; the customer’s request.", "customer's request"),
        ("The customer’s request; the customer‘s request.", "customer's request"),
        ("“approved” then “approved”", '"approved"'),
        ("A\u00a0B and A\u00a0B", "A B"),
        ("‘’‘", "''"),
    ],
)
def test_ambiguous_normalized_matches_are_rejected_including_overlaps(claim, quote):
    assert exact_claim_span(claim, quote) is None


@pytest.mark.parametrize(
    "claim,quote",
    [
        ("The employee’s request.", ""),
        ("", "employee's request"),
        ("The employee’s request.", "Employee's request"),
        ("The employee’s request.", "employee's  request"),
        ("The employee’s  request.", "employee's request"),
        ("The employee’s\nrequest.", "employee's request"),
        ("The employee’s\trequest.", "employee's request"),
        ("The employee’s\u202frequest.", "employee's request"),
        ("The employee’s request.", " employee's request "),
        ("The employee’s request was not approved.", "employee's request was approved"),
        ("The employee’s request.", "customer's request"),
        ("The employee’s −37% adjustment.", "employee's -37% adjustment"),
        ("The employee’s 37% adjustment.", "employee's 38% adjustment"),
        ("The employee’s ３７% adjustment.", "employee's 37% adjustment"),
        ("The employee’s ½ share.", "employee's 1/2 share"),
        ("The employee’s request—approved.", "employee's request-approved"),
        ("The employee’s café request.", "employee's cafe\u0301 request"),
    ],
)
def test_changes_beyond_allowed_typography_are_rejected(claim, quote):
    assert exact_claim_span(claim, quote) is None


def test_evidence_bold_label_returns_original_markers_and_offsets():
    prefix = "📋 Cafe\u0301 — 前言:\n- "
    original = "**Decision rights:** Sole approver of probation completion."
    text = prefix + original + "\nOther context."
    quote = "Decision rights: Sole approver of probation completion."
    assert exact_evidence_span(text, quote) == original
    assert text.index(exact_evidence_span(text, quote)) == len(prefix)
    assert exact_claim_span(text, quote) is None


def test_evidence_bold_typography_restores_all_original_characters():
    text = "The **employee’s request**\u00a0was **not approved**."
    assert exact_evidence_span(text, "The employee's request was not approved.") == text


def test_evidence_bold_span_ending_at_content_boundary_keeps_closing_marker():
    text = "Status: **not approved**. More text."
    assert exact_evidence_span(text, "Status: not approved") == "Status: **not approved**"


def test_evidence_bold_partial_span_keeps_original_interior_marker():
    text = "**Decision rights:** Sole approver."
    assert exact_evidence_span(text, "rights: Sole approver") == "rights:** Sole approver"


def test_evidence_exact_match_takes_precedence_over_markdown_variants():
    text = "Status: approved. Status: **approved**. Status: approved."
    assert exact_evidence_span(text, "Status: approved") == "Status: approved"


def test_evidence_repeated_normalized_bold_matches_are_ambiguous():
    text = "Status: **approved**. Status: **approved**."
    assert exact_evidence_span(text, "Status: approved") is None


def test_evidence_can_bind_model_bold_to_original_plain_text():
    text = "Status: approved."
    assert exact_evidence_span(text, "Status: **approved**.") == text


@pytest.mark.parametrize(
    "text,quote",
    [
        ("Status: **not approved**.", ""),
        ("Status: **not approved**.", "Status: approved."),
        ("Status: **not approved**.", "status: not approved."),
        ("Status: **not approved**.", "Status: not  approved."),
        ("Status:\n**not approved**.", "Status: not approved."),
        ("Limit: **37%**.", "Limit: 38%."),
        ("Limit: **−37%**.", "Limit: -37%."),
        ("Limit: **３７%**.", "Limit: 37%."),
        ("Status: **not approved**.", "Status: denied."),
    ],
)
def test_evidence_markdown_repair_does_not_change_meaning_or_whitespace(text, quote):
    assert exact_evidence_span(text, quote) is None


@pytest.mark.parametrize(
    "text,quote",
    [
        ("Status: **approved.", "Status: approved."),
        ("Status: approved**.", "Status: approved."),
        ("Status: ** approved**.", "Status:  approved."),
        ("Status: **approved **.", "Status: approved ."),
        (r"Status: \**approved**.", r"Status: \approved."),
        (r"Status: **approved\**.", r"Status: approved\."),
        ("2**3**4", "234"),
        ("A**bold**Z", "AboldZ"),
        ("Status: ***approved***.", "Status: *approved*."),
        ("Status: **a *nested* label**.", "Status: a *nested* label."),
    ],
)
def test_evidence_unpaired_escaped_arithmetic_or_nested_markers_stay_literal(text, quote):
    assert exact_evidence_span(text, quote) is None


@pytest.mark.parametrize("ticks", ["`", "``", "```"])
def test_evidence_bold_markers_inside_backtick_code_stay_literal(ticks):
    text = f"Code: {ticks}Status: **approved**.{ticks}"
    assert exact_evidence_span(text, f"Code: {ticks}Status: approved.{ticks}") is None
    assert exact_evidence_span(text, "Status: approved.") is None


def test_evidence_unclosed_backtick_code_is_protected_conservatively():
    assert exact_evidence_span("`Status: **approved**.", "`Status: approved.") is None
