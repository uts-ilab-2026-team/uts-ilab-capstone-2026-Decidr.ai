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

def _grouping_passage(identifier, *, source="source:a", section="Topic", row=None, paragraph=None):
    from decidr.retrieval_models import Evidence

    return Evidence(
        evidence_id=identifier,
        source_id=source,
        locator=f"record:{identifier}" if row else f"heading:{section}#{identifier}",
        text=f"Original text for {identifier}",
        source_type="audit_log" if row else "policy",
        section=section,
        heading=section,
        paragraph=paragraph if paragraph is not None else int(identifier[-1]),
        row_identifier=row,
        extraction_method="csv_rows_v1" if row else "markdown_heading_blocks_v1",
    )


def _grouping_result(passage, rank):
    from types import SimpleNamespace

    return SimpleNamespace(
        evidence_id=passage.evidence_id,
        source_id=passage.source_id,
        locator=passage.locator,
        text=passage.text,
        rank=rank,
    )


def test_grouping_preserves_citations_and_ranked_matches():
    from decidr.hybrid import group_ranked_evidence

    first = _grouping_passage("a1")
    second = _grouping_passage("a2")
    context = _grouping_passage("a3")
    other = _grouping_passage("b1", source="source:b")
    lead = _grouping_result(second, 1)
    results = [lead, _grouping_result(first, 2), _grouping_result(other, 3)]

    grouped = group_ranked_evidence(
        results, [context, other, second, first], limit=2
    )

    assert len(grouped) == 2
    assert grouped[0].lead_result is lead
    assert grouped[0].matched_evidence_ids == ("a2", "a1")
    assert [item.model_dump() for item in grouped[0].passages] == [
        item.model_dump() for item in (first, second, context)
    ]
    assert grouped[1].matched_evidence_ids == ("b1",)
    assert [item.rank for item in grouped] == [1, 2]
    assert grouped[1].lead_result.rank == 3

    repeated = group_ranked_evidence(
        [lead, *results], [first, second, context, other], limit=2
    )
    assert repeated == grouped

    grouped[0].passages[0].structured_metadata["changed"] = True
    assert first.structured_metadata == {}


def test_grouping_keeps_sections_sources_and_csv_records_separate():
    from decidr.hybrid import group_ranked_evidence

    passages = [
        _grouping_passage("a1", section="Topic > Formal"),
        _grouping_passage("a2", section="Topic > Observed"),
        _grouping_passage("b1", source="source:b", section="Topic > Formal"),
        _grouping_passage("c1", source="source:csv", row="EVENT-1"),
        _grouping_passage("c2", source="source:csv", row="EVENT-2"),
    ]
    results = [
        _grouping_result(item, rank)
        for rank, item in enumerate(passages, start=1)
    ]

    grouped = group_ranked_evidence(results, passages)

    assert len(grouped) == 5
    assert all(len(item.passages) == 1 for item in grouped)
    assert [item.passages[0].evidence_id for item in grouped] == [
        item.evidence_id for item in passages
    ]


def test_grouping_rejects_missing_or_mismatched_citations():
    from decidr.hybrid import group_ranked_evidence

    passage = _grouping_passage("a1")
    result = _grouping_result(passage, 1)

    with pytest.raises(ValueError, match="Missing evidence"):
        group_ranked_evidence([result], [])

    result.text = "Text belonging to a different record"
    with pytest.raises(ValueError, match="does not match evidence"):
        group_ranked_evidence([result], [passage])

def test_record_references_distinguish_identity_link_and_mention():
    from decidr.retrieval import find_record_references

    record = _grouping_passage("a1", row="CASE-731")
    audit = _grouping_passage("b1", source="audit", row="EVENT-812")
    audit.structured_metadata = {"record": {"related_record": "CASE-731"}}
    message = _grouping_passage("c1", source="messages")
    message.text = "No approval record was found for CASE-731."
    unrelated = _grouping_passage("d1", row="CASE-732")
    unrelated.text = "CASE-732 received approval."

    evidence = [record, audit, message, unrelated]
    before = [item.model_dump() for item in evidence]
    references = find_record_references("Was case-731 approved?", evidence)

    assert [
        (item.evidence_id, item.relationship) for item in references
    ] == [
        ("a1", "record_itself"),
        ("b1", "structured_reference"),
        ("c1", "textual_mention"),
    ]
    assert all(item.record_id == "CASE-731" for item in references)
    assert [item.locator for item in references] == [
        record.locator, audit.locator, message.locator
    ]
    assert [item.model_dump() for item in evidence] == before


@pytest.mark.parametrize(
    "text",
    ["CASE-7310", "CASE-731-02", "OTHER-CASE-731", "CASE-731_extra"],
)
def test_record_references_do_not_match_partial_identifiers(text):
    from decidr.retrieval import find_record_references

    passage = _grouping_passage("a1")
    passage.text = text
    assert find_record_references("Check CASE-731", [passage]) == []


def test_record_references_preserve_multiple_targets_and_unknowns():
    from decidr.retrieval import find_record_references

    passage = _grouping_passage("a1")
    passage.text = "CASE-731 and INCIDENT-2026-02 concern different events."

    references = find_record_references(
        "Compare CASE-731 with INCIDENT-2026-02 and CASE-999", [passage]
    )
    assert {item.record_id for item in references} == {
        "CASE-731", "INCIDENT-2026-02"
    }
    assert find_record_references("Was the billing release approved?", [passage]) == []

def test_corpus_search_anchors_to_explicit_record_without_unrelated_policy(corpus_store):
    from decidr.hybrid import search_corpus
    from decidr.retrieval_store import replace_source_evidence

    audit_source = corpus_store.execute(
        "SELECT source_id FROM evidence WHERE locator LIKE '%AUD-9001%'"
    ).fetchone()[0]

    own = _grouping_passage("own1", source=audit_source, row="CASE-731")
    own.text = "Archived record."
    linked = _grouping_passage("linked2", source=audit_source, row="EVENT-812")
    linked.text = "Review completed."
    linked.structured_metadata = {"record": {"related_record": "CASE-731"}}
    unrelated = _grouping_passage("other3", source=audit_source, row="CASE-732")
    unrelated.text = "Separate record."

    replace_source_evidence(corpus_store, audit_source, [own, linked, unrelated])
    before = corpus_store.total_changes
    result = search_corpus(corpus_store, "CASE-731 travel approval", limit=1)

    assert len(result.ranked_groups) == 0
    assert len(result.additional_linked_groups) == 2

    candidates = {item.evidence_id: item for item in result.candidates}
    assert candidates["own1"].retrieval is None
    assert candidates["linked2"].retrieval is None
    assert candidates["own1"].record_references[0].relationship == "record_itself"
    assert candidates["linked2"].record_references[0].relationship == "structured_reference"
    assert "other3" not in candidates

    all_groups = (*result.ranked_groups, *result.additional_linked_groups)
    passages = [item for group in all_groups for item in group.passages]
    assert len(passages) == len({item.evidence_id for item in passages})
    assert next(item for item in passages if item.evidence_id == "linked2") == linked
    assert corpus_store.total_changes == before


def test_corpus_search_groups_before_limit_and_retains_context(corpus_store):
    from decidr.hybrid import search_corpus
    from decidr.retrieval_store import replace_source_evidence

    source_id = "test:POL-91"
    passages = [
        _grouping_passage(f"passage{i}", source=source_id, paragraph=i + 1)
        for i in range(25)
    ]
    for passage in passages:
        passage.text = "Travel approval."

    context = _grouping_passage("context9", source=source_id)
    context.text = "Background only."
    replace_source_evidence(corpus_store, source_id, [*passages, context])

    result = search_corpus(corpus_store, "travel approval", limit=2)

    assert len(result.ranked_groups) == 2
    assert {
        group.lead_result.source_id for group in result.ranked_groups
    } == {"test:POL-91", "test:POL-92"}
    group = next(
        group for group in result.ranked_groups
        if group.lead_result.source_id == source_id
    )
    assert len(group.passages) == 26
    assert "context9" not in group.matched_evidence_ids
    assert any(item.evidence_id == "context9" for item in group.passages)
    assert result.additional_linked_groups == ()


def test_corpus_search_semantic_union_and_reference_deduplication(corpus_store):
    from decidr.hybrid import reciprocal_rank_fusion, search_corpus
    from decidr.semantic import semantic_search_text

    query = "AUD-9001 travel"
    embedder = RecordingEmbedder()
    result = search_corpus(corpus_store, query, limit=10, embedder=embedder)

    expected = reciprocal_rank_fusion(
        lexical_search_text(corpus_store, query, limit=10),
        semantic_search_text(corpus_store, query, embedder, limit=10),
        limit=10,
    )
    assert [item.retrieval for item in result.candidates] == expected
    assert len(result.candidates) == len({
        item.evidence_id for item in result.candidates
    })
    assert result.additional_linked_groups == ()

    linked = [
        item for item in result.candidates if item.record_references
    ]
    assert len(linked) == 1
    assert linked[0].record_references[0].record_id == "AUD-9001"


@pytest.mark.parametrize("query,limit", [("", 8), ("   ", 8), ("travel", 0)])
def test_corpus_search_noop_does_not_encode_or_write(corpus_store, query, limit):
    from decidr.hybrid import search_corpus

    embedder = RecordingEmbedder()
    before = corpus_store.total_changes
    result = search_corpus(corpus_store, query, limit=limit, embedder=embedder)

    assert result.ranked_groups == ()
    assert result.additional_linked_groups == ()
    assert result.candidates == ()
    assert embedder.calls == []
    assert corpus_store.total_changes == before


@pytest.mark.parametrize("query", ["CASE-731 approval", "general approval"])
@pytest.mark.parametrize("limit", [1, 3])
def test_corpus_record_priority_preserves_retrieval(corpus_store, monkeypatch, query, limit):
    import decidr.hybrid as hybrid
    from decidr.retrieval_store import replace_source_evidence

    source = "test:POL-91"
    generic = _grouping_passage("generic1", source=source, section="General")
    lead = _grouping_passage("lead2", source=source, section="Discussion")
    context = _grouping_passage("context3", source=source, section="Discussion")
    context.text = "This discussion concerns CASE-731."
    own = _grouping_passage("own4", source=source, row="CASE-731")
    passages = [generic, lead, context, own]
    replace_source_evidence(corpus_store, source, passages)

    # Deliberately rank unrelated evidence first. The explicit mention occurs
    # in section context, not in the retrieved section lead.
    lexical = [
        _grouping_result(generic, 1),
        _grouping_result(lead, 2),
        _grouping_result(own, 3),
    ]
    monkeypatch.setattr(
        hybrid, "lexical_search_text",
        lambda connection, query, limit: lexical,
    )
    expected_retrieval = hybrid.reciprocal_rank_fusion(lexical, [], limit=10)
    before = corpus_store.total_changes
    result = hybrid.search_corpus(corpus_store, query, limit=limit)

    has_record = "CASE-731" in query
    expected_order = (
        ["lead2", "own4"]
        if has_record else ["generic1", "lead2", "own4"]
    )
    assert [
        group.lead_result.evidence_id for group in result.ranked_groups
    ] == expected_order[:limit]
    assert [group.rank for group in result.ranked_groups] == list(range(1, min(limit, len(expected_order)) + 1))

    # Display priority must not rewrite the underlying ranks or scores.
    assert [
        candidate.retrieval for candidate in result.candidates
        if candidate.retrieval is not None
    ] == expected_retrieval

    expected_additional = ["own4"] if has_record and limit == 1 else []
    assert [
        group.lead_result.evidence_id for group in result.additional_linked_groups
    ] == expected_additional

    displayed = [
        passage
        for group in (*result.ranked_groups, *result.additional_linked_groups)
        for passage in group.passages
    ]
    originals = {passage.evidence_id: passage for passage in passages}
    assert all(passage == originals[passage.evidence_id] for passage in displayed)
    assert len(displayed) == len({passage.evidence_id for passage in displayed})
    if has_record:
        assert any(passage.evidence_id == "context3" for passage in displayed)
    assert corpus_store.total_changes == before


def test_unknown_identifier_does_not_fall_back_to_keyword_matches(corpus_store):
    from decidr.hybrid import search_corpus
    result = search_corpus(corpus_store, "CASE-987654 travel approval", limit=8)
    assert not result.ranked_groups
    assert not result.additional_linked_groups


def test_index_evidence_then_preload_roundtrip(corpus_store, tmp_path):
    """Pre-index embeds once into the persistent cache; preload copies vectors into a retrieval DB."""
    from types import SimpleNamespace

    from decidr.semantic import index_evidence, preload_cached_vectors

    cache = tmp_path / "embedding_cache.sqlite"
    rows = corpus_store.execute(
        "SELECT evidence_id, text_content FROM evidence ORDER BY evidence_id"
    ).fetchall()
    evidence = [SimpleNamespace(evidence_id=row[0], text=row[1]) for row in rows]
    embedder = RecordingEmbedder()

    # First pre-index embeds every passage; a second run is idempotent (nothing re-embedded).
    assert index_evidence(evidence, embedder, cache_path=cache) == len(evidence)
    embedder.calls.clear()
    assert index_evidence(evidence, embedder, cache_path=cache) == 0
    assert embedder.calls == []

    # Preloading copies the stored vectors into the retrieval connection's cache.
    assert preload_cached_vectors(corpus_store, cache_path=cache) == len(evidence)
    cached = corpus_store.execute(
        "SELECT COUNT(*) FROM embedding_cache WHERE model_name=? AND model_version=?",
        (embedder.name, embedder.version),
    ).fetchone()[0]
    assert cached == len(evidence)


def test_preload_missing_cache_is_noop(corpus_store, tmp_path):
    from decidr.semantic import preload_cached_vectors

    assert preload_cached_vectors(corpus_store, cache_path=tmp_path / "absent.sqlite") == 0
