"""Operational comparisons must not turn missing fields into violations."""

from datetime import date
import json

import pytest

from decidr.practice_assessment import assess_practice
from decidr.retrieval_models import Evidence, Source

RULE = "Expense claims over €725 require approval from Regional Finance before reimbursement is processed."


def evaluate(row, rule=RULE, as_of=date(2026, 10, 11), **source_fields):
    source = Source(
        source_id="custom-ledger",
        title="Expense ledger",
        original_file_path="ledger.csv",
        source_type="project_tasks",
        checksum="a" * 64,
        ingestion_status="ingested",
        **source_fields,
    )
    text = json.dumps(row)
    passage = Evidence(
        evidence_id="row-xyz",
        source_id=source.source_id,
        locator="csv:row:2",
        text=text,
        source_type="project_tasks",
        extraction_method="csv",
    )
    result = assess_practice(rule, [passage], {source.source_id: source}, as_of)
    for finding in result["findings"]:
        c = finding["citation"]
        assert text[c["start"] : c["end"]] == c["quotation"]
    return result


def row(**changes):
    return {
        "task_id": "RANDOM-772",
        "process_or_capability": "Expense Approval",
        "expense_amount": "800",
        "currency": "€",
        "payment_status": "reimbursed",
        "reimbursement_date": "2026-06-10",
        "approval_date": "2026-06-09",
        "approval_role": "Regional Finance",
        "approval_status": "approved",
        **changes,
    }


def test_compliant_record_is_one_event_not_universal_proof():
    finding = evaluate(row())["findings"][0]
    assert finding["status"] == "recorded_consistent_event"
    assert "One event" in finding["reason"]


def test_late_approval_is_recorded_departure():
    assert (
        evaluate(row(approval_date="2026-06-11"))["findings"][0]["status"] == "recorded_departure"
    )


@pytest.mark.parametrize("amount", ["100", "725"])
def test_amount_outside_claim_range_is_not_counterexample(amount):
    assert not evaluate(row(expense_amount=amount, approval_date="2026-06-11"))["findings"]


@pytest.mark.parametrize(
    "changes",
    [
        {"approval_date": "2026-06-10"},
        {"approval_date": ""},
        {"approval_role": "Someone else"},
        {"reimbursement_date": ""},
        {"reimbursement_date": "invalid"},
        {"payment_status": "pending"},
    ],
)
def test_missing_or_ambiguous_facts_do_not_establish_compliance(changes):
    assert evaluate(row(**changes))["findings"][0]["status"] not in {
        "recorded_departure",
        "recorded_consistent_event",
    }


def test_missing_approval_record_is_not_a_violation():
    assert (
        evaluate(row(approval_date="", approval_role=""))["findings"][0]["status"]
        == "missing_approval_record"
    )


def test_future_events_and_source_creation_are_not_used():
    assert not evaluate(row(), as_of=date(2026, 6, 1))["findings"]
    assert not evaluate(row(), creation_date=date(2027, 1, 1))["findings"]


def test_explicit_bypass_report_retains_uncertain_timing():
    data = {
        "task_id": "unseen",
        "process_or_capability": "Expense Approval",
        "comments": "€830 conference costs — Alex signed off directly rather than routing to Finance.",
        "completion_date": "2026-06-01",
    }
    finding = evaluate(data)["findings"][0]
    assert finding["status"] == "reported_alternative_route"
    assert finding["event_date"] is None
    assert not evaluate(data, rule=RULE.replace("725", "900"))["findings"]
    assert (
        evaluate({**data, "comments": "We will spend €830 rather than routing to Finance."})[
            "findings"
        ][0]["status"]
        != "reported_alternative_route"
    )


def test_wrong_currency_and_multiple_amounts_do_not_infer_scope():
    assert not evaluate(row(currency="$"))["findings"]
    assert not evaluate(
        {"process_or_capability": "Expense Approval", "comments": "€800 plus €900"}
    )["findings"]


def test_discount_scope_basis_and_written_approval_are_not_assumed():
    rule = "Any discount of at least 23% off list price on a new-business deal requires written approval from Commercial Finance before the deal is marked Closed Won."
    source = Source(
        source_id="crm-unseen",
        title="CRM",
        original_file_path="crm.csv",
        source_type="crm_records",
        checksum="b" * 64,
        ingestion_status="ingested",
    )
    record = {
        "deal_id": "Z-991",
        "discount_pct": "29",
        "deal_scope": "new-business",
        "discount_basis": "list_price",
        "stage": "Closed Won",
        "close_date": "2026-02-03",
        "approval_date": "2026-02-01",
        "approval_role": "Commercial Finance",
        "approval_status": "approved",
        "written_approval": True,
    }

    def assess(changes):
        text = json.dumps({**record, **changes})
        passage = Evidence(
            evidence_id="crm-row",
            source_id=source.source_id,
            locator="csv:row:3",
            text=text,
            source_type="crm_records",
            extraction_method="csv",
        )
        return assess_practice(rule, [passage], {source.source_id: source}, date(2026, 10, 11))[
            "findings"
        ]

    assert assess({})[0]["status"] == "recorded_consistent_event"
    assert assess({"approval_date": "2026-02-04"})[0]["status"] == "recorded_departure"
    for changes in [
        {"deal_scope": ""},
        {"discount_basis": ""},
        {"written_approval": False},
        {"approval_role": "Sales"},
    ]:
        assert assess(changes)[0]["status"] == "unresolved_record"
    assert not assess({"deal_scope": "renewal"})
    assert not assess({"discount_pct": "22"})


def test_conflicting_record_fields_do_not_establish_event_outcome():
    for changes in [
        {"comments": "€200 travel costs"},
        {"approval_status": "rejected"},
    ]:
        finding = evaluate(row(**changes))["findings"][0]
        assert finding["status"] == "unresolved_record"
        assert any("review is required" in reason for reason in finding["limitations"])


@pytest.mark.parametrize("status", ["", "pending", "awaiting sign-off", "not approved", "revoked"])
def test_approval_date_alone_never_proves_compliance(status):
    finding = evaluate(row(approval_status=status))["findings"][0]
    assert finding["status"] not in {"recorded_consistent_event", "recorded_departure"}


def test_future_approval_is_excluded_even_when_reimbursement_has_occurred():
    assert not evaluate(row(approval_date="2026-07-01"), as_of=date(2026, 6, 20))["findings"]


def test_documentation_negation_does_not_erase_explicit_approval():
    finding = evaluate(row(comments="No CRM entry exists."))["findings"][0]
    assert finding["status"] == "recorded_consistent_event"
