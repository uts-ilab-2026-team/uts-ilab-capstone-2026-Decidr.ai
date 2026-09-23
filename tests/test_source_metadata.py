"""Source attribution, conflict retention and unknown supersession boundaries."""

from datetime import date
from pathlib import Path

from decidr.ingestion import build_source, extract_markdown
from decidr.source_metadata import metadata_constraint


def source(tmp_path, header, body="## Body\n\nA requirement."):
    path = tmp_path / "procedure.md"
    path.write_text(f"# A procedure\n\n{header}\n\n{body}\n")
    return build_source(path, tmp_path, "phase2"), path


def test_own_approval_is_not_referenced_draft(tmp_path):
    header = "- **Approval status:** Approved. This is the current formally approved version. (See DOC-913 for an unapproved draft revision.)"
    item, path = source(tmp_path, header)
    assert item.lifecycle_status == "current"
    assert item.approval_status == header.split(":** ")[1]
    entry = item.metadata_evidence[0]
    assert entry["quote"] == header
    assert path.read_text()[entry["start"] : entry["end"]] == header
    assert entry["source_id"] == item.source_id
    referenced = [c for c in entry["clauses"] if c["scope"] == "referenced_document"]
    assert referenced[0]["references"] == ["DOC-913"]
    assert referenced[0]["lifecycle"] == "draft"
    for clause in entry["clauses"]:
        assert item.approval_status[clause["start"] : clause["end"]] == clause["quote"]
    assert header in extract_markdown(item, path)[0].text


def test_conflicting_own_status_and_duplicate_dates_are_unresolved(tmp_path):
    item, _ = source(
        tmp_path,
        "- **Approval status:** Approved. This version is draft.\n"
        "- **Effective date:** 2024-01-01\n- **Effective date:** 2024-02-01",
    )
    assert item.lifecycle_status == "unknown"
    assert item.effective_start_date is None
    assert len(item.metadata_conflicts) == 2
    assert len(item.metadata_evidence) == 3
    assert (
        metadata_constraint(item.model_dump(mode="json"), date(2024, 3, 1), date(2024, 3, 1))[0]
        == "unknown"
    )


def test_no_header_does_not_consume_body_metadata(tmp_path):
    item, _ = source(
        tmp_path,
        "",
        "## Somebody else\n- **Approval status:** Draft\n- **Date:** 2025-01-01\n# Another title",
    )
    assert item.title == "A procedure"
    assert item.approval_status is None
    assert item.creation_date is None
    assert item.metadata_evidence == []


def test_updated_is_not_created_or_effective_and_reference_date_not_local(tmp_path):
    item, _ = source(
        tmp_path, "- **Last updated:** 2024-01-01\n- **Effective date:** See DOC-22 (2023-01-01)"
    )
    assert item.last_updated_date == date(2024, 1, 1)
    assert item.creation_date is item.effective_start_date is None
    assert item.metadata_conflicts[0]["field"] == "effective_date"


def test_supersession_retains_date_without_inventing_inclusion(tmp_path):
    item, _ = source(
        tmp_path,
        "- **Approval status:** Approved (historical — no longer in force)\n"
        "- **Effective date:** 2021-06-01\n- **Superseded date:** 2025-02-28",
    )
    assert item.lifecycle_status == "superseded"
    assert item.superseded_date == date(2025, 2, 28)
    assert item.effective_end_date is None
    assert item.metadata_conflicts == []
    for day, expected in [(27, None), (28, "unknown")]:
        at = date(2025, 2, day)
        assert metadata_constraint(item.model_dump(mode="json"), at, at)[0] == expected
    at = date(2025, 3, 1)
    assert metadata_constraint(item.model_dump(mode="json"), at, at)[0] == "no"


def test_invalid_date_and_inverted_interval_do_not_abort_ingestion(tmp_path):
    item, _ = source(tmp_path, "- **Effective date:** 2025-02-31")
    assert item.effective_start_date is None
    assert item.metadata_conflicts
    item, _ = source(
        tmp_path, "- **Effective date:** 2025-03-01\n- **Superseded date:** 2024-01-01"
    )
    assert item.superseded_date == date(2024, 1, 1)
    assert item.metadata_conflicts[0]["field"] == "supersession"


def test_referenced_approval_does_not_establish_own_status(tmp_path):
    item, _ = source(tmp_path, "- **Approval status:** See DOC-22, approved.")
    assert item.lifecycle_status == "unknown"
    assert item.metadata_conflicts


def test_real_corpus_metadata_regressions():
    from decidr.ingestion import ingest

    root = Path(__file__).resolve().parents[1] / "data/raw/phase2_model_development"
    result = ingest({"phase2": root})
    sources = {s.source_id: s for s in result.sources}
    assert sources["phase2:PROC-05"].lifecycle_status == "current"
    assert sources["phase2:POL-04"].lifecycle_status == "draft"
    assert sources["phase2:POL-02"].superseded_date == date(2025, 2, 28)
    assert sources["phase2:POL-02"].effective_end_date is None
    assert sources["phase2:POL-02"].successor_source_id == "phase2:POL-01"
    assert len(result.sources) == 45
    assert len(result.evidence) == 812


def test_unheaded_body_cannot_supply_header_fields(tmp_path):
    item, _ = source(tmp_path, "", "Some body prose.\n- **Approval status:** Draft")
    assert item.metadata_evidence == []


def test_explicit_current_status_conflicts_with_supersession(tmp_path):
    item, _ = source(
        tmp_path,
        "- **Approval status:** Approved. This is the current version.\n- **Superseded date:** 2025-01-01",
    )
    assert item.lifecycle_status == "unknown"
    assert item.metadata_conflicts[0]["field"] == "lifecycle_status"


def test_conflicting_successors_are_not_last_write_wins(tmp_path):
    from decidr.ingestion import ingest

    root = tmp_path / "02_policies"
    root.mkdir()
    (root / "POL-91.md").write_text("# Old\n\n- **Superseded by:** POL-92\n")
    (root / "POL-92.md").write_text("# New\n")
    (root / "POL-93.md").write_text("# Other\n\n- **Supersedes:** POL-91\n")
    result = ingest({"phase2": tmp_path})
    old = next(s for s in result.sources if s.source_id == "phase2:POL-91")
    assert old.successor_source_id is None
    assert old.metadata_conflicts[0]["field"] == "supersession"


def test_reference_without_a_policy_id_does_not_supply_own_status(tmp_path):
    item, _ = source(
        tmp_path, "- **Approval status:** Approved. (See replacement_handbook.md for the draft.)"
    )
    assert item.lifecycle_status == "current"
    assert item.metadata_evidence[0]["clauses"][-1]["scope"] == "referenced_document"
