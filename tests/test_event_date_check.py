"""Unit tests for the deterministic event-date admission check (first cut).

Pure-function tests (no LLM): they pin the firing conditions for ``event_date_exclusion`` — the
helper the trimmed reader uses to demote a ``supports`` finding to context when a structured
record's date contradicts the claim's asserted date.
"""

import json

from decidr.event_date_check import event_date_exclusion

# A trimmed real-shape CRM row: the deal actually closed 2025-07-05; 2025-07-02 was the Slack
# approval date (hidden inside a non-date-valued field, so it must NOT be picked up as a date).
_CRM_RECORD = {
    "deal_id": "DEAL-014",
    "close_date": "2025-07-05",
    "first_activity_date": "2025-06-10",
    "approval_role": "Diane Okafor (Slack, 2025-07-02)",
    "stage_history": "Discovery:2025-06-10;Closed Won:2025-07-05",
}


def _crm_passage(record: dict | None = None) -> dict:
    return {"text": json.dumps(record or _CRM_RECORD), "source_type": "structured_operational_record"}


def _component(text: str, predicate: str = "closed") -> dict:
    return {"predicate": predicate, "temporal": "", "claim_quote": text, "text": text}


def test_wrong_close_date_is_flagged():
    # DEAL-014: claim says "closed on 2 July 2025"; record close_date is 2025-07-05 -> mismatch.
    reason = event_date_exclusion(
        _component("DEAL-014 closed on 2 July 2025 without any prior Finance approval."),
        _crm_passage(),
    )
    assert reason is not None
    assert "close_date" in reason
    assert "2025-07-05" in reason and "2025-07-02" in reason


def test_correct_close_date_is_not_flagged():
    reason = event_date_exclusion(
        _component("DEAL-014 closed on 5 July 2025."), _crm_passage()
    )
    assert reason is None


def test_prior_elsewhere_does_not_leak_into_the_operator():
    # "without any prior Finance approval" contains 'prior' but it is far from the date, so the
    # operator for '2 July 2025' must stay equality (on), not less-than.
    reason = event_date_exclusion(
        _component("DEAL-014 closed on 2 July 2025 without any prior Finance approval."),
        _crm_passage(),
    )
    # Equality fails (5 != 2) -> flagged. If 'prior' had leaked (treated as <), 5 < 2 is false too,
    # but the phrasing in the reason would be 'before'; assert it is the equality phrasing.
    assert reason is not None
    assert "on 2025-07-02" in reason


def test_before_operator_satisfied_is_not_flagged():
    reason = event_date_exclusion(
        _component("DEAL-014 closed before 10 July 2025."), _crm_passage()
    )
    assert reason is None  # 2025-07-05 < 2025-07-10 holds


def test_before_operator_violated_is_flagged():
    reason = event_date_exclusion(
        _component("DEAL-014 closed before 1 July 2025."), _crm_passage()
    )
    assert reason is not None  # 2025-07-05 is NOT before 2025-07-01
    assert "before 2025-07-01" in reason


def test_after_operator_violated_is_flagged():
    reason = event_date_exclusion(
        _component("DEAL-014 closed after 10 July 2025."), _crm_passage()
    )
    assert reason is not None  # 2025-07-05 is NOT after 2025-07-10


def test_by_operator_is_inclusive_upper_bound():
    # "by 5 July" means on or before -> 2025-07-05 satisfies it.
    assert event_date_exclusion(_component("DEAL-014 closed by 5 July 2025."), _crm_passage()) is None
    # but "by 1 July" is violated.
    assert event_date_exclusion(_component("DEAL-014 closed by 1 July 2025."), _crm_passage()) is not None


def test_iso_date_in_claim_is_parsed():
    reason = event_date_exclusion(
        _component("DEAL-014 closed on 2025-07-02."), _crm_passage()
    )
    assert reason is not None and "2025-07-05" in reason


def test_month_day_year_format_is_parsed():
    reason = event_date_exclusion(
        _component("DEAL-014 closed on July 2, 2025."), _crm_passage()
    )
    assert reason is not None and "2025-07-05" in reason


def test_prose_passage_is_never_flagged():
    prose = {"text": "Diane said over Slack to close DEAL-014 on 2 July 2025.", "source_type": "interview"}
    assert event_date_exclusion(_component("DEAL-014 closed on 2 July 2025."), prose) is None


def test_claim_without_a_date_is_not_flagged():
    assert event_date_exclusion(_component("DEAL-014 was closed without Finance approval."), _crm_passage()) is None


def test_two_distinct_claim_dates_bail_out():
    # Ambiguous which date to compare -> do nothing.
    reason = event_date_exclusion(
        _component("DEAL-014 opened on 1 June 2025 and closed on 2 July 2025."), _crm_passage()
    )
    assert reason is None


def test_same_date_twice_is_not_ambiguous():
    reason = event_date_exclusion(
        {
            "predicate": "closed",
            "temporal": "on 2 July 2025",
            "claim_quote": "closed on 2 July 2025",
            "text": "DEAL-014 closed on 2 July 2025",
        },
        _crm_passage(),
    )
    assert reason is not None  # one distinct date (2025-07-02) mentioned twice


def test_predicate_match_ignores_other_date_fields():
    # first_activity_date (2025-06-10) must not be chosen for a 'closed' predicate.
    reason = event_date_exclusion(_component("DEAL-014 closed on 2 July 2025."), _crm_passage())
    assert "first_activity_date" not in (reason or "")
    assert "close_date" in reason


def test_single_date_field_used_when_predicate_has_no_match():
    record = {"deal_id": "DEAL-099", "recorded_on": "2025-07-05"}
    reason = event_date_exclusion(
        _component("DEAL-099 happened on 2 July 2025.", predicate="happened"), _crm_passage(record)
    )
    assert reason is not None and "recorded_on" in reason


def test_ambiguous_record_fields_bail_out():
    record = {"deal_id": "DEAL-099", "opened_on": "2025-06-01", "shipped_on": "2025-07-05"}
    reason = event_date_exclusion(
        _component("DEAL-099 happened on 2 July 2025.", predicate="happened"), _crm_passage(record)
    )
    assert reason is None  # no predicate match AND >1 date field -> ambiguous


def test_approval_date_inside_text_field_is_not_mistaken_for_a_date():
    # approval_role carries '2025-07-02' inside free text; it must not be read as a date field.
    record = {"deal_id": "DEAL-014", "close_date": "2025-07-05", "approval_role": "Diane (2025-07-02)"}
    reason = event_date_exclusion(_component("DEAL-014 closed on 5 July 2025."), _crm_passage(record))
    assert reason is None  # close_date matches; the 07-02 in approval_role is ignored
