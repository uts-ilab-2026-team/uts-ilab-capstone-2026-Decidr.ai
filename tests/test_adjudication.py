import pytest
from pydantic import ValidationError

from decidr.database import connect, initialise_database, save_adjudication, save_claim
from decidr.models import Adjudication, AtomicClaim, ClaimOutcome


def test_adjudication_can_preserve_genuine_disagreement(tmp_path):
    database = tmp_path / "ledger.sqlite3"
    initialise_database(database)
    claim = AtomicClaim(
        claim_id="C1",
        subject="discount",
        predicate="requires",
        object="approval",
        claim_type="control",
        claim_text="Discount requires approval.",
    )
    item = Adjudication(
        adjudication_id="A1",
        claim_id="C1",
        reviewer_a="reviewer-a",
        reviewer_b="reviewer-b",
        adjudicator="reviewer-c",
        preserve_disagreement=True,
        rationale="The source interpretation remains genuinely unresolved.",
    )
    with connect(database) as connection:
        save_claim(connection, claim)
        save_adjudication(connection, item)
        row = connection.execute(
            "SELECT preserve_disagreement, final_outcome FROM adjudications"
        ).fetchone()

    assert tuple(row) == (1, None)


def test_resolved_adjudication_requires_final_outcome():
    with pytest.raises(ValidationError):
        Adjudication(
            adjudication_id="A1",
            claim_id="C1",
            reviewer_a="reviewer-a",
            reviewer_b="reviewer-b",
            adjudicator="reviewer-c",
            preserve_disagreement=False,
            rationale="Resolved.",
        )


def test_preserved_disagreement_rejects_forced_outcome():
    with pytest.raises(ValidationError):
        Adjudication(
            adjudication_id="A1",
            claim_id="C1",
            reviewer_a="reviewer-a",
            reviewer_b="reviewer-b",
            adjudicator="reviewer-c",
            preserve_disagreement=True,
            final_outcome=ClaimOutcome.CONTESTED,
            rationale="Still unresolved.",
        )
