"""Approval negation is consistent across ingestion and proposal metadata."""

import pytest

from decidr.ingestion import build_source
from decidr.interpretation_engine import classify_source
from decidr.retrieval_models import Evidence, Source
from decidr.source_metadata import approval_lifecycle, approval_signals


def passage(source):
    return Evidence(
        evidence_id="example",
        source_id=source.source_id,
        locator="section:rule",
        text="Written approval is required.",
        source_type="policy",
        extraction_method="test",
    )


@pytest.mark.parametrize(
    "status",
    [
        "Not approved",
        "Not yet approved",
        "Never approved",
        "Not formally approved",
        "Not yet formally approved",
        "Never formally approved",
        "NOT  YET\tAPPROVED",
        "Unapproved",
    ],
)
def test_negative_status_across_ingestion_and_legacy_metadata(tmp_path, status):
    path = tmp_path / "policy.md"
    path.write_text(f"# Example\n\n- **Approval status:** {status}\n")
    source = build_source(path, tmp_path, "development")
    assert source.lifecycle_status == "draft"
    assert not source.metadata_conflicts
    assert approval_signals(status) == (True, False)
    for candidate in (
        source,
        source.model_copy(update={"approval_clauses": [], "lifecycle_status": "current"}),
    ):
        result = classify_source(candidate, passage(candidate))
        assert result.approval_key == "unapproved"
        assert result.authority_verified is None
    for clause in source.approval_clauses:
        assert status[clause["start"] : clause["end"]] == clause["quote"]


def test_reference_negation_does_not_change_own_approval(tmp_path):
    path = tmp_path / "policy.md"
    path.write_text(
        "# Example\n\n- **Approval status:** Approved (see POL-999, not yet approved)\n"
    )
    source = build_source(path, tmp_path, "development")
    assert source.lifecycle_status == "current"
    assert classify_source(source, passage(source)).approval_key == "approved"


def test_conflicting_approval_is_unresolved():
    status = "Approved; never approved"
    lifecycle, _, conflicts = approval_lifecycle(status, "POL-001")
    assert lifecycle == "unknown"
    assert conflicts
    source = Source(
        source_id="example",
        title="Example",
        source_type="policy",
        original_file_path="policy.md",
        checksum="a" * 64,
        approval_status=status,
        lifecycle_status="current",
    )
    assert classify_source(source, passage(source)).approval_key == "unknown"


def test_historical_approval_is_not_denial():
    assert approval_signals("Approved (historical — no longer in force)") == (False, True)
    assert (
        approval_lifecycle("Approved (historical — no longer in force)", "POL-001")[0]
        == "superseded"
    )
