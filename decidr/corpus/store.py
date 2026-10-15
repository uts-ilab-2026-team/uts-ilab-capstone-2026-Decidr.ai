"""SQLite source, passage, search-index and embedding storage.

Source-writing functions and schema adapted from retrieval commit 90ffff9.
This store contains no claim-review or assessment-history tables.
"""

from contextlib import closing
from pathlib import Path
import sqlite3

from decidr.corpus.models import Evidence, Source

SCHEMA = "CREATE TABLE IF NOT EXISTS sources (\n                source_id TEXT PRIMARY KEY,\n                payload_json TEXT NOT NULL,\n                checksum TEXT NOT NULL,\n                original_file_path TEXT NOT NULL UNIQUE,\n                ingestion_status TEXT NOT NULL,\n                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,\n                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP\n            );\nCREATE TABLE IF NOT EXISTS evidence (\n                evidence_id TEXT PRIMARY KEY,\n                source_id TEXT NOT NULL REFERENCES sources(source_id) ON DELETE CASCADE,\n                locator TEXT NOT NULL,\n                text_content TEXT NOT NULL,\n                payload_json TEXT NOT NULL,\n                UNIQUE(source_id, locator)\n            );\nCREATE VIRTUAL TABLE IF NOT EXISTS evidence_fts USING fts5(\n                evidence_id UNINDEXED,\n                text_content,\n                tokenize='porter unicode61'\n            );\nCREATE TABLE IF NOT EXISTS embedding_cache (\n                evidence_id TEXT NOT NULL REFERENCES evidence(evidence_id) ON DELETE CASCADE,\n                model_name TEXT NOT NULL,\n                model_version TEXT NOT NULL,\n                content_checksum TEXT NOT NULL,\n                vector_json TEXT NOT NULL,\n                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,\n                PRIMARY KEY(evidence_id, model_name, model_version)\n            );"


def connect(path: Path) -> sqlite3.Connection:
    """Open a retrieval connection with referential integrity enabled."""
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialise_database(path: Path) -> None:
    """Create the retrieval tables and close the setup connection."""
    with closing(connect(path)) as connection, connection:
        connection.executescript(SCHEMA)


def upsert_source(connection: sqlite3.Connection, source: Source) -> None:
    """Insert or refresh a source record without creating duplicates."""
    connection.execute(
        """
        INSERT INTO sources(
            source_id, payload_json, checksum, original_file_path, ingestion_status
        ) VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(source_id) DO UPDATE SET
            payload_json=excluded.payload_json,
            checksum=excluded.checksum,
            original_file_path=excluded.original_file_path,
            ingestion_status=excluded.ingestion_status,
            updated_at=CURRENT_TIMESTAMP
        """,
        (
            source.source_id,
            source.model_dump_json(),
            source.checksum,
            source.original_file_path,
            source.ingestion_status,
        ),
    )


def replace_source_evidence(
    connection: sqlite3.Connection,
    source_id: str,
    evidence: list[Evidence],
) -> None:
    """Replace a source's complete passage snapshot atomically.

    An empty list removes all passages for the source.
    Only call after successful extraction, not after an extraction failure.
    Existing embeddings for this source are invalidated by cascade deletion.
    The caller controls any surrounding transaction.
    """
    if any(item.source_id != source_id for item in evidence):
        raise ValueError("Every passage must belong to the supplied source")

    if (
        connection.execute("SELECT 1 FROM sources WHERE source_id = ?", (source_id,)).fetchone()
        is None
    ):
        raise ValueError(f"Unknown source: {source_id}")

    connection.execute("SAVEPOINT replace_source_passages")
    try:
        connection.execute(
            """DELETE FROM evidence_fts WHERE evidence_id IN (
                SELECT evidence_id FROM evidence WHERE source_id = ?
            )""",
            (source_id,),
        )
        connection.execute("DELETE FROM evidence WHERE source_id = ?", (source_id,))
        connection.executemany(
            """INSERT INTO evidence(
                evidence_id, source_id, locator, text_content, payload_json
            ) VALUES (?, ?, ?, ?, ?)""",
            [
                (
                    item.evidence_id,
                    item.source_id,
                    item.locator,
                    item.text,
                    item.model_dump_json(),
                )
                for item in evidence
            ],
        )
        connection.executemany(
            "INSERT INTO evidence_fts(evidence_id, text_content) VALUES (?, ?)",
            [(item.evidence_id, item.text) for item in evidence],
        )
    except BaseException:
        connection.execute("ROLLBACK TO SAVEPOINT replace_source_passages")
        connection.execute("RELEASE SAVEPOINT replace_source_passages")
        raise
    else:
        connection.execute("RELEASE SAVEPOINT replace_source_passages")
