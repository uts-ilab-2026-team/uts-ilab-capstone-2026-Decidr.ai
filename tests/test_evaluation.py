import json

from decidr.challenges import run_challenges
from decidr.database import connect, initialise_database, save_claim, save_evaluation_error
from decidr.evaluate import build_evaluation, write_evaluation
from decidr.evaluation import outcome_metrics, retrieval_metrics, traceability_check
from decidr.models import AtomicClaim, ClaimOutcome, EvaluationError


def test_incomplete_retrieval_pool_withholds_precision_recall_f1():
    result = retrieval_metrics({"E1", "E2"}, {"E1", "E3"}, pool_complete=False)

    assert result.relevant_applicable_found == 1
    assert result.irrelevant_returned == 1
    assert result.material_missed == 1
    assert result.precision is result.recall is result.f1 is None
    assert "withheld" in result.limitation


def test_complete_retrieval_pool_calculates_metrics():
    result = retrieval_metrics({"E1", "E2"}, {"E1", "E3"}, pool_complete=True)

    assert result.precision == 0.5
    assert result.recall == 0.5
    assert result.f1 == 0.5


def test_outcome_metrics_are_per_claim_and_confusion_based():
    result = outcome_metrics(
        {"C1": ClaimOutcome.SUPPORTED, "C2": ClaimOutcome.CONTESTED},
        {"C1": ClaimOutcome.SUPPORTED, "C2": ClaimOutcome.CONTRADICTED, "C3": ClaimOutcome.SUPPORTED},
    )

    assert result.evaluated_claims == 2
    assert result.agreement_rate == 0.5
    assert result.disagreements == ("C2",)
    assert result.confusion_matrix["Contested"]["Contradicted"] == 1


def test_traceability_check_reports_missing_reconstruction_fields():
    result = traceability_check(
        [{"evidence_id": "E1", "source_id": "S1", "locator": "section:one"}]
    )

    assert result["faithful"] is False
    assert "provenance" in result["missing_fields"]["E1"]


def test_all_ten_challenges_pass_and_are_labelled_synthetic():
    results = run_challenges()

    assert len(results) == 10
    assert all(item.passed for item in results)
    assert all(item.fixture_type == "synthetic_behavioral_fixture" for item in results)


def test_empty_reference_evaluation_does_not_fabricate_results(tmp_path):
    database = tmp_path / "ledger.sqlite3"
    initialise_database(database)
    report = build_evaluation(database)
    output = tmp_path / "evaluation"
    write_evaluation(report, output)

    assert report["research_results"]["adjudicated_reference_count"] == 0
    assert report["research_results"]["outcome_evaluation"]["agreement_rate"] is None
    assert report["challenge_results_are_research_performance"] is False
    exported = json.loads((output / "evaluation_results.json").read_text(encoding="utf-8"))
    assert exported["research_results"]["limitation"].startswith("No resolved")


def test_per_claim_error_taxonomy_record_is_persisted(tmp_path):
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
    error = EvaluationError(
        error_id="ERR-1",
        claim_id="C1",
        category="temporal_error",
        component="reasoning",
        description="A superseded source was initially treated as current.",
        reviewer="reviewer-a",
    )
    with connect(database) as connection:
        save_claim(connection, claim)
        save_evaluation_error(connection, error)
        row = connection.execute(
            "SELECT claim_id, category FROM evaluation_errors WHERE error_id='ERR-1'"
        ).fetchone()

    assert tuple(row) == ("C1", "temporal_error")
