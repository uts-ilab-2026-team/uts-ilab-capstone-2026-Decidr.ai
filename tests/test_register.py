import csv
from dataclasses import asdict, replace
from datetime import date
from io import StringIO
import json
from types import SimpleNamespace
from unittest.mock import Mock

from framework.models import EdgeAssessment, FactAssessment
from framework.register import GraphFactsRegister
import pytest

AS_OF = date(2026, 7, 31)


@pytest.fixture
def assessment():
    support = EdgeAssessment(
        edge_id="edge:1",
        document_id="document:1",
        document_title='Policy, "approved"\nRevision α',
        mode="formal",
        attests_value="Written approval is required.",
        stance="support",
        source_class="policy",
        lifecycle_status="active",
        applicable=True,
        materiality_score=0.8,
        material=True,
        dimensions={"authority": 0.9},
        limitations=(),
        trace=("Approval requirement recorded.",),
    )
    excluded = replace(
        support,
        edge_id="edge:2",
        document_id="document:2",
        stance="contradict",
        lifecycle_status="superseded",
        applicable=False,
        materiality_score=None,
        material=False,
        limitations=("Superseded source.",),
        trace=("Excluded by upstream assessment.",),
    )
    observed = replace(
        support,
        edge_id="edge:3",
        mode="observed",
        stance="qualify",
        attests_value="Approval was not recorded.",
        materiality_score=0.3,
        material=False,
        limitations=("Missing records do not prove non-compliance.",),
    )
    return FactAssessment(
        fact_id="fact:example",
        statement='Approval for "special" requests,\nwithin scope α.',
        category="Example process",
        formal_outcome="Supported",
        observed_outcome="Insufficient evidence",
        overall_outcome="Supported",
        confidence="Lower confidence",
        summary="A rule is documented; practice remains unresolved.",
        evidence=(support, excluded, observed),
        gaps=("Practice is not established.",),
        related_qualifiers=("qualifier:1",),
        rules_applied=("rule:applicability", "rule:materiality"),
    )


def make_register(assessment):
    engine = Mock()
    engine.graph.fact_nodes.return_value = [SimpleNamespace(node_id=assessment.fact_id)]
    engine.evaluate_fact.return_value = assessment
    return GraphFactsRegister(engine, as_of=AS_OF), engine


def test_preserves_complete_evidence_and_assessment_context(assessment):
    register, engine = make_register(assessment)
    record = register.get(assessment.fact_id)

    engine.evaluate_fact.assert_called_once_with(assessment.fact_id, as_of=AS_OF)
    assert record.as_of == AS_OF.isoformat()
    assert record.evidence == assessment.evidence
    assert record.rules_applied == assessment.rules_applied
    assert record.gaps == assessment.gaps
    assert record.related_qualifiers == assessment.related_qualifiers
    assert record.derivation_summary == assessment.summary

    # Keep excluded and non-material evidence with its original flags.
    assert record.evidence[1].applicable is False
    assert record.evidence[1].materiality_score is None
    assert record.evidence[2].material is False

    # One document can have multiple distinct evidence edges.
    assert record.documents == ("document:1", "document:2")
    assert len(record.evidence) == 3


@pytest.mark.parametrize(
    "outcome",
    ["Supported", "Contradicted", "Contested", "Insufficient evidence"],
)
def test_preserves_upstream_verdict_and_confidence(assessment, outcome):
    supplied = replace(assessment, overall_outcome=outcome)
    register, _ = make_register(supplied)
    record = register.get(supplied.fact_id)

    assert record.overall_outcome == outcome
    assert record.formal_outcome == supplied.formal_outcome
    assert record.observed_outcome == supplied.observed_outcome
    assert record.confidence == supplied.confidence
    assert "reviewed" not in record.status.lower()


def test_no_evidence_remains_a_candidate(assessment):
    supplied = replace(
        assessment,
        evidence=(),
        formal_outcome="Insufficient evidence",
        observed_outcome="Insufficient evidence",
        overall_outcome="Insufficient evidence",
    )
    register, _ = make_register(supplied)
    record = register.get(supplied.fact_id)

    assert record.status == "Candidate - no evidence"
    assert record.evidence == ()
    assert record.documents == ()
    assert record.formal_values == ()
    assert record.observed_values == ()
    assert record.gaps == supplied.gaps


def test_json_retains_nested_evidence_and_null_scores(assessment):
    register, _ = make_register(assessment)
    rows = json.loads(register.to_json())

    assert len(rows) == 1
    assert rows[0]["statement"] == assessment.statement
    assert rows[0]["as_of"] == AS_OF.isoformat()
    assert rows[0]["rules_applied"] == list(assessment.rules_applied)
    expected = json.loads(json.dumps([asdict(item) for item in assessment.evidence]))
    assert rows[0]["evidence"] == expected
    assert rows[0]["evidence"][1]["materiality_score"] is None


def test_csv_and_json_preserve_the_same_record(assessment):
    register, _ = make_register(assessment)
    expected = json.loads(register.to_json())[0]
    rows = list(csv.DictReader(StringIO(register.to_csv())))

    assert len(rows) == 1
    actual = rows[0]
    for name in (
        "formal_values",
        "observed_values",
        "documents",
        "gaps",
        "related_qualifiers",
        "evidence",
        "rules_applied",
    ):
        actual[name] = json.loads(actual[name])

    assert actual == expected


def test_record_does_not_share_upstream_dimension_dictionary(assessment):
    register, _ = make_register(assessment)
    record = register.get(assessment.fact_id)

    assessment.evidence[0].dimensions["authority"] = 0.1

    assert record.evidence[0].dimensions["authority"] == 0.9


def test_export_dictionary_does_not_mutate_record(assessment):
    register, _ = make_register(assessment)
    record = register.get(assessment.fact_id)
    payload = record.model_dump()

    payload["evidence"][0]["dimensions"]["authority"] = 0.1

    assert record.evidence[0].dimensions["authority"] == 0.9


def test_empty_graph_exports_empty_register(assessment):
    register, engine = make_register(assessment)
    engine.graph.fact_nodes.return_value = []

    assert register.list_records() == []
    assert json.loads(register.to_json()) == []
    reader = csv.DictReader(StringIO(register.to_csv()))
    assert "evidence" in reader.fieldnames
    assert list(reader) == []
    engine.evaluate_fact.assert_not_called()


def test_multiple_facts_keep_their_own_evidence_and_explanations(assessment):
    second = replace(
        assessment,
        fact_id="fact:second",
        statement="A different claim.",
        overall_outcome="Insufficient evidence",
        evidence=(
            replace(
                assessment.evidence[0],
                edge_id="edge:second",
                document_id="document:second",
                attests_value="Evidence for the second claim only.",
            ),
        ),
        gaps=("A separate evidence gap.",),
        rules_applied=("rule:second",),
        related_qualifiers=(),
        summary="Explanation for the second claim.",
    )
    supplied = {
        assessment.fact_id: assessment,
        second.fact_id: second,
    }
    register, engine = make_register(assessment)
    engine.graph.fact_nodes.return_value = [
        SimpleNamespace(node_id=fact_id) for fact_id in supplied
    ]

    def evaluate(fact_id, *, as_of):
        assert as_of == AS_OF
        return supplied[fact_id]

    engine.evaluate_fact.side_effect = evaluate
    records = register.list_records()

    assert len(records) == 2
    for record in records:
        original = supplied[record.fact_id]
        assert record.statement == original.statement
        assert record.evidence == original.evidence
        assert record.gaps == original.gaps
        assert record.rules_applied == original.rules_applied
        assert record.related_qualifiers == original.related_qualifiers
        assert record.derivation_summary == original.summary
        assert record.overall_outcome == original.overall_outcome

    exported = json.loads(register.to_json())
    assert {row["fact_id"] for row in exported} == set(supplied)
    for row in exported:
        original = supplied[row["fact_id"]]
        assert row["evidence"] == json.loads(
            json.dumps([asdict(item) for item in original.evidence])
        )
        assert row["gaps"] == list(original.gaps)
        assert row["rules_applied"] == list(original.rules_applied)


def test_unknown_fact_preserves_upstream_error(assessment):
    register, engine = make_register(assessment)
    error = KeyError("fact:missing")
    engine.evaluate_fact.side_effect = error

    with pytest.raises(KeyError) as caught:
        register.get("fact:missing")

    assert caught.value is error
    engine.evaluate_fact.assert_called_once_with("fact:missing", as_of=AS_OF)


def test_register_fields_survive_api_listing_and_exports(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from framework import CONFIG_PATH, GRAPH_PATH, GraphCredibilityFramework

    from decidr.api.app import app

    # Use a temporary authentication database, not the user's database.
    monkeypatch.setenv("DECIDR_AUTH_DB", str(tmp_path / "users.db"))
    framework = GraphCredibilityFramework.load(GRAPH_PATH, CONFIG_PATH)
    register = GraphFactsRegister(framework, as_of=AS_OF)
    expected = json.loads(register.to_json())
    params = {"as_of": AS_OF.isoformat()}

    with TestClient(app) as client:
        signup = client.post(
            "/api/auth/signup",
            json={
                "name": "Register Test",
                "email": "register-test@example.com",
                "password": "temporary-test-password",
            },
        )
        assert signup.status_code == 201

        listing = client.get("/api/claims", params=params)
        assert listing.status_code == 200
        assert listing.json()["claims"] == expected

        json_response = client.get("/api/register.json", params=params)
        assert json_response.status_code == 200
        assert json_response.json() == expected

        csv_response = client.get("/api/register.csv", params=params)
        assert csv_response.status_code == 200
        assert csv_response.headers["content-type"].startswith("text/csv")

    rows = list(csv.DictReader(StringIO(csv_response.text)))
    for row in rows:
        for name in (
            "formal_values",
            "observed_values",
            "documents",
            "gaps",
            "related_qualifiers",
            "evidence",
            "rules_applied",
        ):
            row[name] = json.loads(row[name])

    assert rows == expected
    assert expected
    assert all(row["as_of"] == AS_OF.isoformat() for row in expected)
    assert any(row["rules_applied"] for row in expected)
    assert any(item["material"] is False for row in expected for item in row["evidence"])
