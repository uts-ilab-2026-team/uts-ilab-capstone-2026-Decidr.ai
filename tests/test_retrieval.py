from decidr.database import connect
from decidr.ingestion import ingest
from decidr.models import AtomicClaim
from decidr.retrieval import lexical_search


def test_lexical_retrieval_returns_match_reasons(tmp_path):
    release = tmp_path / "release"
    policy = release / "02_policies" / "POL-01.md"
    policy.parent.mkdir(parents=True)
    policy.write_text(
        "# POL-01 — Approval\n\n## Rule\n\nFinance approval is required for discounts.\n",
        encoding="utf-8",
    )
    database = tmp_path / "ledger.sqlite3"
    ingest({"phase2": release}, database)
    claim = AtomicClaim(
        claim_id="C1",
        subject="discount",
        predicate="requires",
        object="finance approval",
        claim_type="control",
        claim_text="Discounts require Finance approval.",
    )

    with connect(database) as connection:
        results = lexical_search(connection, claim)

    assert results
    assert results[0].source_id == "phase2:POL-01"
    assert "approval" in results[0].matched_terms
    assert "FTS5 BM25 match on" in results[0].match_explanation
