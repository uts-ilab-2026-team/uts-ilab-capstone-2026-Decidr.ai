"""Complete reproducibility exports from the relational evidence ledger."""

import csv
from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3

from loguru import logger
import typer

from decidr.config import DATABASE_PATH, REPORTS_DIR
from decidr.database import connect

app = typer.Typer()

EXPORT_TABLES = {
    "sources": "source_register",
    "evidence": "evidence_register",
    "claims": "claim_register",
    "claim_evidence_links": "claim_evidence_links",
    "credibility_assessments": "credibility_assessments",
    "claim_assessments": "claim_assessments",
    "adjudications": "adjudicated_references",
    "rule_traces": "rule_traces",
    "retrieval_runs": "retrieval_runs",
    "retrieval_results": "retrieval_results",
    "evaluation_errors": "evaluation_errors",
    "audit_events": "audit_history",
}


def _rows(connection: sqlite3.Connection, table: str) -> list[dict[str, object]]:
    rows = connection.execute(f"SELECT * FROM {table}").fetchall()
    return [dict(row) for row in rows]


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def export_ledger(database_path: Path, output_dir: Path) -> dict[str, object]:
    """Export every review, reasoning, retrieval, and audit register to CSV and JSON."""
    output_dir.mkdir(parents=True, exist_ok=True)
    counts = {}
    with connect(database_path) as connection:
        for table, name in EXPORT_TABLES.items():
            rows = _rows(connection, table)
            counts[name] = len(rows)
            _write_csv(output_dir / f"{name}.csv", rows)
            (output_dir / f"{name}.json").write_text(
                json.dumps(rows, indent=2, default=str), encoding="utf-8"
            )
        assessments = _rows(connection, "claim_assessments")
    reports_dir = output_dir / "claim_reports"
    reports_dir.mkdir(exist_ok=True)
    for row in assessments:
        payload = json.loads(str(row["payload_json"]))
        if not str(payload["reviewer"]).startswith("automated:"):
            continue
        safe_id = "".join(
            character if character.isalnum() or character in "-_" else "-"
            for character in payload["claim_id"]
        )
        (reports_dir / f"{safe_id}-{row['assessment_id']}.md").write_text(
            payload["explanation"], encoding="utf-8"
        )
    manifest = {
        "exported_at": datetime.now(UTC).isoformat(),
        "database_path": str(database_path.resolve()),
        "counts": counts,
        "formats": ["csv", "json", "markdown"],
    }
    (output_dir / "export_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return manifest


@app.command()
def main(database: str = str(DATABASE_PATH), output: str = str(REPORTS_DIR / "exports")) -> None:
    """Export all ledger registers and available claim assessment reports."""
    manifest = export_ledger(Path(database), Path(output))
    logger.success("Exported {} registers", len(manifest["counts"]))


if __name__ == "__main__":
    app()
