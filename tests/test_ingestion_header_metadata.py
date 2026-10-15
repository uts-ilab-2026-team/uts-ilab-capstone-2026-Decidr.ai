"""Document attribution, header boundaries and metadata provenance."""

import pytest

from decidr.corpus.ingest import build_source
from decidr.corpus.models import Source


def build(tmp_path, content):
    folder = tmp_path / "03_process_docs"
    folder.mkdir()
    path = folder / "example.md"
    path.write_bytes(content.encode("utf-8"))
    return build_source(path, tmp_path, "development")


@pytest.mark.parametrize("reference", [
    "(See POLICY-999 for an unapproved draft revision.)",
    "(See the proposed replacement for an unapproved draft revision.)",
])
def test_external_draft_does_not_override_own_approval(tmp_path, reference):
    approval = (
        "Approved. This is the current formally approved version. " + reference
    )
    source = build(
        tmp_path,
        "# Example\n\n- **Approval status:** " + approval + "\n",
    )
    assert source.lifecycle_status == "current"
    assert source.approval_status == approval
    assert source.effective_start_date is None
    assert any(
        clause["scope"] == "referenced_document"
        and clause["lifecycle"] == "draft"
        for clause in source.approval_clauses
    )
    for clause in source.approval_clauses:
        assert approval[clause["start"]:clause["end"]] == clause["quote"]


def test_own_draft_remains_draft(tmp_path):
    source = build(
        tmp_path, "# Example\n\n- **Approval status:** Draft; not approved.\n"
    )
    assert source.lifecycle_status == "draft"


@pytest.mark.parametrize("body", [
    "## Details\n- **Approval status:** Draft\n",
    "Ordinary body prose.\n- **Approval status:** Draft\n",
])
def test_empty_header_does_not_consume_body_metadata(tmp_path, body):
    source = build(tmp_path, "# Example\n\n" + body)
    assert source.approval_status is None
    assert source.header_evidence == []
    assert source.metadata_provenance["lifecycle_status"].startswith("inferred:")


def test_repeated_conflicting_fields_stay_unresolved(tmp_path):
    source = build(
        tmp_path,
        "# Example\n\n"
        "- **Approval status:** Approved\n"
        "- **Approval status:** Draft\n"
        "- **Effective date:** 2023-01-01\n"
        "- **Effective date:** 2024-01-01\n",
    )
    assert source.approval_status is None
    assert source.lifecycle_status == "unknown"
    assert source.effective_start_date is None
    assert len(source.header_evidence) == 4
    assert {"approval_status", "effective_date"} <= {
        item["field"] for item in source.metadata_conflicts
    }


def test_conflicting_own_approval_clauses_stay_unresolved(tmp_path):
    source = build(
        tmp_path,
        "# Example\n\n- **Approval status:** Approved. Draft; not approved.\n",
    )
    assert source.lifecycle_status == "unknown"
    assert source.metadata_conflicts


@pytest.mark.parametrize("value", [
    "See POLICY-999 effective 2023-01-01",
    "2023-01-01 or 2024-01-01",
    "2023-02-30",
])
def test_invalid_ambiguous_or_referenced_date_is_not_selected(tmp_path, value):
    source = build(
        tmp_path, "# Example\n\n- **Effective date:** " + value + "\n"
    )
    assert source.effective_start_date is None
    assert any(
        item["field"] == "effective_date" for item in source.metadata_conflicts
    )


def test_header_offsets_survive_crlf_unicode_and_serialisation(tmp_path):
    content = (
        "# Café procedure\r\n\r\n"
        "- **Approval status:** Approved\r\n"
        "- **Last updated:** 2024-04-12\r\n\r\n"
        "## Body\r\nExample.\r\n"
    )
    source = build(tmp_path, "\ufeff" + content)
    restored = Source.model_validate_json(source.model_dump_json())
    assert restored.metadata_version == "document-metadata-v1"
    assert len(restored.header_evidence) == 2
    for entry in restored.header_evidence:
        assert content[entry["start"]:entry["end"]] == entry["quote"]
        assert entry["source_id"] == source.source_id


def test_reversed_effective_interval_is_recorded_as_conflict(tmp_path):
    source = build(
        tmp_path,
        "# Example\n\n"
        "- **Effective date:** 2024-04-12\n"
        "- **Effective end date:** 2023-01-01\n",
    )
    assert source.effective_end_date is None
    assert any(
        item["field"] == "effective_end_date"
        for item in source.metadata_conflicts
    )
