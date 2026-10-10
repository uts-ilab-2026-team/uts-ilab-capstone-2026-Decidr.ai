"""Tests for the Saif retrieval -> graph credibility integration."""

from datetime import date
from hashlib import sha256
from pathlib import Path

import pytest

from decidr.corpus_assessment import (
    AssessmentStore,
    _source_class,
    assess_claim,
    evaluation_summary,
    extract_numeric_condition,
    interpret_evidence,
)
from decidr.corpus_search import CorpusResult
from decidr.database import connect, upsert_source, upsert_source_evidence
from decidr.models import Evidence, Source


def _source(
    source_id: str,
    source_type: str,
    *,
    title: str | None = None,
    duplicate_group: str | None = None,
) -> Source:
    return Source(
        source_id=source_id,
        title=title or source_id,
        original_file_path=f"{source_id}.csv",
        source_type=source_type,
        lifecycle_status="current",
        approval_status="approved" if source_type == "policy" else "recorded",
        checksum=sha256(source_id.encode()).hexdigest(),
        duplicate_group=duplicate_group,
    )


def _evidence(
    evidence_id: str,
    source: Source,
    text: str,
    *,
    locator: str,
    row_identifier: str | None = None,
    role: str | None = None,
    missing_approval: bool = False,
) -> Evidence:
    record = {"approval_role": "" if missing_approval else role or ""}
    return Evidence(
        evidence_id=evidence_id,
        source_id=source.source_id,
        locator=locator,
        text=text,
        source_type=source.source_type,
        row_identifier=row_identifier,
        role=role,
        extraction_method="test_fixture",
        structured_metadata={"record": record},
    )


def populated_store(tmp_path: Path) -> AssessmentStore:
    store = AssessmentStore(tmp_path / "evidence.sqlite3")
    policy = _source("phase2:POL-01", "policy", title="Discount Approval Policy")
    deal = _source("phase2:CRM-01", "crm_records", title="CRM Deals")
    audit = _source("phase2:AUD-01", "audit_events", title="System Audit Log")
    with connect(store.path) as connection:
        upsert_source(connection, policy)
        upsert_source_evidence(
            connection,
            policy.source_id,
            [
                _evidence(
                    "EV-POL-01",
                    policy,
                    (
                        "New-business discounts of 15 percent or greater require written "
                        "approval from the Head of Finance and People Ops before Closed Won."
                    ),
                    locator="heading:approval",
                )
            ],
        )
        upsert_source(connection, deal)
        upsert_source_evidence(
            connection,
            deal.source_id,
            [
                _evidence(
                    "EV-DEAL-01",
                    deal,
                    (
                        "DEAL-001 has an 18 percent discount approved by the Head of Sales "
                        "without Finance approval."
                    ),
                    locator="csv:row:2",
                    row_identifier="DEAL-001",
                    role="Head of Sales",
                )
            ],
        )
        upsert_source(connection, audit)
        upsert_source_evidence(
            connection,
            audit.source_id,
            [
                _evidence(
                    "EV-AUD-01",
                    audit,
                    "No linked approval record was found for deployment AUD-0111.",
                    locator="csv:row:9",
                    row_identifier="AUD-0111",
                    missing_approval=True,
                )
            ],
        )
    return store


def _corpus_result(
    text: str,
    *,
    role: str | None = None,
    source_type: str = "crm_records",
    temporal_status: str = "current_or_unspecified",
) -> CorpusResult:
    return CorpusResult(
        evidence_id="EV-1",
        source_id="SRC-1",
        source_title="Evidence source",
        locator="row:1",
        text=text,
        row_identifier="ROW-1",
        process=None,
        actor=None,
        role=role,
        system=None,
        rank=1,
        hybrid_score=1.0,
        ranking_score=1.0,
        lexical_rank=1,
        semantic_rank=None,
        source_type=source_type,
        lifecycle_status="current",
        version=None,
        approval_status="recorded",
        effective_start_date=None,
        effective_end_date=None,
        creation_date=None,
        temporal_status=temporal_status,
        duplicate_group=None,
        provenance_group="SRC-1",
        provenance_sources=("SRC-1",),
        possible_duplicate_of=(),
        missing_fields=(),
    )


def test_numeric_condition_preserves_operator_value_unit_and_role() -> None:
    condition = extract_numeric_condition(
        "Discounts of 15 percent or greater require the Head of Finance and People Ops."
    )
    assert condition is not None
    assert condition.value == 15
    assert condition.operator == ">="
    assert condition.unit == "percent"
    assert condition.role == "Head of Finance and People Ops"


def test_numeric_condition_reads_markdown_percentage_symbol() -> None:
    condition = extract_numeric_condition("Discounts of **15% or greater** require approval.")
    assert condition is not None
    assert condition.value == 15
    assert condition.operator == ">="


def test_saif_retrieval_returns_provenance_and_structured_context(tmp_path: Path) -> None:
    store = populated_store(tmp_path)
    package = store.retrieve("DEAL-001 18 percent Finance approval", limit=5, semantic=False)
    assert package.results
    first = package.results[0]
    assert first.locator
    assert first.provenance_group
    assert any(item.row_identifier == "DEAL-001" for item in package.results)
    assert package.semantic_status == "not_requested"


def test_assessment_retrieval_excludes_phase1_from_a_mixed_database(tmp_path: Path) -> None:
    store = AssessmentStore(tmp_path / "evidence.sqlite3")
    phase1 = _source("phase1:POL-OLD", "policy", title="Old policy")
    phase2 = _source("phase2:POL-CURRENT", "policy", title="Current policy")
    with connect(store.path) as connection:
        for source, evidence_id in ((phase1, "EV-OLD"), (phase2, "EV-CURRENT")):
            upsert_source(connection, source)
            upsert_source_evidence(
                connection,
                source.source_id,
                [
                    _evidence(
                        evidence_id,
                        source,
                        "Finance approval is required for discounts.",
                        locator="heading:approval",
                    )
                ],
            )

    package = store.retrieve(
        "Finance approval discounts",
        limit=5,
        semantic=False,
        as_of=date(2026, 7, 31),
    )
    assert {item.source_id for item in package.results} == {"phase2:POL-CURRENT"}
    assert store.counts()["sources"] == 1
    assert store.counts()["evidence"] == 1


def test_missing_link_is_qualification_not_contradiction() -> None:
    result = _corpus_result("No linked approval record was found for deployment AUD-0111.")
    interpretation = interpret_evidence(
        "The deployment received approval before release.",
        result,
    )
    assert interpretation.relationship == "qualify"
    assert "gap" in interpretation.rationale


def test_triggered_threshold_with_wrong_authority_remains_unresolved() -> None:
    result = _corpus_result(
        "The 18 percent discount was approved by the Head of Sales without Finance approval.",
        role="Head of Sales",
    )
    interpretation = interpret_evidence(
        "Discounts of 15 percent or greater require approval from the Head of Finance.",
        result,
    )
    assert interpretation.relationship == "unresolved"
    assert interpretation.comparison_result is not None
    assert "meets" in interpretation.comparison_result
    assert "authority differs" in interpretation.comparison_result


def test_negative_wording_does_not_become_support_from_overlap() -> None:
    interpretation = interpret_evidence(
        "Finance approval is required.",
        _corpus_result("Finance approval is not required."),
    )
    assert interpretation.relationship == "unresolved"


def test_different_business_scope_does_not_become_support() -> None:
    interpretation = interpret_evidence(
        "New-business discounts require Finance approval.",
        _corpus_result("Renewal discounts require Finance approval."),
    )
    assert interpretation.relationship == "unresolved"
    assert interpretation.scope_match is None


def test_ingestion_source_types_map_to_configured_credibility_classes() -> None:
    assert _source_class("crm_records") == "structured_operational_record"
    assert _source_class("audit_events") == "system_verified"
    assert _source_class("meeting") == "meeting_record"
    assert _source_class("interview") == "interview"


def test_end_to_end_assessment_preserves_saif_retrieval_and_graph_trace(
    tmp_path: Path,
) -> None:
    store = populated_store(tmp_path)
    claim = (
        "New-business discounts of 15 percent or greater require written approval from "
        "the Head of Finance and People Ops before Closed Won."
    )
    result = assess_claim(
        store,
        claim,
        as_of=date(2026, 7, 31),
        semantic=False,
    )
    assert result["claim_text"] == claim
    assert result["assessment_id"].startswith("ASM-")
    assert result["retrieval"]["results"]
    assert result["retrieval"]["semantic_status"] == "not_requested"
    assert result["retrieval"]["query_period_start"] == "2026-07-31"
    assert result["retrieval"]["query_period_end"] == "2026-07-31"
    assert len(result["retrieval"]["results"]) == len(result["interpretations"])
    assert not any(
        item["relationship"] in {"support", "contradict"} for item in result["interpretations"]
    )
    assert result["credibility"]["rules_applied"]
    assert "R1_SAIF_FTS5_BM25_RETRIEVAL" in result["rules_applied"]


def test_two_agreeing_reviews_promote_a_human_finding(tmp_path: Path) -> None:
    store = populated_store(tmp_path)
    result = assess_claim(
        store,
        "DEAL-001 received Finance approval.",
        as_of=date(2026, 7, 31),
        semantic=False,
    )
    assessment_id = result["assessment_id"]
    store.save_review(
        assessment_id,
        "Reviewer A",
        "Supported",
        "Higher confidence",
        "CRM row independently checked.",
    )
    store.save_review(
        assessment_id,
        "Reviewer B",
        "Supported",
        "Moderate confidence",
        "Citation independently checked.",
    )
    row = store.register_rows()[0]
    assert row["status"] == "Human-reviewed finding"
    assert row["final_outcome"] == "Supported"
    assert row["final_confidence"] == "Moderate confidence"
    assert evaluation_summary([row])["final_findings"] == 1


def test_reviewer_identity_is_case_insensitive_and_immutable(tmp_path: Path) -> None:
    store = populated_store(tmp_path)
    result = assess_claim(
        store,
        "DEAL-001 received Finance approval.",
        as_of=date(2026, 7, 31),
        semantic=False,
    )
    assessment_id = result["assessment_id"]
    store.save_review(
        assessment_id,
        "Reviewer A",
        "Supported",
        "Higher confidence",
        "Initial review.",
    )
    with pytest.raises(ValueError, match="immutable review"):
        store.save_review(
            assessment_id,
            "reviewer a",
            "Supported",
            "Moderate confidence",
            "Updated review.",
        )
    row = store.register_rows()[0]
    assert row["human_reviewers"] == 1
    assert row["status"] == "Awaiting second review"


def test_repeated_assessment_creates_immutable_history(tmp_path: Path) -> None:
    store = populated_store(tmp_path)
    first = assess_claim(
        store,
        "DEAL-001 received Finance approval.",
        as_of=date(2026, 7, 31),
        semantic=False,
    )
    second = assess_claim(
        store,
        "DEAL-001 received Finance approval.",
        as_of=date(2026, 7, 31),
        semantic=False,
    )
    assert first["assessment_id"] != second["assessment_id"]
    assert store.counts()["assessments"] == 2


def test_disagreement_requires_adjudication(tmp_path: Path) -> None:
    store = populated_store(tmp_path)
    result = assess_claim(
        store,
        "AUD-0111 had sign-off.",
        as_of=date(2026, 7, 31),
        semantic=False,
    )
    assessment_id = result["assessment_id"]
    store.save_review(
        assessment_id,
        "Reviewer A",
        "Supported",
        "Moderate confidence",
        "First judgement.",
    )
    store.save_review(
        assessment_id,
        "Reviewer B",
        "Insufficient evidence",
        "Lower confidence",
        "Missing approval record.",
    )
    assert store.register_rows()[0]["status"] == "Needs adjudication"
    store.save_adjudication(
        assessment_id,
        "Adjudicator",
        "Insufficient evidence",
        "Lower confidence",
        "Missingness is neither support nor contradiction.",
    )
    final_row = store.register_rows()[0]
    assert final_row["status"] == "Adjudicated final finding"
    assert final_row["final_outcome"] == "Insufficient evidence"
