import json

from decidr.database import (
    connect,
    initialise_database,
    save_adjudication,
    save_claim_assessment,
)
from decidr.facts_register import FactRecordStatus, FactsRegister
from decidr.models import (
    Adjudication,
    AtomicClaim,
    ClaimAssessment,
    ClaimOutcome,
    ConfidenceLevel,
)


def _claim() -> AtomicClaim:
    return AtomicClaim(
        claim_id="C1",
        subject="discounts above 15%",
        predicate="require",
        object="approval before closing",
        scope="Sales",
        claim_type="formal_rule",
        claim_text="Discounts above 15% require approval before closing.",
    )


def _assessment(reviewer: str, outcome: ClaimOutcome) -> ClaimAssessment:
    return ClaimAssessment(
        assessment_id=f"A-{reviewer}",
        claim_id="C1",
        reviewer=reviewer,
        outcome=outcome,
        confidence=ConfidenceLevel.MODERATE,
        uncertainty_explanation="One source remains to be checked.",
        explanation="The reviewer traced the claim to the available evidence.",
        review_status="complete",
    )


def test_new_register_row_is_a_candidate_not_a_fact(tmp_path):
    database = tmp_path / "ledger.sqlite3"
    initialise_database(database)

    with connect(database) as connection:
        record = FactsRegister(connection).register_candidate(_claim())

    assert record.status == FactRecordStatus.CANDIDATE
    assert record.final_outcome is None
    assert record.is_final_finding is False


def test_single_human_review_is_visible_but_not_promoted_to_final_finding(tmp_path):
    database = tmp_path / "ledger.sqlite3"
    initialise_database(database)

    with connect(database) as connection:
        register = FactsRegister(connection)
        register.register_candidate(_claim())
        save_claim_assessment(
            connection,
            _assessment("reviewer-a", ClaimOutcome.SUPPORTED),
            [],
        )
        record = register.get("C1")

    assert record.status == FactRecordStatus.REVIEWED
    assert record.final_outcome is None
    assert record.independent_human_reviewers == ["reviewer-a"]


def test_resolved_adjudication_creates_assessed_finding(tmp_path):
    database = tmp_path / "ledger.sqlite3"
    initialise_database(database)

    with connect(database) as connection:
        register = FactsRegister(connection)
        register.register_candidate(_claim())
        save_claim_assessment(
            connection,
            _assessment("reviewer-a", ClaimOutcome.SUPPORTED),
            [],
        )
        save_claim_assessment(
            connection,
            _assessment("reviewer-b", ClaimOutcome.CONTESTED),
            [],
        )
        save_adjudication(
            connection,
            Adjudication(
                adjudication_id="ADJ-1",
                claim_id="C1",
                reviewer_a="reviewer-a",
                reviewer_b="reviewer-b",
                adjudicator="lead-reviewer",
                final_outcome=ClaimOutcome.CONTESTED,
                final_confidence=ConfidenceLevel.HIGHER,
                rationale="Independent evidence supports opposing positions.",
            ),
        )
        record = register.get("C1")
        exported = register.to_csv()

    assert record.status == FactRecordStatus.ASSESSED_FINDING
    assert record.final_outcome == ClaimOutcome.CONTESTED
    assert record.final_confidence == ConfidenceLevel.HIGHER
    assert record.finalised_by == "lead-reviewer"
    assert record.is_final_finding is True
    assert "Assessed organisational finding" in exported


def test_missing_evidence_is_exported_from_rule_trace(tmp_path):
    database = tmp_path / "ledger.sqlite3"
    initialise_database(database)

    with connect(database) as connection:
        register = FactsRegister(connection)
        register.register_candidate(_claim())
        save_claim_assessment(
            connection,
            _assessment("automated:reviewer-a", ClaimOutcome.INSUFFICIENT),
            [
                {
                    "rule_id": "R5_MISSINGNESS_IS_A_GAP",
                    "evidence_ids": [],
                    "details": {"gaps": ["Signed approval record is missing."]},
                }
            ],
        )
        record = register.get("C1")
        exported = json.loads(register.to_json())

    assert record.status == FactRecordStatus.REVIEW_IN_PROGRESS
    assert record.evidence_gaps == ["Signed approval record is missing."]
    assert exported[0]["evidence_gaps"] == ["Signed approval record is missing."]
