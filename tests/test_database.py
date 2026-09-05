import pytest

from decidr.database import (
    connect,
    activate_frozen_portfolio_version,
    initialise_database,
    save_claim,
    save_link,
    save_versioned_claim_amendment,
)
from decidr.models import AtomicClaim, ClaimEvidenceLink, EvidenceRelationship


def test_database_initialisation_is_idempotent(tmp_path):
    database_path = tmp_path / "ledger.sqlite3"

    initialise_database(database_path)
    initialise_database(database_path)

    with connect(database_path) as connection:
        version = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

    assert version == 5
    assert {"sources", "evidence", "claims", "claim_versions", "rule_traces", "audit_events"} <= tables


def test_reviewer_links_are_stored_independently(tmp_path):
    database_path = tmp_path / "ledger.sqlite3"
    initialise_database(database_path)
    claim = AtomicClaim(
        claim_id="C1",
        subject="discount",
        predicate="requires",
        object="approval",
        claim_type="control",
        claim_text="Discount requires approval.",
    )
    with connect(database_path) as connection:
        save_claim(connection, claim)
        connection.execute(
            "INSERT INTO sources VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            ("S1", "{}", "a" * 64, "test.md", "ingested"),
        )
        connection.execute(
            "INSERT INTO evidence VALUES (?, ?, ?, ?, ?)",
            ("E1", "S1", "heading:test#block:001", "evidence", "{}"),
        )
        for reviewer, relationship in (
            ("reviewer-a", EvidenceRelationship.SUPPORT),
            ("reviewer-b", EvidenceRelationship.CONTRADICT),
        ):
            save_link(
                connection,
                ClaimEvidenceLink(
                    link_id=f"L-{reviewer}",
                    claim_id="C1",
                    evidence_id="E1",
                    relationship=relationship,
                    applicability_reason="Reviewer judgement.",
                    target_match=True,
                    scope_match=True,
                    condition_match=True,
                    temporal_match=True,
                    reviewer=reviewer,
                ),
            )
        rows = connection.execute(
            "SELECT reviewer, relationship FROM claim_evidence_links ORDER BY reviewer"
        ).fetchall()

    assert [tuple(row) for row in rows] == [
        ("reviewer-a", "support"),
        ("reviewer-b", "contradict"),
    ]


def test_frozen_claim_cannot_be_edited_and_requires_versioned_amendment(tmp_path):
    database_path = tmp_path / "ledger.sqlite3"
    initialise_database(database_path)
    frozen = AtomicClaim(
        claim_id="C1",
        subject="discount",
        predicate="requires",
        object="approval",
        claim_type="formal_rule",
        claim_text="Discount requires approval.",
        portfolio_status="approved_and_frozen",
        portfolio_version="1.1-final",
    )
    with connect(database_path) as connection:
        save_claim(connection, frozen)
        with pytest.raises(ValueError, match="is frozen"):
            save_claim(connection, frozen.model_copy(update={"claim_text": "Changed."}))
        amendment = frozen.model_copy(
            update={
                "claim_id": "C1-v1.2",
                "claim_text": "Versioned replacement.",
                "portfolio_status": "versioned_amendment",
                "portfolio_version": "1.2",
                "parent_claim_id": "C1",
            }
        )
        save_versioned_claim_amendment(
            connection,
            "C1",
            amendment,
            reason="New evidence",
            author="Royston",
            affected_claims=["C1"],
            evaluation_validity_impact="Requires a new evaluation version.",
        )
        saved = connection.execute("SELECT claim_id FROM claims ORDER BY claim_id").fetchall()
    assert [row[0] for row in saved] == ["C1", "C1-v1.2"]


def test_approved_portfolio_activation_preserves_prior_version(tmp_path):
    database_path = tmp_path / "ledger.sqlite3"
    initialise_database(database_path)
    old = AtomicClaim(
        claim_id="C1", subject="old", predicate="is", object="rule",
        claim_type="formal_rule", claim_text="Old wording.",
        portfolio_status="approved_and_frozen", portfolio_version="1.1-final",
    )
    new = old.model_copy(
        update={"subject": "new", "claim_text": "New wording.", "portfolio_version": "1.2-final"}
    )
    with connect(database_path) as connection:
        save_claim(connection, old)
        activate_frozen_portfolio_version(
            connection, [new], previous_version="1.1-final",
            reason="Approved metadata normalization", author="Royston",
            evaluation_validity_impact="Supersedes unused reviewer packets; no outcomes existed.",
        )
        versions = connection.execute(
            "SELECT portfolio_version, payload_json FROM claim_versions ORDER BY portfolio_version"
        ).fetchall()
    assert [row[0] for row in versions] == ["1.1-final", "1.2-final"]
    assert "Old wording" in versions[0][1]
    assert "New wording" in versions[1][1]
