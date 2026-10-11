from datetime import date
import json

import pytest

from decidr.retrieval_models import Evidence, Source
from decidr.transaction_claims import assess_transaction_claim, parse_transaction_claim

CLAIM = "CASE-782 Jordan approved 37% discount before the contract was signed."


def record(**changes):
    return {
        "deal_id": "CASE-782",
        "discount_pct": "37",
        "approval_role": "Jordan Lee (exception)",
        "approval_record": "Recorded in approvals",
        "approval_status": "approved",
        "close_date": "2026-02-10",
        **changes,
    }


def assess(rows, claim=CLAIM, as_of=date(2026, 10, 11), scope_answer=None, **source_changes):
    source = Source(
        source_id="s",
        title="Ledger",
        original_file_path="rows.csv",
        source_type="crm_records",
        checksum="a" * 64,
        ingestion_status="ingested",
        **source_changes,
    )
    passages = [
        Evidence(
            evidence_id=f"e{i}",
            source_id="s",
            source_type="crm_records",
            locator=f"csv:row:{i}",
            row_identifier=row.get("deal_id", f"AUD-{i}"),
            text=json.dumps(row),
            extraction_method="csv",
        )
        for i, row in enumerate(rows)
    ]
    result = assess_transaction_claim(claim, passages, {"s": source}, as_of, scope_answer)
    for citation in result["citations"]:
        text = next(p.text for p in passages if p.evidence_id == citation["evidence_id"])
        assert text[citation["start"] : citation["end"]] == citation["quotation"]
    return result


def test_partial_claim_preserves_missing_signing_time():
    result = assess([record()])
    assert result["status"] == "partially_supported"
    assert [c["status"] for c in result["components"]] == ["supported", "supported", "unresolved"]


@pytest.mark.parametrize(
    "approved,signed,status",
    [
        ("2026-02-09", "2026-02-10", "supported_by_records"),
        ("2026-02-11", "2026-02-10", "contradicted_by_records"),
        ("2026-02-10", "2026-02-10", "partially_supported"),
        ("bad", "2026-02-10", "partially_supported"),
    ],
)
def test_explicit_event_order(approved, signed, status):
    assert (
        assess([record(approval_date=approved, contract_signed_date=signed)])["status"] == status
    )


def test_wrong_and_conflicting_discounts():
    assert assess([record(discount_pct="12")])["status"] == "contradicted_by_records"
    assert assess([record(), record(discount_pct="12")])["status"] == "conflicting_records"


def test_other_records_cannot_supply_dates_or_identity():
    result = assess(
        [
            record(),
            record(
                deal_id="CASE-783", approval_date="2026-01-01", contract_signed_date="2026-02-10"
            ),
        ]
    )
    assert result["status"] == "partially_supported"
    assert len(result["citations"]) == 1
    assert assess([record(deal_id="CASE-7821")])["status"] == "unresolved"


def test_ambiguous_first_name_does_not_verify_actor():
    result = assess([record(), record(deal_id="CASE-783", approval_role="Jordan Smith")])
    assert result["components"][1]["status"] == "unresolved"


def test_missing_or_pending_approval_is_not_verified():
    for changes in [
        {"approval_record": "", "approval_status": ""},
        {"approval_record": "No approval recorded", "approval_status": ""},
    ]:
        assert assess([record(**changes)])["components"][1]["status"] == "unresolved"


def test_future_and_conflicted_source_not_used_for_comparison():
    assert assess([record()], as_of=date(2026, 1, 1))["status"] == "unresolved"
    assert assess([record()], creation_date=date(2027, 1, 1))["status"] == "unresolved"
    assert assess([record()], metadata_conflicts=[{"field": "version"}])["status"] == "unresolved"


def test_explicit_related_record_can_supply_event_evidence():
    event = record(approval_date="2026-02-09", contract_signed_date="2026-02-10")
    event["related_record"] = event.pop("deal_id")
    assert assess([record(), event])["components"][2]["status"] == "supported"


def test_supported_word_orders_and_unsupported_extra_assertions():
    assert parse_transaction_claim(
        "Jordan approved a 37 percent discount for CASE-782 before the contract was signed"
    )
    assert parse_transaction_claim("For CASE-782, Jordan Lee approved 37% discount")
    for text in [
        CLAIM + " Also the customer paid.",
        CLAIM.replace("37%", "137%"),
        CLAIM.replace("approved", "did not approve"),
    ]:
        assert parse_transaction_claim(text) is None


def test_conclusion_answers_only_the_submitted_claim():
    from decidr.transaction_claims import transaction_conclusion

    simple = assess([record()], claim=CLAIM.replace(" before the contract was signed", ""))
    conclusion = transaction_conclusion(simple)
    assert conclusion["status"] == "supported_by_records"
    assert conclusion["label"] == "Supported by the available record"
    assert "signing" not in conclusion["summary"]
    assert "not independently verified" in conclusion["notice"]
    partial = transaction_conclusion(assess([record()]))
    assert partial["status"] == "partially_supported"
    assert "Not established: Approval before contract signing" in partial["summary"]


@pytest.mark.parametrize(
    "changes,expected",
    [
        (
            {"approval_status": "not approved", "approval_record": "Recorded in approvals"},
            "contradicted",
        ),
        ({"approval_status": "", "approval_record": "Awaiting sign-off"}, "unresolved"),
        ({"approval_status": "", "approval_record": "Recorded in approvals"}, "unresolved"),
        ({"approval_status": "pending", "approval_record": "Requested via Slack"}, "unresolved"),
        (
            {"approval_status": "not approved", "approval_record": "Approved via Slack"},
            "conflicting",
        ),
        ({"approval_status": "approved", "approval_record": "Awaiting sign-off"}, "conflicting"),
        ({"approval_status": "", "approval_record": "If approved via Slack"}, "unresolved"),
        (
            {
                "approval_status": "",
                "approval_record": "Recorded outside CRM (Slack)",
                "notes": "Same-day exception approved by Jordan — urgent.",
            },
            "supported",
        ),
    ],
)
def test_completed_approval_requires_explicit_affirmation(changes, expected):
    result = assess(
        [record(**changes)], claim=CLAIM.replace(" before the contract was signed", "")
    )
    assert result["components"][1]["status"] == expected
    if expected != "supported":
        assert result["status"] != "supported_by_records"


@pytest.mark.parametrize(
    "claim",
    [
        "Jordan approved a 37% discount for CASE-782 before the contract was signed.",
        "For CASE-782, the 37% discount was approved by Jordan before signing.",
        "Jordan authorised a 37% discount for CASE-782 before the contract was signed.",
        "The 37 percent discount was authorized by Jordan for CASE-782 before signing.",
    ],
)
def test_active_passive_and_authorisation_wordings_agree(claim):
    result = assess([record()], claim=claim)
    assert result["claim_fields"] == parse_transaction_claim(CLAIM)
    assert [c["status"] for c in result["components"]] == ["supported", "supported", "unresolved"]


def test_negative_and_positive_records_conflict_instead_of_voting():
    result = assess([record(), record(approval_status="not approved")])
    assert result["components"][1]["status"] == "conflicting"
    assert result["status"] == "conflicting_records"


@pytest.mark.parametrize("reference", ["Approved in principle", "Approved by Someone Else"])
def test_qualified_or_different_person_reference_does_not_verify_approval(reference):
    result = assess([record(approval_status="", approval_record=reference)])
    assert result["components"][1]["status"] != "supported"


def test_no_identifier_resolves_unique_actor_amount_and_reported_channel():
    result = assess(
        [
            record(approval_record="Recorded outside CRM (Teams)"),
            record(deal_id="CASE-900", discount_pct="12"),
        ],
        claim="Jordan authorised a 37% discount on Teams",
    )
    assert result["record_id"] == "CASE-782"
    assert result["record_resolution"] == "unique_actor_amount_match"
    assert result["status"] == "supported_by_records"
    assert result["components"][-1]["field"] == "channel"
    assert (
        "original message has not been verified"
        in result["components"][-1]["observations"][0]["reason"]
    )
    assert len(result["citations"]) == 1


def test_no_identifier_does_not_choose_between_matching_transactions():
    result = assess(
        [record(), record(deal_id="CASE-999")], claim="Jordan approved 37% discount on Teams"
    )
    assert result["status"] == "unresolved"
    assert result["candidate_record_ids"] == ["CASE-782", "CASE-999"]
    assert len(result["citations"]) == 2
    assert all(
        link["relationship"] == "candidate_transaction_not_selected"
        for link in result["connections"]
    )
    assert all(not component["observations"] for component in result["components"])


@pytest.mark.parametrize(
    "changes",
    [
        {"approval_record": "Awaiting sign-off on Teams", "approval_status": ""},
        {"approval_record": "Not approved via Teams", "approval_status": "not approved"},
        {"approval_record": "Approved via email"},
    ],
)
def test_channel_mentions_do_not_establish_channel_approval(changes):
    result = assess([record(**changes)], claim="Jordan approved 37% discount on Teams")
    assert result["status"] != "supported_by_records"
    assert result["components"][-1]["status"] == "unresolved"


def test_no_identifier_excludes_future_candidate():
    result = assess(
        [record(close_date="2027-01-01")], claim="Jordan approved 37% discount on Teams"
    )
    assert result["status"] == "unresolved"
    assert result["candidate_record_ids"] == []


@pytest.mark.parametrize(
    "notes,expected",
    [
        ("Jordan approved this one over Teams — never logged in the CRM.", "approved"),
        (
            "Jordan approved this one over Teams — never went through the formal CRM approval field.",
            "approved",
        ),
        ("Approved by Jordan. No CRM entry exists.", "approved"),
        ("Jordan did not approve this discount.", "denied"),
        ("Not approved by Jordan.", "denied"),
        ("Jordan would approve this discount if requested.", "unresolved"),
        ("Jordan approved this discount subject to Finance approval.", "unresolved"),
        ("Jordan approved this discount. Jordan did not approve this discount.", "conflicting"),
        ("Morgan did not approve this discount.", "unresolved"),
        ("Approval pending. Jordan approved this discount.", "conflicting"),
    ],
)
def test_approval_polarity_belongs_to_approval_clause(notes, expected):
    from decidr.transaction_claims import approval_state

    assert (
        approval_state(record(approval_status="", approval_record="", notes=notes))[0] == expected
    )


@pytest.mark.parametrize(
    "claim",
    [
        "For CASE-782, Jordan approved a 37% discount via Teams before signing.",
        "Jordan approved 37 percent discount via Teams for CASE-782 before the contract was signed.",
        "The 37% discount for CASE-782 was authorised by Jordan on Teams before signing.",
        "The 37% discount was authorized by Jordan for CASE-782 via Teams before signing.",
    ],
)
def test_modifier_positions_preserve_all_assertions(claim):
    result = assess([record(approval_record="Approved via Teams")], claim=claim)
    assert result["record_id"] == "CASE-782"
    assert result["claim_fields"]["channel"] == "Teams"
    assert result["status"] == "partially_supported"
    assert {c["field"]: c["status"] for c in result["components"]} == {
        "discount": "supported",
        "approval": "supported",
        "timing": "unresolved",
        "channel": "supported",
    }


@pytest.mark.parametrize(
    "claim",
    [
        "Jordan approved 37% discount in principle",
        "Jordan approved 37% discount on Teams and the customer paid",
        "CASE-782 Jordan approved 37% discount for CASE-783",
        "Jordan approved 37% discount after signing",
        "Jordan approved 37% discount on Teams via email",
    ],
)
def test_unsupported_assertions_cannot_be_discarded(claim):
    assert parse_transaction_claim(claim) is None


@pytest.mark.parametrize(
    "identifier,person,percentage",
    [
        ("ORDER-503", "Taylor Reed", "7.5"),
        ("SALE-902", "Ravi Das", "42"),
        ("X-17", "María Costa", "81.25"),
    ],
)
def test_entity_and_number_substitution_changes_comparison(identifier, person, percentage):
    claim = f"The {percentage}% discount for {identifier} was authorised by {person} on email."
    data = record(
        deal_id=identifier,
        approval_role=person,
        discount_pct=percentage,
        approval_record="Approved via email",
    )
    assert assess([data], claim=claim)["status"] == "supported_by_records"
    assert (
        assess([{**data, "discount_pct": "99"}], claim=claim)["status"]
        == "contradicted_by_records"
    )
    assert (
        assess([{**data, "approval_status": "pending", "approval_record": ""}], claim=claim)[
            "status"
        ]
        == "partially_supported"
    )


def test_explicit_record_connection_can_join_separate_approval_and_signing_dates():
    result = assess(
        [
            record(approval_date="2026-02-01"),
            {"related_record": "CASE-782", "contract_signed_date": "2026-02-03"},
        ]
    )
    assert result["status"] == "supported_by_records"
    assert {o["evidence_id"] for o in result["components"][2]["observations"]} == {"e0", "e1"}
    assert len(result["citations"]) == 2


def test_multiple_linked_signing_dates_are_not_resolved_by_choosing_convenient_date():
    result = assess(
        [
            record(approval_date="2026-02-02"),
            {"related_record": "CASE-782", "contract_signed_date": "2026-02-01"},
            {"related_record": "CASE-782", "contract_signed_date": "2026-02-03"},
        ]
    )
    assert result["status"] == "partially_supported"
    assert result["components"][2]["status"] == "unresolved"
    assert "Multiple" in result["components"][2]["observations"][0]["reason"]


@pytest.mark.parametrize(
    "field,value,selected,expected",
    [
        ("deal_type", "new_business", "New-business deals", "supported"),
        ("deal_scope", "new business deal", "New-business deals", "supported"),
        ("deal_type", "Renewals", "Renewal deals", "supported"),
        ("deal_scope", "renewal", "New-business deals", "contradicted"),
        ("deal_type", "new-business", "Renewal deals", "contradicted"),
        ("deal_type", "possibly new business", "New-business deals", "unresolved"),
    ],
)
def test_selected_scope_compares_only_explicit_linked_deal_fields(field, value, selected, expected):
    result = assess(
        [record(**{field: value})],
        claim=CLAIM.replace(" before the contract was signed", ""),
        scope_answer=selected,
    )
    component = next(c for c in result["components"] if c["field"] == "scope")
    assert component["status"] == expected
    assert component["observations"][0]["evidence_id"] == "e0"
    assert field in component["observations"][0]["reason"]
    if expected == "supported":
        assert result["status"] == "supported_by_records"


def test_missing_deal_scope_has_specific_reason_and_does_not_infer_from_business_context():
    result = assess(
        [record(customer_segment="New Business", stage="Closed Won", notes="New-business policy applies.")],
        scope_answer="New-business deals",
    )
    scope = next(c for c in result["components"] if c["field"] == "scope")
    assert scope["status"] == "unresolved"
    assert "does not explicitly identify its deal type" in scope["observations"][0]["reason"]
    assert "New-business deals" in result["next_step"]
    assert "signed contract" in result["next_step"]


def test_scope_comes_from_same_linked_transaction_and_conflicting_fields_remain_visible():
    claim = CLAIM.replace(" before the contract was signed", "")
    supported = assess(
        [record(), {"related_record": "CASE-782", "deal_type": "new-business"}],
        claim=claim,
        scope_answer="New-business deals",
    )
    assert supported["status"] == "supported_by_records"
    assert supported["components"][-1]["observations"][0]["evidence_id"] == "e1"
    unrelated = assess(
        [record(), {"related_record": "CASE-783", "deal_type": "new-business"}],
        claim=claim,
        scope_answer="New-business deals",
    )
    assert unrelated["components"][-1]["status"] == "unresolved"
    conflicting = assess(
        [record(deal_type="new-business", deal_scope="renewal")],
        claim=claim,
        scope_answer="New-business deals",
    )
    assert conflicting["components"][-1]["status"] == "conflicting"
    assert conflicting["status"] == "conflicting_records"


def test_scope_unknown_conflicting_or_future_records_cannot_silently_verify_scope():
    rows = [record(deal_type="new-business"), record(deal_type="conditional renewal")]
    assert assess(rows, scope_answer="New-business deals")["components"][-1]["status"] == "unresolved"
    rows = [record(), record(deal_type="new-business", close_date="2027-01-01")]
    assert assess(rows, scope_answer="New-business deals")["components"][-1]["status"] == "unresolved"
    result = assess([record(deal_type="new-business")], scope_answer="Not new-business deals")
    assert result["components"][-1]["status"] == "unresolved"


def test_all_deal_types_does_not_assert_a_transaction_type():
    result = assess([record()], scope_answer="All deal types")
    assert not any(c["field"] == "scope" for c in result["components"])
