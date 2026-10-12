"""Authority assertions are cited without turning ownership into verification."""

from datetime import date

import pytest

from decidr.authority_context import authority_context
from decidr.ingestion import build_source, extract_markdown
from decidr.interpretation_models import InterpretationCitation

RULE = "Any discount of 22% or greater off list price on a wholesale deal requires written approval from the Director of Operations before the deal is marked Signed."


def packet(tmp_path, approval="Approved"):
    path = tmp_path / "rule.md"
    path.write_text(
        "# Commercial Rule\n\n- **Document owner:** Casey Example, Policy Coordinator\n"
        f"- **Approval status:** {approval}\n- **Effective date:** 2025-01-01\n\n"
        f"## Formal requirements\n\n{RULE}\n"
    )
    source = build_source(path, tmp_path, "development")
    source.source_type = "policy"
    passages = extract_markdown(source, path)
    focal = next(p for p in passages if p.text == RULE)
    citation = InterpretationCitation(
        evidence_id=focal.evidence_id,
        source_id=source.source_id,
        locator=focal.locator,
        quotation=RULE,
        start=0,
        end=len(RULE),
    )
    return {
        "source": source,
        "focal": focal,
        "citation": citation,
        "passages": passages,
        "facet": RULE,
        "as_of": date(2026, 6, 17).isoformat(),
    }


def test_owner_and_approver_remain_distinct_and_cited(tmp_path):
    args = packet(tmp_path)
    result = authority_context(**args)
    assert result["document_owner"]["value"] == "Casey Example, Policy Coordinator"
    assert result["operational_approver"]["value"]["approver"] == "the director of operations"
    assert result["document_approval"]["value"] == "current"
    assert result["policy_adoption"]["status"] == "unresolved"
    assert result["authority_verified"] is None
    by_id = {p.evidence_id: p for p in args["passages"]}
    for key in ("document_owner", "document_approval", "operational_approver"):
        for citation in result[key]["citations"]:
            p = by_id[citation["evidence_id"]]
            assert p.text[citation["start"] : citation["end"]] == citation["quotation"]


@pytest.mark.parametrize("status", ["Not approved", "Not yet approved", "Never approved"])
def test_negative_status_retained(tmp_path, status):
    result = authority_context(**packet(tmp_path, status))
    assert result["document_approval"]["value"] == "draft"
    assert result["authority_verified"] is None


def test_referenced_draft_does_not_change_document_status(tmp_path):
    result = authority_context(**packet(tmp_path, "Approved (see REF-999, never approved)"))
    assert result["document_approval"]["value"] == "current"


def test_missing_header_passage_does_not_invent_citation(tmp_path):
    args = packet(tmp_path)
    args["passages"] = [args["focal"]]
    result = authority_context(**args)
    assert result["document_owner"]["status"] == "unresolved"
    assert result["document_approval"]["status"] == "unresolved"


def test_metadata_conflict_remains_unresolved(tmp_path):
    args = packet(tmp_path)
    args["source"].metadata_conflicts = [
        {"field": "approval_status", "reason": "Conflicting assertions"}
    ]
    assert authority_context(**args)["document_approval"]["status"] == "unresolved"


def test_unverifiable_clause_offsets_stay_unresolved(tmp_path):
    args = packet(tmp_path)
    args["source"].approval_clauses[0]["start"] = 200
    assert authority_context(**args)["document_approval"]["status"] == "unresolved"


def test_citation_mismatch_rejected(tmp_path):
    args = packet(tmp_path)
    args["citation"] = args["citation"].model_copy(update={"source_id": "other"})
    with pytest.raises(ValueError):
        authority_context(**args)


def test_legacy_metadata_without_header_proof_stays_unresolved(tmp_path):
    args = packet(tmp_path)
    args["source"].header_evidence = []
    result = authority_context(**args)
    assert result["document_owner"]["status"] == "unresolved"
    assert result["document_approval"]["status"] == "unresolved"


def test_header_value_must_match_quoted_value(tmp_path):
    args = packet(tmp_path)
    for entry in args["source"].header_evidence:
        if entry["key"] == "document owner":
            entry["value"] = "Invented owner"
    assert authority_context(**args)["document_owner"]["status"] == "unresolved"
