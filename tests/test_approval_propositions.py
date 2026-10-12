"""Field-preserving approval paraphrases and near misses."""

from datetime import date

import pytest

from decidr.approval_propositions import compare_approval_rules, parse_approval_rule
from decidr.interpretation_engine import propose_interpretation
from decidr.interpretation_models import EvidenceInterpretation, validate_interpretation
from decidr.retrieval_models import Evidence, Source


def forms(
    approver="the Review Director", scope="export", amount="12.5", event="Accepted in the register"
):
    source = (
        f"Any discount of {amount}% or greater off list price on a {scope} deal "
        f"requires written approval from {approver} before the deal is marked {event}."
    )
    claim = (
        f"{approver} must provide written approval before every {scope} deal with a "
        f"discount of at least {amount}% off list price is marked {event}."
    )
    return claim, source


@pytest.mark.parametrize(
    "approver,scope,amount,event",
    [
        ("the Review Director", "export", "12.5", "Accepted in the register"),
        ("the Head of Finance & People Ops", "new-business", "15", "Closed Won in the CRM"),
        ("Asha Rao", "partner", "27.25", "Final in the system"),
        ("the Contract Board", "renewal", "0", "Signed"),
        ("the Operations Lead", "regional", "100", "Complete"),
    ],
)
def test_equivalence_is_not_tied_to_corpus_values(approver, scope, amount, event):
    claim, source = forms(approver, scope, amount, event)
    result = compare_approval_rules(claim, source)
    assert result is not None and result["equivalent"]
    assert result["differences"] == []


@pytest.mark.parametrize(
    "old,new,field",
    [
        ("the Review Director", "the Sales Director", "approver"),
        ("export", "renewal", "deal_scope"),
        ("at least 12.5%", "above 12.5%", "boundary"),
        ("12.5%", "20%", "percentage"),
        ("written approval", "approval", "written"),
        ("before", "after", "timing"),
        ("Accepted in the register", "Accepted in the portal", "event"),
    ],
)
def test_changed_fields_are_explicit_not_contradiction(old, new, field):
    claim, source = forms()
    result = compare_approval_rules(claim.replace(old, new), source)
    assert result is not None and not result["equivalent"]
    assert result["differences"] == [field]


@pytest.mark.parametrize(
    "change",
    [
        lambda s: s.replace("every", "some"),
        lambda s: s.replace("must provide", "may provide"),
        lambda s: s.replace("must provide", "must not provide"),
        lambda s: s + " Unless the deal is urgent.",
        lambda s: s[:-1] + " if requested.",
        lambda s: "Diane said " + s,
        lambda s: s.replace(" off list price", ""),
        lambda s: s.replace(" off list price", " off invoice value"),
        lambda s: s.replace("before every", "before some"),
        lambda s: s.replace("12.5%", "112.5%"),
        lambda s: s.replace("12.5%", "-12.5%"),
        lambda s: s.replace("12.5%", "12.5% or less"),
    ],
)
def test_unsupported_or_incomplete_grammar_abstains(change):
    claim, _ = forms()
    assert parse_approval_rule(change(claim)) is None


def test_decimal_spelling_does_not_change_boundary():
    claim, source = forms(amount="12.50")
    assert compare_approval_rules(claim.replace("12.50", "12.5"), source)["equivalent"]


def test_engine_integration_preserves_exact_citation_and_unassessed_gates():
    claim, text = forms()
    source = Source(
        source_id="novel-source",
        title="Novel policy",
        original_file_path="test.md",
        source_type="policy",
        checksum="a" * 64,
        ingestion_status="ingested",
        lifecycle_status="current",
        approval_status="Approved",
        effective_start_date=date(2025, 1, 1),
    )
    passage = Evidence(
        evidence_id="novel-evidence",
        source_id=source.source_id,
        locator="section:1",
        text="1. " + text,
        source_type="policy",
        extraction_method="test",
    )
    result = propose_interpretation(
        claim_text=claim,
        facet=claim,
        assessment_target="formal_rule",
        as_of=date(2026, 6, 17),
        evidence=passage,
        source=source,
    )
    assert result.stance == "support"
    assert result.comparison_method == "approval_fields_v2"
    assert result.review_payload()["field_comparison"]["equivalent"]
    assert result.authority_verified is None
    assert (result.directness, result.specificity, result.completeness) == (0, 0, 0)
    validate_interpretation(
        EvidenceInterpretation(
            claim_text=claim,
            facet=claim,
            stance=result.stance,
            mode=result.mode,
            rationale=result.rationale,
            citations=(result.citation,),
        ),
        [passage],
        claim_text=claim,
    )


def test_engine_reports_changed_approver_as_unresolved():
    claim, text = forms()
    source = Source(
        source_id="s",
        title="Policy",
        original_file_path="p.md",
        source_type="policy",
        checksum="a" * 64,
        lifecycle_status="current",
        effective_start_date=date(2025, 1, 1),
    )
    passage = Evidence(
        evidence_id="e",
        source_id="s",
        locator="p:1",
        text=text,
        source_type="policy",
        extraction_method="test",
    )
    result = propose_interpretation(
        claim_text=claim,
        facet=claim.replace("Review Director", "Sales Director"),
        assessment_target="formal_rule",
        as_of=date(2026, 6, 17),
        evidence=passage,
        source=source,
    )
    assert result.stance == "unresolved"
    assert result.field_comparison["differences"] == ["approver"]


@pytest.mark.parametrize(
    "claim",
    [
        "Discounts of at least 15% off list price on new-business deals require written approval from Finance before deals are marked won.",
        "For new-business deals, discounts of 15% or greater off list price require written approval from Finance before the deal is marked won.",
    ],
)
def test_complete_natural_word_order_variants(claim):
    rule = "Any discount of 15% or greater off list price on a new-business deal requires written approval from Finance before the deal is marked won."
    assert compare_approval_rules(claim, rule)["evidence_entails_claim"]
    assert not compare_approval_rules(claim.replace("Finance", "Sales"), rule)[
        "evidence_entails_claim"
    ]
    assert not compare_approval_rules(
        claim.replace("at least 15%", "above 15%").replace("15% or greater", "above 15%"),
        rule.replace("15% or greater", "below 15%"),
    )["evidence_entails_claim"]
