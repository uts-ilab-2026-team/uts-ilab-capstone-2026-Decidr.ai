"""Free-text retrieval through the integrated corpus store."""

from contextlib import closing
import json

import pytest

from decidr.ingestion import ingest
from decidr.retrieval import lexical_search_text
from decidr.retrieval_store import connect


@pytest.fixture
def corpus_store(tmp_path):
    root = tmp_path / "corpus"
    policies = root / "02_policies"
    audit = root / "09_audit_log"
    policies.mkdir(parents=True)
    audit.mkdir()

    (policies / "POL-91.md").write_text(
        "# POL-91\n\nTravel requires manager approval.\n",
        encoding="utf-8",
    )
    (policies / "POL-92.md").write_text(
        "# POL-92\n\nTravel does not require manager approval.\n",
        encoding="utf-8",
    )
    (audit / "events.csv").write_text(
        "event_id,action,notes\n"
        "AUD-9001,Updated payroll,Reconciliation completed\n"
        "AUD-9002,Updated inventory,Stock counted\n",
        encoding="utf-8",
    )

    database = tmp_path / "retrieval.sqlite"
    ingest({"test": root}, database_path=database)
    with closing(connect(database)) as connection:
        yield connection


def test_opposing_passages_are_both_retrievable(corpus_store):
    query = "Travel requires manager approval"
    changes_before = corpus_store.total_changes

    results = lexical_search_text(corpus_store, query, limit=10)

    assert {item.source_id for item in results} == {"test:POL-91", "test:POL-92"}
    assert any("does not require" in item.text for item in results)
    assert any("Travel requires" in item.text for item in results)
    assert corpus_store.total_changes == changes_before


def test_csv_result_resolves_to_stored_evidence_and_source(corpus_store):
    results = lexical_search_text(corpus_store, "AUD-9001", limit=5)

    assert len(results) == 1
    item = results[0]
    assert "event_id:AUD-9001" in item.locator
    assert json.loads(item.text)["event_id"] == "AUD-9001"

    row = corpus_store.execute(
        """
        SELECT e.payload_json, s.payload_json
        FROM evidence e
        JOIN sources s ON s.source_id = e.source_id
        WHERE e.evidence_id = ?
        """,
        (item.evidence_id,),
    ).fetchone()
    assert row is not None
    evidence, source = map(json.loads, row)
    assert evidence["text"] == item.text
    assert evidence["locator"] == item.locator
    assert source["source_id"] == item.source_id
    assert source["original_file_path"].endswith("events.csv")
    assert len(source["checksum"]) == 64


@pytest.mark.parametrize("query", ["", "   ", "the and of"])
def test_empty_or_stopword_only_query_returns_nothing(corpus_store, query):
    assert lexical_search_text(corpus_store, query) == []


def test_unmatched_query_returns_nothing(corpus_store):
    assert lexical_search_text(corpus_store, "zzzxxyyqq") == []


def test_result_limit_is_respected(corpus_store):
    results = lexical_search_text(corpus_store, "travel approval", limit=1)

    assert len(results) == 1
    assert results[0].rank == 1


class RecordingEmbedder:
    """Predictable test vectors; these do not measure semantic quality."""

    name = "test-embedder"
    version = "1"

    def __init__(self):
        self.calls = []

    def encode(self, texts):
        self.calls.append(list(texts))
        return [
            [1.0, 0.0] if "travel" in text.lower() else [0.0, 1.0]
            for text in texts
        ]


def test_semantic_cache_reuse_and_source_refresh(corpus_store):
    from decidr.retrieval_models import Evidence
    from decidr.retrieval_store import replace_source_evidence
    from decidr.semantic import semantic_search_text

    embedder = RecordingEmbedder()
    query = "travel"
    first = semantic_search_text(corpus_store, query, embedder, limit=10)
    assert len(first) == 4
    assert sum(map(len, embedder.calls)) == 5

    embedder.calls.clear()
    repeated = semantic_search_text(corpus_store, query, embedder, limit=10)
    assert repeated == first
    assert embedder.calls == [[query]]

    payload = corpus_store.execute(
        "SELECT payload_json FROM evidence WHERE source_id = ?",
        ("test:POL-91",),
    ).fetchone()[0]
    old = Evidence.model_validate_json(payload)
    updated = Evidence.model_validate({
        **old.model_dump(),
        "text": "Payroll reconciliation has changed.",
    })
    replace_source_evidence(corpus_store, old.source_id, [updated])

    embedder.calls.clear()
    refreshed = semantic_search_text(corpus_store, query, embedder, limit=10)

    assert embedder.calls == [[query], [updated.text]]
    result = next(item for item in refreshed if item.evidence_id == old.evidence_id)
    assert result.text == updated.text
    assert result.score == pytest.approx(0.0)
    assert corpus_store.execute(
        "SELECT COUNT(*) FROM embedding_cache"
    ).fetchone()[0] == 4


def test_blank_semantic_query_does_not_encode_or_write(corpus_store):
    from decidr.semantic import semantic_search_text

    embedder = RecordingEmbedder()
    before = corpus_store.total_changes

    assert semantic_search_text(corpus_store, "   ", embedder) == []
    assert embedder.calls == []
    assert corpus_store.total_changes == before


def test_fusion_preserves_union_ranks_and_ignores_repeated_ids():
    from types import SimpleNamespace

    from decidr.hybrid import reciprocal_rank_fusion

    def item(identifier, rank):
        return SimpleNamespace(
            evidence_id=identifier,
            source_id=f"source:{identifier}",
            locator=f"section:{identifier}",
            text=f"Passage {identifier}",
            rank=rank,
        )

    lexical = [item("a", 1), item("b", 2)]
    semantic = [item("b", 1), item("c", 2)]

    expected = reciprocal_rank_fusion(lexical, semantic, limit=10)
    repeated = reciprocal_rank_fusion(
        [lexical[0], lexical[0], lexical[1]],
        [semantic[0], semantic[0], semantic[1]],
        limit=10,
    )

    assert repeated == expected
    assert [result.evidence_id for result in expected] == ["b", "a", "c"]
    assert expected[0].lexical_rank == 2
    assert expected[0].semantic_rank == 1
    assert expected[1].semantic_rank is None
    assert expected[2].lexical_rank is None

    lexical_only = reciprocal_rank_fusion(lexical, [], limit=10)
    assert [result.evidence_id for result in lexical_only] == ["a", "b"]
