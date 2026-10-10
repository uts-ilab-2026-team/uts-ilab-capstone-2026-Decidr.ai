"""Bounded proposal comparisons; no inference of authority or quality."""

from datetime import date

import pytest

from decidr.interpretation_engine import infer_target, propose_interpretation
from decidr.interpretation_models import EvidenceInterpretation, validate_interpretation
from decidr.retrieval_models import Evidence, Source


def propose(facet, text, *, claim=None, target="formal_rule", as_of=date(2026, 6, 17), **changes):
    values = {
        "source_id": "s",
        "title": "Test",
        "original_file_path": "test.md",
        "source_type": "policy",
        "checksum": "a" * 64,
        "ingestion_status": "ingested",
        "lifecycle_status": "current",
        "approval_status": "Approved",
        "effective_start_date": date(2025, 1, 1),
    }
    values.update(changes)
    source = Source(**values)
    evidence = Evidence(
        evidence_id="e",
        source_id="s",
        locator="p:1",
        text=text,
        source_type=source.source_type,
        extraction_method="test",
    )
    result = propose_interpretation(
        claim_text=claim or facet,
        facet=facet,
        assessment_target=target,
        as_of=as_of,
        evidence=evidence,
        source=source,
    )
    validate_interpretation(
        EvidenceInterpretation(
            claim_text=claim or facet,
            facet=facet,
            stance=result.stance,
            mode=result.mode,
            rationale=result.rationale,
            citations=(result.citation,),
        ),
        [evidence],
        claim_text=claim or facet,
    )
    return result


@pytest.mark.parametrize(
    "claim,text",
    [
        ("Finance must approve Sales requests.", "Sales must approve Finance requests."),
        (
            "Finance approval is required before closing.",
            "Finance approval is required after closing.",
        ),
        ("All requests require approval.", "Some requests require approval."),
        (
            "Discounts of at least 20% require approval.",
            "Discounts of at least 15% require approval.",
        ),
        ("Discounts above 15% require approval.", "Discounts of 15% or greater require approval."),
        ("Discounts of 15% require approval.", "Discounts of 20% require approval."),
        ("Approval is never required.", "Approval is required."),
        ("Approval is not unnecessary.", "Approval is required."),
        ("Finance approval is required.", "Written Finance approval must be obtained."),
    ],
)
def test_unrecognised_comparisons_abstain(claim, text):
    result = propose(claim, text)
    assert result.stance == "unresolved"
    assert result.proposal_confidence == "low"


def test_facet_not_whole_claim_is_compared():
    result = propose(
        "Finance approval is not required.",
        "Finance approval is required.",
        claim="Finance approval is required.",
    )
    assert result.stance == "contradict"


@pytest.mark.parametrize(
    "claim,text",
    [
        (
            "DEAL-014 production deployment requires approval.",
            "DEAL-014 staging deployment requires approval.",
        ),
        (
            "DEAL-014 new-business discounts require approval.",
            "DEAL-014 renewal discounts require approval.",
        ),
        ("DEAL-014 and DEAL-015 require approval.", "DEAL-014 and DEAL-016 require approval."),
    ],
)
def test_identifiers_do_not_override_scope(claim, text):
    result = propose(claim, text)
    assert result.scope_matches is False
    assert result.stance == "context"


@pytest.mark.parametrize(
    "claim,text",
    [
        ("Written approval is required.", "Written approval is required."),
        ("Approval is not required.", "Approval is not required."),
        (
            "Discounts of 15% or more require approval.",
            "Discounts of 15% or greater require approval.",
        ),
        (
            "Discounts of at least 15.5% require approval.",
            "1. Discounts of **15.5% or greater** require approval.",
        ),
    ],
)
def test_bounded_equivalence_preserves_citation(claim, text):
    result = propose(claim, text)
    assert result.stance == "support"
    assert result.authority_verified is None
    assert result.independence_verified is False
    assert (result.directness, result.specificity, result.completeness) == (0, 0, 0)
    assert result.review_payload()["quality_status"] == "not_assessed"


@pytest.mark.parametrize(
    "claim,text",
    [
        ("Approval is required.", "Approval is not required."),
        ("Approval is not required.", "Approval is required."),
    ],
)
def test_complete_explicit_negation(claim, text):
    assert propose(claim, text).stance == "contradict"


def test_internal_conflict_keeps_whole_passage():
    text = "Approval is required. Approval is not required."
    result = propose("Approval is required.", text)
    assert result.stance == "unresolved"
    assert result.citation.quotation == text


def test_missingness_is_not_event_contradiction():
    result = propose(
        "The deployment received approval.",
        "No approval record was found.",
        target="underlying_event",
        source_type="audit_events",
    )
    assert result.stance == "unresolved"


@pytest.mark.parametrize("source_type", ["interview", "internal_communication", "meeting"])
def test_reported_rules_are_not_formal_authority(source_type):
    result = propose("Approval is required.", "Approval is required.", source_type=source_type)
    assert result.mode == "observed"
    assert result.evidence_target == "recorded_statement"
    assert result.stance == "context"
    assert result.authority_verified is None


def test_explicit_report_takes_precedence_over_normative_words():
    text = "Diane reported that Finance approval is required."
    assert infer_target(text) == "recorded_statement"
    result = propose(text, text, target="recorded_statement", source_type="interview")
    assert result.stance == "support"
    assert result.temporal_matches is None


@pytest.mark.parametrize(
    "as_of,expected",
    [
        (date(2020, 1, 1), False),
        (date(2021, 6, 1), True),
        (date(2025, 2, 27), True),
        (date(2025, 2, 28), None),
        (date(2025, 3, 1), False),
    ],
)
def test_historical_approval_remains_separate_from_lifecycle(as_of, expected):
    result = propose(
        "Approval is required.",
        "Approval is required.",
        as_of=as_of,
        lifecycle_status="superseded",
        effective_start_date=date(2021, 6, 1),
        superseded_date=date(2025, 2, 28),
        approval_status="Approved (historical — no longer in force)",
    )
    assert result.approval_key == "approved"
    assert result.temporal_matches is expected
    assert result.authority_verified is None


def test_not_approved_is_not_positive_approval():
    result = propose(
        "Approval is required.", "Approval is required.", approval_status="Not approved"
    )
    assert result.approval_key == "unapproved"


def test_arbitrary_record_dates_do_not_verify_event_time():
    text = "On 2025-06-01, the request was completed."
    result = propose(text, text, target="underlying_event", source_type="audit_events")
    assert result.temporal_matches is None


def test_invalid_dates_remain_reviewable():
    text = "On 2025-99-99, the request was completed."
    result = propose(text, text, target="underlying_event")
    assert result.temporal_matches is None


def test_long_unicode_citation_is_not_truncated():
    text = "Approval of " + "évidence " * 100 + "is required."
    result = propose(text, text)
    assert result.citation.quotation == text
    assert result.citation.end == len(text)


def test_metadata_conflicts_prevent_resolved_approval_and_time():
    result = propose(
        "Approval is required.",
        "Approval is required.",
        metadata_conflicts=[{"field": "approval_status", "reason": "conflict"}],
    )
    assert result.approval_key == "unknown"
    assert result.temporal_matches is None
