"""Integration checks for corpus ingestion and retrieval storage."""

from contextlib import closing
import sqlite3

import pytest

from decidr import ingestion


def snapshot(database):
    with closing(sqlite3.connect(database)) as connection:
        return {
            table: connection.execute(
                f"SELECT * FROM {table} ORDER BY 1"
            ).fetchall()
            for table in ("sources", "evidence", "evidence_fts", "embedding_cache")
        }


def search(database, term):
    with closing(sqlite3.connect(database)) as connection:
        return connection.execute(
            "SELECT evidence_id FROM evidence_fts WHERE evidence_fts MATCH ?",
            (term,),
        ).fetchall()


@pytest.fixture
def corpus(tmp_path):
    root = tmp_path / "corpus"
    policies = root / "02_policies"
    policies.mkdir(parents=True)
    first = policies / "POL-01.md"
    second = policies / "POL-02.md"
    first.write_text(
        "# POL-01\n\noriginalword\n\nobsoleteword\n",
        encoding="utf-8",
    )
    second.write_text("# POL-02\n\nunrelatedword\n", encoding="utf-8")
    database = tmp_path / "retrieval.sqlite"
    ingestion.ingest({"phase2": root}, database_path=database)
    return root, first, second, database


def test_reimport_replaces_passages_without_duplicates(corpus):
    root, first, _, database = corpus

    ingestion.ingest({"phase2": root}, database_path=database)
    assert len(snapshot(database)["evidence"]) == 3

    first.write_text("# POL-01\n\nreplacementword\n", encoding="utf-8")
    ingestion.ingest({"phase2": root}, database_path=database)

    assert not search(database, "originalword")
    assert not search(database, "obsoleteword")
    assert len(search(database, "replacementword")) == 1
    assert len(search(database, "unrelatedword")) == 1
    saved = snapshot(database)
    assert len(saved["evidence"]) == len(saved["evidence_fts"]) == 2


def test_successfully_extracted_empty_source_clears_old_passages(corpus):
    root, first, _, database = corpus
    first.write_text("# POL-01\n", encoding="utf-8")

    ingestion.ingest({"phase2": root}, database_path=database)

    assert not search(database, "originalword")
    assert not search(database, "obsoleteword")
    assert len(search(database, "unrelatedword")) == 1
    assert len(snapshot(database)["sources"]) == 2


def test_missing_release_preserves_entire_index(corpus):
    root, first, _, database = corpus
    before = snapshot(database)
    first.write_text("# POL-01\n\nreplacementword\n", encoding="utf-8")

    with pytest.raises(ValueError, match="incomplete"):
        ingestion.ingest(
            {"phase2": root, "missing": root / "does-not-exist"},
            database_path=database,
        )

    assert snapshot(database) == before


def test_extraction_failure_preserves_entire_index(corpus, monkeypatch):
    root, first, second, database = corpus
    before = snapshot(database)
    first.write_text("# POL-01\n\nreplacementword\n", encoding="utf-8")
    original = ingestion.extract_markdown

    def fail_second(source, path):
        if path == second:
            raise ValueError("Simulated extraction failure")
        return original(source, path)

    monkeypatch.setattr(ingestion, "extract_markdown", fail_second)

    with pytest.raises(ValueError, match="Simulated extraction failure"):
        ingestion.ingest({"phase2": root}, database_path=database)

    assert snapshot(database) == before


def test_storage_failure_rolls_back_all_source_updates(corpus, monkeypatch):
    root, first, _, database = corpus
    before = snapshot(database)
    first.write_text("# POL-01\n\nreplacementword\n", encoding="utf-8")
    original = ingestion.replace_source_evidence
    calls = 0

    def fail_second(connection, source_id, evidence):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise sqlite3.IntegrityError("Simulated storage failure")
        return original(connection, source_id, evidence)

    monkeypatch.setattr(ingestion, "replace_source_evidence", fail_second)

    with pytest.raises(sqlite3.IntegrityError, match="Simulated storage failure"):
        ingestion.ingest({"phase2": root}, database_path=database)

    assert calls == 2
    assert snapshot(database) == before


@pytest.mark.parametrize("separator", ["---", "***", "___", "- - -", "* * *", "_ _ _"])
def test_markdown_separators_are_not_evidence(corpus, separator):
    root, first, _, _ = corpus
    first.write_text(
        f"# POL-01\n\nFirst requirement.\n\n{separator}\n\nSecond requirement.\n",
        encoding="utf-8",
    )

    result = ingestion.ingest({"phase2": root})
    passages = [
        item.text for item in result.evidence
        if item.source_id == "phase2:POL-01"
    ]

    assert passages == ["First requirement.", "Second requirement."]


def test_separator_filter_preserves_content_and_fenced_code(corpus):
    root, first, _, _ = corpus
    blocks = [
        "A requirement -- with punctuation.",
        "```\n---\n```",
        "| Item | Value |\n| --- | --- |\n| Limit | 10 |",
    ]
    first.write_text(
        "# POL-01\n\n" + "\n\n".join(blocks) + "\n",
        encoding="utf-8",
    )

    result = ingestion.ingest({"phase2": root})
    passages = [
        item.text for item in result.evidence
        if item.source_id == "phase2:POL-01"
    ]

    assert passages == blocks
