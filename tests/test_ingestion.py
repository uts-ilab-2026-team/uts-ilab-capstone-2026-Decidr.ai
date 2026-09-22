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


def test_superseded_date_populates_effective_end_date(tmp_path):
    root = tmp_path / "release"
    policy = root / "02_policies" / "POL-99.md"
    policy.parent.mkdir(parents=True)

    policy.write_text(
        "# POL-99 — Historical Policy\n\n"
        "- **Effective date:** 2021-06-01\n"
        "- **Superseded date:** 2025-02-28\n\n"
        "## Rule\n\nHistorical rule.\n",
        encoding="utf-8",
    )

    result = ingest({"test": root})

    source = next(item for item in result.sources if item.source_id == "test:POL-99")
    assert source.effective_start_date.isoformat() == "2021-06-01"
    assert source.effective_end_date.isoformat() == "2025-02-28"


def test_structured_csv_context_populates_existing_evidence_fields(tmp_path):
    root = tmp_path / "release"
    tasks = root / "08_project_tasks" / "project_tasks.csv"
    audit = root / "09_audit_log" / "system_audit_log.csv"
    deals = root / "07_crm" / "crm_deals.csv"
    for path in (tasks, audit, deals):
        path.parent.mkdir(parents=True, exist_ok=True)

    tasks.write_text(
        "task_id,process_or_capability,owner_role,owner_name,due_date\n"
        "TASK-TEST,Customer Onboarding,Implementation Specialist,Ben Lockwood,2026-01-10\n",
        encoding="utf-8",
    )
    audit.write_text(
        "event_id,timestamp,system,actor_role,actor_name,action\n"
        "AUD-TEST,2026-02-18 16:30,Billing Integration,Senior Engineer,Ana Kowalski,"
        "Deployed fix\n",
        encoding="utf-8",
    )
    deals.write_text(
        "deal_id,ae_owner,discount_pct,approval_record,approval_role,close_date\n"
        "DEAL-TEST,Callum Reyes,20,Recorded in CRM,Head of Finance,2026-01-20\n",
        encoding="utf-8",
    )

    result = ingest({"test": root})
    evidence = {item.row_identifier: item for item in result.evidence}

    task = evidence["TASK-TEST"]
    assert (task.process, task.actor, task.role, task.system) == (
        "Customer Onboarding",
        "Ben Lockwood",
        "Implementation Specialist",
        "Project System",
    )
    assert task.structured_metadata["field_mapping"]["process"] == (
        "direct:csv_column:process_or_capability"
    )

    event = evidence["AUD-TEST"]
    assert (event.actor, event.role, event.system) == (
        "Ana Kowalski",
        "Senior Engineer",
        "Billing Integration",
    )
    assert event.structured_metadata["field_mapping"]["system"] == (
        "direct:csv_column:system"
    )

    deal = evidence["DEAL-TEST"]
    assert deal.actor == "Callum Reyes"
    assert deal.role == "Head of Finance"
    assert deal.system == "CRM"
    assert deal.structured_metadata["record"]["discount_pct"] == "20"
    assert deal.structured_metadata["field_mapping"]["system"] == (
        "inferred:source_type:crm_records"
    )
    assert deal.structured_metadata["field_mapping"]["role"] == (
        "direct:csv_column:approval_role"
    )
