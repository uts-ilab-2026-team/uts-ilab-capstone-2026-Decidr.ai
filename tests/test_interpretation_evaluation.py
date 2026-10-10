"""Scoring arithmetic and safeguards; not interpreter accuracy tests."""

import pytest

from decidr.interpretation_evaluation import evaluate


def reference(identifier, expected="support", review="provisional"):
    return {
        "case_id": identifier,
        "dataset_version": "synthetic-test-v1",
        "input_sha256": "a" * 64,
        "review_status": review,
        "expected_relationship": expected,
    }


def prediction(identifier, relationship="support", status="classified"):
    return {
        "case_id": identifier,
        "dataset_version": "synthetic-test-v1",
        "input_sha256": "a" * 64,
        "method_version": "synthetic-output-v1",
        "status": status,
        "relationship": relationship,
    }


def test_distinguishes_errors_abstentions_and_relationship_failures():
    refs = [
        reference("match"),
        reference("reverse"),
        reference("false", "qualify"),
        reference("missed"),
        reference("abstain"),
        reference("error"),
        reference("missing"),
    ]
    outputs = [
        prediction("match"),
        prediction("reverse", "contradict"),
        prediction("false"),
        prediction("missed", "context"),
        prediction("abstain", None, "abstained"),
        prediction("error", None, "error"),
    ]
    result = evaluate(refs, outputs)["cohorts"]["provisional"]
    assert result["cases"] == 7
    assert result["classified"] == 4
    assert result["matches"] == 1
    assert result["support_contradiction_reversals"] == 1
    assert result["false_decisive"] == 1
    assert result["missed_decisive"] == 4
    assert result["abstained"] == 1
    assert result["errors"] == 1
    assert result["missing_outputs"] == 1
    assert result["coverage"] == pytest.approx(4 / 7)
    assert result["matches_per_case"] == pytest.approx(1 / 7)


def test_reference_review_states_are_not_pooled():
    refs = [
        reference("p"),
        reference("a", review="adjudicated"),
        reference("u", None, "unresolved"),
    ]
    outputs = [
        prediction("p"),
        prediction("a", "contradict"),
        prediction("u"),
    ]
    cohorts = evaluate(refs, outputs)["cohorts"]
    assert cohorts["provisional"]["matches"] == 1
    assert cohorts["adjudicated"]["support_contradiction_reversals"] == 1
    assert cohorts["unresolved"]["classified"] == 1
    assert cohorts["unresolved"]["matches"] is None
    assert cohorts["unresolved"]["false_decisive"] is None


def test_all_abstentions_are_zero_coverage_not_matches():
    result = evaluate(
        [reference("a")], [prediction("a", None, "abstained")]
    )["cohorts"]["provisional"]
    assert result["coverage"] == 0
    assert result["matches_per_case"] == 0


@pytest.mark.parametrize("field,value", [
    ("input_sha256", "b" * 64),
    ("dataset_version", "different-version"),
    ("relationship", "unknown-label"),
    ("status", "unknown-status"),
])
def test_rejects_mismatched_or_malformed_predictions(field, value):
    output = prediction("a")
    output[field] = value
    with pytest.raises(ValueError):
        evaluate([reference("a")], [output])


def test_rejects_duplicate_and_unknown_case_ids():
    with pytest.raises(ValueError):
        evaluate([reference("a"), reference("a")], [])
    with pytest.raises(ValueError):
        evaluate([reference("a")], [prediction("a"), prediction("a")])
    with pytest.raises(ValueError):
        evaluate([reference("a")], [prediction("other")])


def test_rejects_mixed_method_versions():
    second = prediction("b")
    second["method_version"] = "another-method"
    with pytest.raises(ValueError):
        evaluate(
            [reference("a"), reference("b")],
            [prediction("a"), second],
        )


def test_error_cannot_carry_a_relationship():
    with pytest.raises(ValueError):
        evaluate([reference("a")], [prediction("a", "support", "error")])


def test_unresolved_reference_cannot_carry_an_expected_label():
    with pytest.raises(ValueError):
        evaluate([reference("a", "support", "unresolved")], [])
