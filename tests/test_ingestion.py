from pathlib import Path
import sqlite3

from decidr.ingestion import ingest, write_exports


def _write_fixture(root: Path) -> None:
    policy = root / "02_policies" / "POL-01_policy.md"
    policy.parent.mkdir(parents=True)
    policy.write_text(
        """# POL-01 — Test Policy

- **Document owner:** Reviewer, Finance
- **Version:** 1.0
- **Approval status:** Approved
- **Effective date:** 2025-01-01

## Requirement

Approval is required.

Approval must be recorded.
""",
        encoding="utf-8",
    )
    records = root / "07_crm" / "crm.csv"
    records.parent.mkdir(parents=True)
    records.write_text(
        "deal_id,status,close_date\nDEAL-1,Closed Won,2025-02-03\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text("# Release instructions\n", encoding="utf-8")


def test_ingestion_is_traceable_and_idempotent(tmp_path):
    release = tmp_path / "release"
    _write_fixture(release)
    database = tmp_path / "ledger.sqlite3"

    first = ingest({"test": release}, database)
    second = ingest({"test": release}, database)

    assert len(first.sources) == 3
    assert len(first.evidence) == 4
    assert first.dataset_fingerprint == second.dataset_fingerprint
    assert [item.evidence_id for item in first.evidence] == [
        item.evidence_id for item in second.evidence
    ]
    assert any(source.ingestion_status == "excluded" for source in first.sources)
    assert all(item.locator for item in first.evidence)
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 3
        assert connection.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 4


def test_exact_duplicates_are_grouped_across_releases(tmp_path):
    phase1 = tmp_path / "phase1"
    phase2 = tmp_path / "phase2"
    _write_fixture(phase1)
    _write_fixture(phase2)

    result = ingest({"phase1": phase1, "phase2": phase2})
    policies = [source for source in result.sources if source.source_type == "policy"]

    assert len(policies) == 2
    assert policies[0].duplicate_group == policies[1].duplicate_group
    assert policies[0].duplicate_group.startswith("sha256:")


def test_near_duplicates_are_candidates_not_independent_groups(tmp_path):
    phase1 = tmp_path / "phase1"
    phase2 = tmp_path / "phase2"
    _write_fixture(phase1)
    _write_fixture(phase2)
    changed = phase2 / "02_policies" / "POL-01_policy.md"
    changed.write_text(changed.read_text(encoding="utf-8") + "Minor wording.\n", encoding="utf-8")

    result = ingest({"phase1": phase1, "phase2": phase2})
    policies = [source for source in result.sources if source.source_type == "policy"]

    assert all(source.duplicate_group is None for source in policies)
    assert all("near_duplicate_candidate=" in source.metadata_notes for source in policies)


def test_exports_include_report_and_registers(tmp_path):
    release = tmp_path / "release"
    _write_fixture(release)
    result = ingest({"test": release})
    output = tmp_path / "exports"

    write_exports(result, output)

    assert (output / "source_register.json").is_file()
    assert (output / "source_register.csv").is_file()
    assert (output / "evidence_register.json").is_file()
    report = (output / "ingestion_report.md").read_text(encoding="utf-8")
    assert result.dataset_fingerprint in report


def test_missing_release_is_reported_not_fatal(tmp_path):
    result = ingest({"missing": tmp_path / "does-not-exist"})

    assert result.sources == []
    assert result.warnings == [
        f"Missing configured release directory: missing={tmp_path / 'does-not-exist'}"
    ]
