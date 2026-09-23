"""Synthetic scope regressions: no formal or held-out evaluation."""

from dataclasses import replace
import hashlib
import json

from decidr.approach_b import BoundedGraphExpander, ConstrainedClaimParser, run_approach_b
from decidr.config import PROJ_ROOT
from decidr.corpus import freeze_compatibility
from decidr.database import connect, initialise_database, upsert_source, upsert_source_evidence
from decidr.graph import build_ledger_graph
from decidr.hybrid import HybridResult
from decidr.ingestion import ingest, write_exports
from decidr.models import Evidence, Source
from decidr.reasoning import assess_claim
from decidr.retrieval import lexical_search
from decidr.semantic import semantic_search

RULE = "A new-business discount of 15% or greater requires written approval from Finance before Closed Won."


def _claim():
    return (
        ConstrainedClaimParser()
        .parse_proposal("Do I need approval for a 15% new-business discount?")
        .claims[0]
        .model_copy(update={"atomicity_status": "confirmed"})
    )


def _seed(connection, release):
    sid = release + ":POL-01"
    source = Source(
        source_id=sid,
        metadata_notes="release=" + release,
        ingestion_status="ingested",
        title="Discount policy",
        original_file_path=f"/{release}/policy.md",
        source_type="policy",
        checksum="a" * 64,
        lifecycle_status="current",
        duplicate_group="same",
        derived_from_source_id="phase1:POL-01" if release == "phase2" else None,
    )
    evidence = Evidence(
        evidence_id=release + "-E",
        source_id=sid,
        text=RULE,
        locator="rule",
        source_type="policy",
        extraction_method="fixture",
    )
    upsert_source(connection, source)
    upsert_source_evidence(connection, sid, [evidence])
    return source, evidence


class LocalEmbedder:
    name = "synthetic-offline"
    version = "1"

    def encode(self, texts):
        return [[1.0, 0.0] for _ in texts]


def test_mixed_ledger_cannot_leak_archived_evidence(tmp_path):
    database = tmp_path / "ledger.sqlite3"
    initialise_database(database)
    with connect(database) as connection:
        _, old = _seed(connection, "phase1")
        _, active = _seed(connection, "phase2")
        lexical = lexical_search(connection, _claim())
        semantic = semantic_search(connection, _claim(), LocalEmbedder())
        assert lexical and semantic
        assert all(item.source_id.startswith("phase2:") for item in lexical + semantic)
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM embedding_cache WHERE evidence_id=?", (old.evidence_id,)
            ).fetchone()[0]
            == 0
        )
        seeds = [
            HybridResult(e.evidence_id, e.source_id, e.locator, e.text, 1, 1.0, 1, None)
            for e in (old, active)
        ]
        expanded = BoundedGraphExpander(connection).expand(_claim(), seeds)
        assert [item["source_id"] for item in expanded] == [active.source_id]
        graph = build_ledger_graph(connection)
        assert old.source_id not in graph and old.evidence_id not in graph
        assert active.evidence_id in graph
        profile = {
            "approach_id": "scope-test",
            "configuration_version": "fixture",
            "embedding_model": "unused",
            "cross_encoder_model": "unused",
        }
        result = run_approach_b(connection, "question", _claim(), profile, "fixture")
        assert result.citations
        assert all(citation["source_id"].startswith("phase2:") for citation in result.citations)
        assert "phase1:" not in json.dumps(result.rules_applied)


def test_archived_evidence_cannot_affect_verdict_or_confidence():
    from test_reasoning import _evidence

    # The same high-credibility record changes authority solely by release purpose.
    from decidr.models import EvidenceRelationship

    item = _evidence("E1", EvidenceRelationship.SUPPORT)
    item = replace(item, source_id="phase1:POL-01")
    result = assess_claim([item])
    empty = assess_claim([])
    assert result.outcome == empty.outcome and result.confidence == empty.confidence
    assert not result.applicable
    assert "framework-development-only" in result.excluded[0][1]


def test_rebuild_preserves_raw_archive_and_reports_purposes(tmp_path):
    roots = {release: tmp_path / release for release in ("phase1", "phase2")}
    for root in roots.values():
        (root / "02_policies").mkdir(parents=True)
        (root / "02_policies/POL-01.md").write_text("# Policy\n\n" + RULE)
    # Independent Phase 2 file with identical content is still a dependent duplicate.
    (roots["phase2"] / "02_policies/POL-02.md").write_text("# Policy\n\n" + RULE)
    before = {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in roots["phase1"].rglob("*")
        if p.is_file()
    }
    database = tmp_path / "active.sqlite3"
    initialise_database(database)
    with connect(database) as connection:
        _seed(connection, "phase1")
    result = ingest(roots, database)
    assert before == {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in roots["phase1"].rglob("*")
        if p.is_file()
    }
    with connect(database) as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sources WHERE source_id NOT LIKE 'phase2:%'"
            ).fetchone()[0]
            == 0
        )
        assert connection.execute("SELECT COUNT(*) FROM evidence_fts").fetchone()[0] == len(
            result.evidence
        )
        assert connection.execute("SELECT COUNT(*) FROM embedding_cache").fetchone()[0] == 0
    assert list((tmp_path / "archive").glob("*.sqlite3"))
    assert len({source.duplicate_group for source in result.sources}) == 1
    assert all(source.duplicate_group for source in result.sources)
    output = tmp_path / "report"
    write_exports(result, output)
    report = (output / "ingestion_report.md").read_text()
    assert "framework-development-only" in report
    assert "active modelling corpus" in report
    assert "active=False" in report and "active=True" in report
    assert all(
        source["source_id"].startswith("phase2:")
        for source in json.loads((output / "source_register.json").read_text())
    )


def test_existing_freezes_are_incompatible_with_phase2_ledger(tmp_path):
    database = tmp_path / "active.sqlite3"
    initialise_database(database)
    with connect(database) as connection:
        _seed(connection, "phase2")
    for version in ("1.1-final", "1.2-final"):
        path = PROJ_ROOT / "framework" / f"portfolio_freeze_manifest_v{version}.json"
        before = path.read_bytes()
        compatible, reason = freeze_compatibility(
            database, {"configuration_version": version}, PROJ_ROOT
        )
        assert not compatible and "controlled new portfolio/freeze version" in reason
        assert path.read_bytes() == before
