from types import SimpleNamespace

import pytest

from decidr.database import connect, save_claim, save_link
from decidr.graph import build_claim_graph
from decidr.hybrid import reciprocal_rank_fusion
from decidr.ingestion import ingest
from decidr.models import AtomicClaim, ClaimEvidenceLink, EvidenceRelationship
from decidr.semantic import semantic_search


class FakeEmbedder:
    name = "fake-local"
    version = "1.0"
    calls = 0

    def encode(self, texts):
        self.calls += 1
        return [
            [float("approval" in text.casefold()), float("onboarding" in text.casefold())]
            for text in texts
        ]


def _ledger(tmp_path):
    release = tmp_path / "release"
    policies = release / "02_policies"
    policies.mkdir(parents=True)
    (policies / "POL-01.md").write_text(
        "# POL-01 — Discount approval\n\n## Rule\n\nFinance approval is mandatory.\n",
        encoding="utf-8",
    )
    (policies / "POL-02.md").write_text(
        "# POL-02 — Onboarding\n\n## Rule\n\nOnboarding takes six weeks.\n",
        encoding="utf-8",
    )
    database = tmp_path / "ledger.sqlite3"
    result = ingest({"phase2": release}, database)
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
    return database, result, claim


def test_semantic_search_caches_evidence_embeddings(tmp_path):
    database, ingestion_result, claim = _ledger(tmp_path)
    embedder = FakeEmbedder()
    with connect(database) as connection:
        first = semantic_search(connection, claim, embedder)
        first_calls = embedder.calls
        second = semantic_search(connection, claim, embedder)
        cached = connection.execute("SELECT COUNT(*) FROM embedding_cache").fetchone()[0]

    assert first[0].source_id == "phase2:POL-01"
    assert [item.evidence_id for item in first] == [item.evidence_id for item in second]
    assert embedder.calls == first_calls + 1  # second call encodes only the query
    assert cached == len(ingestion_result.evidence)


def test_rrf_deduplicates_and_retains_component_ranks():
    lexical = [SimpleNamespace(evidence_id="E1", source_id="S1", locator="L1", text="a", rank=1)]
    semantic = [
        SimpleNamespace(evidence_id="E1", source_id="S1", locator="L1", text="a", rank=2),
        SimpleNamespace(evidence_id="E2", source_id="S2", locator="L2", text="b", rank=1),
    ]

    results = reciprocal_rank_fusion(lexical, semantic)

    assert [item.evidence_id for item in results] == ["E1", "E2"]
    assert results[0].lexical_rank == 1
    assert results[0].semantic_rank == 2


def test_claim_graph_is_bounded_to_linked_evidence(tmp_path):
    database, result, claim = _ledger(tmp_path)
    evidence = result.evidence[0]
    with connect(database) as connection:
        save_link(
            connection,
            ClaimEvidenceLink(
                link_id="L1",
                claim_id=claim.claim_id,
                evidence_id=evidence.evidence_id,
                relationship=EvidenceRelationship.SUPPORT,
                applicability_reason="Applicable.",
                target_match=True,
                scope_match=True,
                condition_match=True,
                temporal_match=True,
                reviewer="reviewer-a",
            ),
        )
        graph = build_claim_graph(connection, claim.claim_id)

    assert claim.claim_id in graph
    assert evidence.evidence_id in graph
    assert graph.number_of_nodes() == 3
    assert any(data["relationship"] == "SUPPORT" for *_, data in graph.edges(data=True))


def test_rrf_rejects_invalid_constant():
    with pytest.raises(ValueError):
        reciprocal_rank_fusion([], [], k=0)
