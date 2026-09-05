import json

from decidr.database import connect, initialise_database, save_claim, save_retrieval_run
from decidr.exports import EXPORT_TABLES, export_ledger
from decidr.models import AtomicClaim


def test_complete_ledger_exports_include_empty_registers(tmp_path):
    database = tmp_path / "ledger.sqlite3"
    initialise_database(database)
    output = tmp_path / "exports"

    manifest = export_ledger(database, output)

    assert set(manifest["counts"]) == set(EXPORT_TABLES.values())
    for name in EXPORT_TABLES.values():
        assert (output / f"{name}.csv").is_file()
        assert (output / f"{name}.json").is_file()
    assert json.loads((output / "export_manifest.json").read_text())["formats"] == [
        "csv",
        "json",
        "markdown",
    ]


def test_retrieval_run_records_provenance_scores_latency_and_audit(tmp_path):
    database = tmp_path / "ledger.sqlite3"
    initialise_database(database)
    claim = AtomicClaim(
        claim_id="C1",
        subject="discount",
        predicate="requires",
        object="approval",
        claim_type="control",
        claim_text="Discount requires approval.",
    )
    with connect(database) as connection:
        save_claim(connection, claim)
        connection.execute(
            "INSERT INTO sources VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            ("S1", "{}", "a" * 64, "test.md", "ingested"),
        )
        connection.execute(
            "INSERT INTO evidence VALUES (?, ?, ?, ?, ?)",
            ("E1", "S1", "heading:test#block:001", "approval", "{}"),
        )
        save_retrieval_run(
            connection,
            run_id="RUN-1",
            claim_id="C1",
            method="lexical",
            query_text=claim.claim_text,
            configuration={"limit": 20},
            latency_ms=12.5,
            results=[
                {"evidence_id": "E1", "rank": 1, "component_scores": {"bm25": 2.0}}
            ],
        )
        run = connection.execute(
            "SELECT method, latency_ms FROM retrieval_runs WHERE run_id='RUN-1'"
        ).fetchone()
        result = connection.execute(
            "SELECT rank, component_scores_json FROM retrieval_results WHERE run_id='RUN-1'"
        ).fetchone()
        audits = connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE entity_id='RUN-1'"
        ).fetchone()[0]

    assert tuple(run) == ("lexical", 12.5)
    assert result[0] == 1
    assert json.loads(result[1]) == {"bm25": 2.0}
    assert audits == 1
