"""Regression tests for retrieval index refresh and transaction safety."""

from contextlib import closing
import sqlite3

import pytest

from decidr.corpus.models import Evidence, Source
from decidr.corpus.store import (
    connect,
    initialise_database,
    replace_source_evidence,
    upsert_source,
)


def passage(identifier, source="source:a", text="replacementword", locator=None):
    return Evidence(
        evidence_id=identifier,
        source_id=source,
        locator=locator or identifier,
        text=text,
        source_type="policy",
        extraction_method="test_fixture",
    )


@pytest.fixture
def store(tmp_path):
    path = tmp_path / "retrieval.sqlite"
    initialise_database(path)

    with closing(connect(path)) as connection:
        for suffix in ("a", "b"):
            upsert_source(
                connection,
                Source(
                    source_id=f"source:{suffix}",
                    title=f"Source {suffix}",
                    original_file_path=str(tmp_path / f"{suffix}.md"),
                    source_type="policy",
                    checksum="a" * 64,
                    ingestion_status="ingested",
                ),
            )

        replace_source_evidence(
            connection,
            "source:a",
            [
                passage("a:1", text="originalword"),
                passage("a:2", text="obsoleteword"),
            ],
        )
        replace_source_evidence(
            connection,
            "source:b",
            [passage("b:1", source="source:b", text="unrelatedword")],
        )
        connection.executemany(
            """INSERT INTO embedding_cache(
                evidence_id, model_name, model_version,
                content_checksum, vector_json
            ) VALUES (?, ?, ?, ?, ?)""",
            [
                (identifier, "test-model", "1", "a" * 64, "[1.0, 0.0]")
                for identifier in ("a:1", "a:2", "b:1")
            ],
        )
        connection.commit()
        yield connection


def search(connection, term):
    return {
        row[0]
        for row in connection.execute(
            "SELECT evidence_id FROM evidence_fts WHERE evidence_fts MATCH ?",
            (term,),
        )
    }


def snapshot(connection):
    return {
        table: sorted(
            tuple(row) for row in connection.execute(f"SELECT * FROM {table}")
        )
        for table in ("sources", "evidence", "evidence_fts", "embedding_cache")
    }


def test_refresh_replaces_searchable_text_and_invalidates_source_embeddings(store):
    replace_source_evidence(store, "source:a", [passage("a:1")])

    assert search(store, "originalword") == set()
    assert search(store, "obsoleteword") == set()
    assert search(store, "replacementword") == {"a:1"}
    assert search(store, "unrelatedword") == {"b:1"}

    assert {
        row[0] for row in store.execute("SELECT evidence_id FROM evidence")
    } == {"a:1", "b:1"}
    assert {
        row[0] for row in store.execute("SELECT evidence_id FROM embedding_cache")
    } == {"b:1"}

    payload = store.execute(
        "SELECT payload_json FROM evidence WHERE evidence_id = 'a:1'"
    ).fetchone()[0]
    assert Evidence.model_validate_json(payload).text == "replacementword"


def test_empty_snapshot_removes_only_that_sources_passages(store):
    replace_source_evidence(store, "source:a", [])

    assert search(store, "originalword") == set()
    assert search(store, "obsoleteword") == set()
    assert search(store, "unrelatedword") == {"b:1"}
    assert {
        row[0] for row in store.execute("SELECT evidence_id FROM evidence")
    } == {"b:1"}
    assert {
        row[0] for row in store.execute("SELECT evidence_id FROM embedding_cache")
    } == {"b:1"}
    assert store.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 2


@pytest.mark.parametrize(
    "replacement",
    [
        [passage("new:1"), passage("new:1")],
        [
            passage("new:1", locator="same-location"),
            passage("new:2", locator="same-location"),
        ],
        [passage("new:1"), passage("b:1")],
    ],
    ids=["duplicate-id", "duplicate-locator", "other-source-id-collision"],
)
def test_failed_replacement_restores_rows_search_and_embeddings(store, replacement):
    before = snapshot(store)

    with pytest.raises(sqlite3.IntegrityError):
        replace_source_evidence(store, "source:a", replacement)

    assert snapshot(store) == before
    assert search(store, "originalword") == {"a:1"}
    assert search(store, "obsoleteword") == {"a:2"}
    assert search(store, "replacementword") == set()


@pytest.mark.parametrize(
    "source_id,replacement",
    [
        ("source:a", [passage("new:1", source="source:b")]),
        ("source:missing", [passage("new:1", source="source:missing")]),
    ],
    ids=["wrong-source", "unknown-source"],
)
def test_invalid_source_leaves_store_unchanged(store, source_id, replacement):
    before = snapshot(store)

    with pytest.raises(ValueError):
        replace_source_evidence(store, source_id, replacement)

    assert snapshot(store) == before


def test_replacement_respects_caller_transaction_rollback(store):
    before = snapshot(store)
    store.execute("BEGIN")

    replace_source_evidence(store, "source:a", [passage("a:1")])
    assert search(store, "replacementword") == {"a:1"}

    store.rollback()

    assert snapshot(store) == before
    assert search(store, "originalword") == {"a:1"}
    assert search(store, "replacementword") == set()
