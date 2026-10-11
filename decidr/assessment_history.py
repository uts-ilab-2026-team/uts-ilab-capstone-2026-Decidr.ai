"""Append-only assessment snapshots in a dedicated SQLite database.

Hashes detect accidental changes; they are not signatures against a database
administrator. Source/configuration snapshots are returned without recomputation.
"""

from contextlib import closing
from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import sqlite3
from uuid import uuid4


class HistoryNotFound(Exception):
    """No snapshot is visible to this owner."""


class HistoryConflict(Exception):
    """A retry or revision conflicts with the existing record."""


class HistoryIntegrityError(Exception):
    """Stored history or its schema failed verification."""


def canonical_json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def content_hash(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


SCHEMA = """
BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS assessment_runs (
    run_id TEXT PRIMARY KEY,
    owner_id INTEGER NOT NULL,
    request_id TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    parent_run_id TEXT REFERENCES assessment_runs(run_id),
    created_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    UNIQUE(owner_id, request_id)
);
CREATE INDEX IF NOT EXISTS assessment_owner_date ON assessment_runs(owner_id, created_at, run_id);
CREATE TRIGGER IF NOT EXISTS assessment_no_update BEFORE UPDATE ON assessment_runs
BEGIN SELECT RAISE(ABORT, 'Assessment history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS assessment_no_delete BEFORE DELETE ON assessment_runs
BEGIN SELECT RAISE(ABORT, 'Assessment history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS assessment_no_replace BEFORE INSERT ON assessment_runs
WHEN EXISTS(SELECT 1 FROM assessment_runs WHERE run_id=NEW.run_id
    OR (owner_id=NEW.owner_id AND request_id=NEW.request_id))
BEGIN SELECT RAISE(ABORT, 'Assessment history is append-only'); END;
PRAGMA user_version=1;
COMMIT;
"""


def _check_schema(connection: sqlite3.Connection) -> None:
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version != 1:
        raise HistoryIntegrityError("Unrecognised assessment-history schema")
    columns = {row[1] for row in connection.execute("PRAGMA table_info(assessment_runs)")}
    if columns != {
        "run_id",
        "owner_id",
        "request_id",
        "request_hash",
        "parent_run_id",
        "created_at",
        "payload_json",
        "payload_hash",
    }:
        raise HistoryIntegrityError("Unrecognised assessment-history table")


def _connect(path: Path, *, write: bool = False) -> sqlite3.Connection:
    if write:
        path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path.as_uri() + ("?mode=rwc" if write else "?mode=ro"), uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA recursive_triggers=ON")
        if write:
            tables = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            if not tables:
                connection.executescript(SCHEMA)
        else:
            connection.execute("PRAGMA query_only=ON")
        _check_schema(connection)
    except Exception:
        connection.close()
        raise
    return connection


def _decode(row: sqlite3.Row) -> dict:
    try:
        payload = json.loads(row["payload_json"])
        if content_hash(payload) != row["payload_hash"]:
            raise HistoryIntegrityError("Snapshot hash mismatch")
        if (
            payload["run_id"] != row["run_id"]
            or payload["owner_id"] != row["owner_id"]
            or payload["parent_run_id"] != row["parent_run_id"]
            or payload["created_at"] != row["created_at"]
            or content_hash(payload["save_request"]) != row["request_hash"]
            or payload["save_request"]["request_id"] != row["request_id"]
        ):
            raise HistoryIntegrityError("Snapshot identity mismatch")
    except (ValueError, KeyError, TypeError) as error:
        raise HistoryIntegrityError("Invalid assessment snapshot") from error
    return {"snapshot": payload, "snapshot_sha256": row["payload_hash"]}


def get_run(path: Path, owner_id: int, run_id: str) -> dict:
    if not path.is_file():
        raise HistoryNotFound()
    with closing(_connect(path)) as connection:
        row = connection.execute(
            "SELECT * FROM assessment_runs WHERE owner_id=? AND run_id=?", (owner_id, run_id)
        ).fetchone()
    if row is None:
        raise HistoryNotFound()
    return _decode(row)


def _retry(connection: sqlite3.Connection, owner_id: int, request: dict) -> dict | None:
    row = connection.execute(
        "SELECT * FROM assessment_runs WHERE owner_id=? AND request_id=?",
        (owner_id, request["request_id"]),
    ).fetchone()
    if row is None:
        return None
    if row["request_hash"] != content_hash(request):
        raise HistoryConflict("request_id was already used for a different save request")
    return _decode(row)


def existing_retry(path: Path, owner_id: int, request: dict) -> dict | None:
    if not path.is_file():
        return None
    with closing(_connect(path)) as connection:
        return _retry(connection, owner_id, request)


def list_runs(path: Path, owner_id: int, *, limit: int, offset: int) -> list[dict]:
    if not path.is_file():
        return []
    with closing(_connect(path)) as connection:
        rows = connection.execute(
            "SELECT * FROM assessment_runs WHERE owner_id=? ORDER BY created_at DESC, run_id DESC LIMIT ? OFFSET ?",
            (owner_id, limit, offset),
        ).fetchall()
    result = []
    for row in rows:
        record = _decode(row)
        snapshot = record["snapshot"]
        response = snapshot["response"]
        result.append(
            {
                "run_id": snapshot["run_id"],
                "parent_run_id": snapshot["parent_run_id"],
                "created_at": snapshot["created_at"],
                "claim_text": response["claim_text"],
                "facet": response["facet"],
                "as_of": response["as_of"],
                "overall_outcome": response["assessment"]["overall_outcome"],
                "formal_outcome": response["assessment"]["formal_outcome"],
                "observed_outcome": response["assessment"]["observed_outcome"],
                "record_type": snapshot.get("record_type", "conditional_supplied_assessment"),
                "outcome_basis": response["assurance"]["outcome_basis"],
                "review_status": snapshot["review_status"],
                "snapshot_sha256": record["snapshot_sha256"],
            }
        )
    return result


def append_run(path: Path, owner_id: int, request: dict, bundle: dict) -> tuple[dict, bool]:
    """Atomically save a server-assessed bundle, or return an identical retry."""
    with closing(_connect(path, write=True)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        previous = _retry(connection, owner_id, request)
        if previous is not None:
            return previous, False
        parent_id = request.get("parent_run_id")
        parent_hash = None
        if parent_id:
            row = connection.execute(
                "SELECT * FROM assessment_runs WHERE owner_id=? AND run_id=?",
                (owner_id, parent_id),
            ).fetchone()
            if row is None:
                raise HistoryNotFound()
            parent = _decode(row)
            for key in ("claim_text", "facet", "assessment_target"):
                if parent["snapshot"]["request"][key] != bundle["request"][key]:
                    raise HistoryConflict(
                        "A revision must preserve the original claim, facet and target"
                    )
            parent_hash = parent["snapshot_sha256"]
        payload = deepcopy(bundle)
        payload.update(
            {
                "schema_version": "assessment-history-v1",
                "run_id": str(uuid4()),
                "owner_id": owner_id,
                "created_at": datetime.now(UTC).isoformat(),
                "parent_run_id": parent_id,
                "parent_snapshot_sha256": parent_hash,
                "save_request": request,
                "review_status": "not_established",
                "revision_reason": request.get("revision_reason"),
                "record_type": (
                    "automatic_assessment"
                    if bundle["response"]["status"] == "assessed_automatically"
                    else "conditional_supplied_assessment"
                ),
            }
        )
        payload["response"].update(persisted=True, index_scope="frozen")
        payload["provenance"]["revision_basis"] = "current_index_at_save_time"
        digest = content_hash(payload)
        connection.execute(
            "INSERT INTO assessment_runs VALUES(?,?,?,?,?,?,?,?)",
            (
                payload["run_id"],
                owner_id,
                request["request_id"],
                content_hash(request),
                parent_id,
                payload["created_at"],
                canonical_json(payload),
                digest,
            ),
        )
    return {"snapshot": payload, "snapshot_sha256": digest}, True
