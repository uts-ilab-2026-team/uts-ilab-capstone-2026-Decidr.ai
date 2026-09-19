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
    ingest({"test": release}, database)
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
    assert results[0].source_id == "test:POL-01"
    assert "approval" in results[0].matched_terms
    assert "FTS5 BM25 match on" in results[0].match_explanation


def test_free_text_lexical_search_scans_corpus(tmp_path):
    from decidr.retrieval import lexical_search_text

    release = tmp_path / "release"
    policy = release / "02_policies" / "POL-02.md"
    interview = release / "04_interviews" / "INT-02.md"
    policy.parent.mkdir(parents=True)
    interview.parent.mkdir(parents=True)

    policy.write_text(
        "# POL-02 — Discount Approval\n\n"
        "## Rule\n\n"
        "Discounts above 15% require Finance approval.\n",
        encoding="utf-8",
    )
    interview.write_text(
        "# INT-02 — Sales Interview\n\n"
        "## Notes\n\n"
        "Large discounts are normally sent to Finance before the deal closes.\n",
        encoding="utf-8",
    )

    database = tmp_path / "ledger.sqlite3"
    ingest({"test": release}, database)

    with connect(database) as connection:
        results = lexical_search_text(
            connection,
            "What Finance approval is needed for discounts above 15%?",
            limit=10,
        )

    assert results
    assert any(result.source_id == "test:POL-02" for result in results)


def test_free_text_lexical_search_empty_query_returns_no_results(tmp_path):
    from decidr.retrieval import lexical_search_text

    database = tmp_path / "ledger.sqlite3"
    release = tmp_path / "release"
    release.mkdir()
    ingest({"test": release}, database)

    with connect(database) as connection:
        assert lexical_search_text(connection, "   ") == []
