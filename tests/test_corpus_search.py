from decidr.corpus_search import search_corpus
from decidr.database import connect
from decidr.ingestion import ingest


def test_search_corpus_collapses_exact_phase_duplicates(tmp_path):
    phase1 = tmp_path / "phase1"
    phase2 = tmp_path / "phase2"

    for root in (phase1, phase2):
        path = root / "02_policies" / "POL-01.md"
        path.parent.mkdir(parents=True)
        path.write_text(
            "# POL-01 — Discount Policy\n\n"
            "## Rule\n\n"
            "Discounts above 15% require Finance approval.\n",
            encoding="utf-8",
        )

    interview = phase2 / "04_interviews" / "INT-01.md"
    interview.parent.mkdir(parents=True)
    interview.write_text(
        "# INT-01 — Sales Interview\n\n"
        "Large discounts are sent to Finance before closing.\n",
        encoding="utf-8",
    )

    database = tmp_path / "ledger.sqlite3"
    ingest({"phase1": phase1, "phase2": phase2}, database)

    with connect(database) as connection:
        package = search_corpus(
            connection,
            "Finance approval for discounts above 15%",
            semantic=False,
            limit=10,
        )

    assert package.results
    assert package.duplicate_results_collapsed >= 1

    policy = next(
        result for result in package.results
        if "POL-01" in result.source_id
    )
    assert set(policy.provenance_sources) == {
        "phase1:POL-01",
        "phase2:POL-01",
    }


def test_search_corpus_empty_query_returns_empty_package(tmp_path):
    database = tmp_path / "ledger.sqlite3"
    release = tmp_path / "release"
    release.mkdir()
    ingest({"test": release}, database)

    with connect(database) as connection:
        package = search_corpus(connection, "   ", semantic=False)

    assert package.results == ()
    assert package.candidate_count == 0


def test_query_period_before_year():
    from decidr.corpus_search import parse_query_period

    start, end = parse_query_period(
        "What was the discount approval threshold before 2025?"
    )

    assert start is None
    assert end.isoformat() == "2024-12-31"


def test_search_marks_historical_and_current_policy_periods(tmp_path):
    historical = tmp_path / "historical"
    current = tmp_path / "current"

    old_policy = historical / "02_policies" / "POL-98.md"
    old_policy.parent.mkdir(parents=True)
    old_policy.write_text(
        "# POL-98 — Discount Policy\n\n"
        "- **Effective date:** 2021-06-01\n"
        "- **Superseded date:** 2024-12-31\n\n"
        "## Rule\n\nDiscounts above 10% require approval.\n",
        encoding="utf-8",
    )

    new_policy = current / "02_policies" / "POL-99.md"
    new_policy.parent.mkdir(parents=True)
    new_policy.write_text(
        "# POL-99 — Discount Policy\n\n"
        "- **Effective date:** 2025-01-01\n\n"
        "## Rule\n\nDiscounts above 15% require approval.\n",
        encoding="utf-8",
    )

    database = tmp_path / "ledger.sqlite3"
    ingest(
        {"historical": historical, "current": current},
        database,
    )

    with connect(database) as connection:
        package = search_corpus(
            connection,
            "discount approval threshold before 2025",
            semantic=False,
        )

    statuses = {
        result.source_id: result.temporal_status
        for result in package.results
    }

    assert statuses["historical:POL-98"] == "applicable_to_query_period"
    assert statuses["current:POL-99"] == "outside_query_period"


def test_search_reports_missing_structured_fields(tmp_path):
    release = tmp_path / "release"
    record = release / "07_crm" / "deals.csv"
    record.parent.mkdir(parents=True)
    record.write_text(
        "deal_id,discount_percentage,approval_record\n"
        "DEAL-72,,\n",
        encoding="utf-8",
    )

    database = tmp_path / "ledger.sqlite3"
    ingest({"test": release}, database)

    with connect(database) as connection:
        package = search_corpus(
            connection,
            "DEAL-72 discount approval",
            semantic=False,
        )

    assert package.results
    assert set(package.results[0].missing_fields) == {
        "approval_record",
        "discount_percentage",
    }


def test_temporal_query_prioritises_applicable_sources(tmp_path):
    old_root = tmp_path / "old"
    new_root = tmp_path / "new"

    old = old_root / "02_policies" / "POL-98.md"
    old.parent.mkdir(parents=True)
    old.write_text(
        "# POL-98 — Discount Policy\n\n"
        "- **Effective date:** 2021-01-01\n"
        "- **Superseded date:** 2024-12-31\n\n"
        "Discount approval threshold was 10%.\n",
        encoding="utf-8",
    )

    new = new_root / "02_policies" / "POL-99.md"
    new.parent.mkdir(parents=True)
    new.write_text(
        "# POL-99 — Discount Policy\n\n"
        "- **Effective date:** 2025-01-01\n\n"
        "Discount approval threshold is 15%.\n",
        encoding="utf-8",
    )

    database = tmp_path / "ledger.sqlite3"
    ingest({"old": old_root, "new": new_root}, database)

    with connect(database) as connection:
        package = search_corpus(
            connection,
            "discount approval threshold before 2025",
            semantic=False,
        )

    assert package.results[0].source_id == "old:POL-98"
    assert package.results[0].temporal_status == "applicable_to_query_period"


def test_gap_signals_report_missing_structured_data(tmp_path):
    release = tmp_path / "release"
    crm = release / "07_crm" / "deals.csv"
    crm.parent.mkdir(parents=True)
    crm.write_text(
        "deal_id,discount_percentage,approval_record\n"
        "DEAL-72,,\n",
        encoding="utf-8",
    )

    database = tmp_path / "ledger.sqlite3"
    ingest({"test": release}, database)

    with connect(database) as connection:
        package = search_corpus(
            connection,
            "DEAL-72 discount approval",
            semantic=False,
        )

    assert "structured_fields_missing" in package.gap_signals
