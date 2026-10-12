from datetime import date
import json

from decidr.evidence_synthesis import build_evidence_synthesis
from decidr.retrieval_models import Evidence, Source

CLAIM = "Discounts above 23% require approval from Regional Finance."


def corpus():
    sources = {}
    passages = []

    def add(key, kind, text, **kwargs):
        sources.setdefault(
            key,
            Source(
                source_id=key,
                title=key,
                original_file_path=key,
                source_type=kind,
                checksum="a" * 64,
                ingestion_status="ingested",
            ),
        )
        passage = Evidence(
            evidence_id=key + str(len(passages)),
            source_id=key,
            source_type=kind,
            text=text,
            locator="passage:" + str(len(passages)),
            extraction_method="test",
            **kwargs,
        )
        passages.append(passage)
        return passage

    add(
        "policy",
        "policy",
        "Any discount of 23% or greater off list price on a new-business deal requires written approval from Regional Finance before the deal is marked Closed Won.\nApproval must be recorded in the CRM.",
    )
    add(
        "interview",
        "interview",
        "On discount approval: Alex sometimes approves urgent ones herself and tells me after.",
    )
    add(
        "roles",
        "role_description",
        "Responsibilities: discount approvals.",
        heading="Regional Sales — Alex Chen",
    )
    add(
        "crm",
        "crm_records",
        json.dumps(
            {
                "deal_id": "SALE-809",
                "discount_pct": "31",
                "approval_role": "Alex Chen",
                "approval_record": "Recorded outside CRM (Slack)",
                "close_date": "2026-01-04",
            }
        ),
        row_identifier="SALE-809",
    )
    add("messages", "internal_communication", "SALE-809: Approval discussion retained for review.")
    add("onboarding", "procedure", "New hire onboarding needs approval from People Ops.")
    return sources, passages, add


def test_connects_arbitrary_policy_interview_deal_role_and_documentation():
    sources, passages, _ = corpus()
    result = build_evidence_synthesis(CLAIM, passages, sources, date(2026, 10, 11))
    assert set(result["counts"]) == {"formal", "observed", "documented"}
    assert all(result["counts"].values())
    assert not any(n["source_id"] == "onboarding" for n in result["nodes"])
    assert any(n["relationship"] == "approval_referenced_elsewhere" for n in result["nodes"])
    assert any(
        n["citation"]["quotation"] == "Approval must be recorded in the CRM."
        for n in result["nodes"]
    )
    assert {"same_record", "recorded_person_role", "explicit_record_reference"} <= {
        e["relationship"] for e in result["edges"]
    }
    assert any(c["kind"] == "different_recorded_role" for c in result["comparisons"])
    ids = {"claim", *[n["id"] for n in result["nodes"]]}
    assert all(e["from"] in ids and e["to"] in ids for e in result["edges"])
    texts = {p.evidence_id: p.text for p in passages}
    for n in result["nodes"]:
        c = n["citation"]
        assert texts[c["evidence_id"]][c["start"] : c["end"]] == c["quotation"]


def test_excludes_future_interview_and_message_headers():
    sources, passages, add = corpus()
    sources["interview"].creation_date = date(2026, 6, 1)
    add(
        "later",
        "internal_communication",
        "**Timestamp:** 2026-07-01\nDiscount approval for SALE-809 was discussed.",
        heading="Message",
    )
    result = build_evidence_synthesis(CLAIM, passages, sources, date(2026, 2, 1))
    assert not any(n["source_id"] in {"interview", "later"} for n in result["nodes"])
    assert result["future_evidence_excluded"] == 2


def test_threshold_excludes_other_records_without_filling_missing_scope():
    sources, passages, add = corpus()
    add(
        "crm",
        "crm_records",
        json.dumps({"deal_id": "SALE-810", "discount_pct": "23", "approval_record": ""}),
        row_identifier="SALE-810",
    )
    result = build_evidence_synthesis(CLAIM, passages, sources, date(2026, 10, 11))
    assert not any(n["record_id"] == "SALE-810" for n in result["nodes"])
    assert result["scope"]["deal_scope"] is None
    assert any(n["details"].get("scope") == "not established" for n in result["nodes"])


def test_record_specific_claim_does_not_connect_other_deals():
    sources, passages, add = corpus()
    add(
        "crm",
        "crm_records",
        json.dumps({"deal_id": "SALE-810", "discount_pct": "31", "approval_role": "Alex Chen"}),
        row_identifier="SALE-810",
    )
    result = build_evidence_synthesis(
        "SALE-809 Alex approved 31% discount", passages, sources, date(2026, 10, 11)
    )
    assert {n["record_id"] for n in result["nodes"] if n["record_id"]} == {"SALE-809"}


def test_table_retains_only_subject_row_and_missing_record_is_not_denial():
    sources, passages, add = corpus()
    add(
        "table",
        "organisational_information",
        "| Discount approval | Sales in practice |\n| New hire onboarding | People Ops approval |",
    )
    add(
        "crm",
        "crm_records",
        json.dumps({"deal_id": "SALE-900", "discount_pct": "35", "approval_record": ""}),
        row_identifier="SALE-900",
    )
    result = build_evidence_synthesis(CLAIM, passages, sources, date(2026, 10, 11))
    table = [n for n in result["nodes"] if n["source_id"] == "table"]
    assert len(table) == 1 and "onboarding" not in table[0]["citation"]["quotation"]
    gap = next(n for n in result["nodes"] if n["relationship"] == "approval_documentation_gap")
    assert "not proof" in gap["reason"]


def test_unsupported_subject_returns_no_invented_links():
    sources, passages, _ = corpus()
    assert (
        build_evidence_synthesis(
            "The moon is made of cheese", passages, sources, date(2026, 10, 11)
        )
        is None
    )


def test_resolved_transaction_connects_the_same_record_and_discloses_resolution():
    sources, passages, add = corpus()
    add(
        "crm",
        "crm_records",
        json.dumps({"deal_id": "SALE-810", "discount_pct": "31", "approval_role": "Alex Chen"}),
        row_identifier="SALE-810",
    )
    claim = "Alex authorised a 31% discount on Slack"
    without = build_evidence_synthesis(claim, passages, sources, date(2026, 10, 11))
    assert not any(n["record_id"] for n in without["nodes"])
    result = build_evidence_synthesis(
        claim, passages, sources, date(2026, 10, 11), resolved_record_ids=["SALE-809"]
    )
    assert {n["record_id"] for n in result["nodes"] if n["record_id"]} == {"SALE-809"}
    assert any(n["relationship"] == "approval_referenced_elsewhere" for n in result["nodes"])
    assert any(n["relationship"] == "explicit_record_reference" for n in result["nodes"])
    assert result["record_selection"]["basis"] == "resolved_transaction"
    assert "original claim did not supply a record identifier" in result["notice"]
    assert result["scope"]["threshold"] is None
    assert any(e["relationship"] == "resolved_transaction_reference" for e in result["edges"])
    texts = {p.evidence_id: p.text for p in passages}
    for node in result["nodes"]:
        citation = node["citation"]
        assert texts[citation["evidence_id"]][citation["start"]:citation["end"]] == citation["quotation"]


def test_resolution_cannot_override_explicit_id_or_select_ambiguous_candidates():
    sources, passages, _ = corpus()
    explicit = build_evidence_synthesis(
        "SALE-900 Alex approved 31% discount", passages, sources, date(2026, 10, 11),
        resolved_record_ids=["SALE-809"],
    )
    assert not any(n["record_id"] for n in explicit["nodes"])
    for candidates in (["SALE-809", "SALE-810"], ["see SALE-809"], [None]):
        result = build_evidence_synthesis(
            "Alex approved 31% discount", passages, sources, date(2026, 10, 11),
            resolved_record_ids=candidates,
        )
        assert not any(n["record_id"] for n in result["nodes"])
        assert result["record_selection"]["basis"] != "resolved_transaction"


def test_resolved_transaction_remains_subject_to_date_filter():
    sources, passages, _ = corpus()
    result = build_evidence_synthesis(
        "Alex approved 31% discount", passages, sources, date(2026, 1, 1),
        resolved_record_ids=["SALE-809"],
    )
    assert not any(n["record_id"] for n in result["nodes"])
    assert not any(n["relationship"] == "explicit_record_reference" for n in result["nodes"])
    assert result["future_evidence_excluded"] == 1
