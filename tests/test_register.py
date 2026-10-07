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
