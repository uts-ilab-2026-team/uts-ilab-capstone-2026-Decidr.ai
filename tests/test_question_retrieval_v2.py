"""Retrieval-first Stage 2A tests; all semantic components are synthetic and local."""

import hashlib

from decidr.database import connect, initialise_database, upsert_source, upsert_source_evidence
from decidr.models import Evidence, Source
from decidr.question_retrieval import (
    RawQuestionRetriever,
    RetrievedContextLimits,
    build_retrieved_context,
)
from decidr.retrieval import SearchQuery, lexical_text_search
from decidr.semantic import semantic_text_search


def seed(connection, identifier, release, text, *, path=None):
    source = Source(
        source_id=identifier,
        title=f"Source {identifier}",
        original_file_path=path or f"/private/never/{identifier}.md",
        source_type="policy",
        lifecycle_status="current",
        ingestion_status="ingested",
        checksum=hashlib.sha256(identifier.encode()).hexdigest(),
        metadata_notes=f"release={release}; arbitrary=must-not-be-exposed",
    )
    evidence = Evidence(
        evidence_id=f"E-{identifier}",
        source_id=identifier,
        locator="section:one",
        text=text,
        source_type="policy",
        extraction_method="synthetic",
        structured_metadata={"release": release, "secret": "not model visible"},
    )
    upsert_source(connection, source)
    upsert_source_evidence(connection, identifier, [evidence])
    return evidence


class LocalEmbedder:
    name = "synthetic-local"
    version = "1"

    def encode(self, texts):
        return [[1.0, 0.0] for _ in texts]


def test_neutral_retrieval_uses_release_metadata_not_identifier_prefix(tmp_path):
    database = tmp_path / "ledger.sqlite3"
    initialise_database(database)
    with connect(database) as connection:
        seed(connection, "ACTIVE-WITHOUT-RELEASE-PREFIX", "phase2", "Approval guidance applies.")
        seed(connection, "phase2:MISLEADING", "phase1", "Approval guidance is archived.")
        lexical = lexical_text_search(connection, SearchQuery("approval guidance"))
        semantic = semantic_text_search(
            connection, SearchQuery("approval guidance"), LocalEmbedder()
        )
    assert [item.source_id for item in lexical] == ["ACTIVE-WITHOUT-RELEASE-PREFIX"]
    assert [item.source_id for item in semantic] == ["ACTIVE-WITHOUT-RELEASE-PREFIX"]


def test_semantic_failure_is_recorded_without_removing_lexical_results(tmp_path):
    database = tmp_path / "ledger.sqlite3"
    initialise_database(database)
    with connect(database) as connection:
        seed(connection, "ACTIVE", "phase2", "Approval guidance applies.")

        def unavailable(_model):
            raise RuntimeError("synthetic local embedding failure")

        result = RawQuestionRetriever(
            connection,
            semantic_enabled=True,
            embedder_factory=unavailable,
        ).retrieve("approval guidance")
    assert result.execution_order == ("lexical", "semantic", "fusion")
    assert result.lexical and result.combined
    assert result.semantic == ()
    assert "RuntimeError" in result.component_status["semantic"]
    assert result.combined[0].lexical_rank == 1


def test_context_defaults_bound_and_allowlist_passages(tmp_path):
    database = tmp_path / "ledger.sqlite3"
    initialise_database(database)
    first_sentence = "Approval guidance is available. "
    with connect(database) as connection:
        for index in range(7):
            seed(
                connection,
                f"ACTIVE-{index}",
                "phase2",
                first_sentence + ("approval details continue " * 80),
                path=f"/secret/source-{index}.md",
            )
        run = RawQuestionRetriever(connection).retrieve("approval guidance", limit=20)
        package = build_retrieved_context(connection, run)
    assert len(package.passages) == 5
    assert all(len(item.text) <= 800 for item in package.passages)
    assert package.passage_characters <= 4000
    assert all(item.text.endswith(".") for item in package.passages)
    serialised = package.model_dump_json()
    assert "/secret/" not in serialised
    assert "arbitrary" not in serialised
    assert "must-not-be-exposed" not in serialised
    assert "structured_metadata" not in serialised


def test_context_custom_total_budget_is_enforced(tmp_path):
    database = tmp_path / "ledger.sqlite3"
    initialise_database(database)
    with connect(database) as connection:
        for index in range(3):
            seed(connection, f"SOURCE-{index}", "phase2", "approval " * 100)
        run = RawQuestionRetriever(connection).retrieve("approval")
        package = build_retrieved_context(
            connection,
            run,
            RetrievedContextLimits(
                max_passages=3,
                max_characters_per_passage=200,
                max_total_passage_characters=350,
            ),
        )
    assert len(package.passages) <= 3
    assert all(len(item.text) <= 200 for item in package.passages)
    assert package.passage_characters <= 350
