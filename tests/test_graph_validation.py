"""Validate evidence metadata before it reaches credibility scoring."""

from copy import deepcopy
import json

import pytest

from decidr.graph.errors import GraphValidationError
from decidr.graph.graph import OrganisationalGraph
from decidr.graph.models import GraphEdge, GraphNode


@pytest.fixture(params=["FORMAL", "OBSERVED"])
def payload(request):
    return {
        "graph_version": "validation-test",
        "nodes": [
            {
                "id": "fact:test",
                "kind": "fact",
                "label": "Approval requirement",
                "attributes": {},
            },
            {
                "id": "document:test",
                "kind": "document",
                "label": "Test source",
                "attributes": {},
            },
        ],
        "edges": [
            {
                "id": "edge:test",
                "source": "document:test",
                "target": "fact:test",
                "relationship": request.param,
                "attributes": {"attests_value": "Approval is required."},
            }
        ],
    }


def build_graph(payload):
    nodes = [
        GraphNode(
            node_id=item["id"],
            kind=item["kind"],
            label=item["label"],
            attributes=item["attributes"],
        )
        for item in payload["nodes"]
    ]
    edges = [
        GraphEdge(
            edge_id=item["id"],
            source=item["source"],
            target=item["target"],
            relationship=item["relationship"],
            attributes=item["attributes"],
        )
        for item in payload["edges"]
    ]
    return OrganisationalGraph(nodes, edges, version=payload["graph_version"])


def test_optional_metadata_can_be_omitted(payload):
    original = deepcopy(payload)
    graph = build_graph(payload)

    assert len(graph.attestations("fact:test")) == 1
    assert payload == original


@pytest.mark.parametrize("agrees", [True, False, None])
def test_valid_stances_and_boundary_values_are_preserved(payload, agrees):
    attributes = payload["edges"][0]["attributes"]
    attributes.update(
        agrees=agrees,
        applicable=False,
        scope_match=False,
        directness=0,
        specificity=1,
        completeness=0.5,
    )
    payload["nodes"][1]["attributes"].update(
        effective_date="2026-07-31",
        effective_end_date="2026-07-31",
        last_updated="2026-07-01",
    )
    original = deepcopy(payload)
    graph = build_graph(payload)

    assert graph.edges["edge:test"].attributes["agrees"] is agrees
    assert graph.edges["edge:test"].attributes == attributes
    assert payload == original


@pytest.mark.parametrize(
    "field,value",
    [
        ("agrees", 0),
        ("agrees", 1),
        ("agrees", "true"),
        ("attests_value", None),
        ("attests_value", 42),
        ("attests_value", ""),
        ("attests_value", "   "),
        ("applicable", "false"),
        ("applicable", 0),
        ("applicable", None),
        ("scope_match", "false"),
        ("scope_match", 1),
        ("scope_match", None),
    ],
)
def test_invalid_assertions_and_flags_are_rejected(payload, field, value):
    payload["edges"][0]["attributes"][field] = value

    with pytest.raises(GraphValidationError) as caught:
        build_graph(payload)

    assert "edge:test" in str(caught.value)
    assert field in str(caught.value)


@pytest.mark.parametrize(
    "field", ["directness", "specificity", "completeness"]
)
@pytest.mark.parametrize(
    "value", [-0.1, 1.1, float("nan"), float("inf"), True, "0.5", None]
)
def test_invalid_quality_scores_are_rejected(payload, field, value):
    payload["edges"][0]["attributes"][field] = value

    with pytest.raises(GraphValidationError) as caught:
        build_graph(payload)

    assert "edge:test" in str(caught.value)
    assert field in str(caught.value)


@pytest.mark.parametrize(
    "field", ["effective_date", "effective_end_date", "last_updated"]
)
@pytest.mark.parametrize("value", ["2026-02-30", "20260731", "", True])
def test_invalid_document_dates_are_rejected(payload, field, value):
    payload["nodes"][1]["attributes"][field] = value

    with pytest.raises(GraphValidationError) as caught:
        build_graph(payload)

    assert "document:test" in str(caught.value)
    assert field in str(caught.value)


@pytest.mark.parametrize(
    "dates",
    [
        {
            "effective_date": None,
            "effective_end_date": None,
            "last_updated": None,
        },
        {"effective_date": "2026-07-31"},
        {"effective_end_date": "2026-07-31"},
    ],
)
def test_unknown_and_open_ended_dates_are_valid(payload, dates):
    payload["nodes"][1]["attributes"] = dates
    graph = build_graph(payload)

    assert graph.document("document:test").attributes == dates


def test_reversed_effective_period_is_rejected(payload):
    payload["nodes"][1]["attributes"].update(
        effective_date="2026-08-01",
        effective_end_date="2026-07-31",
    )

    with pytest.raises(GraphValidationError, match="effective_end_date"):
        build_graph(payload)


@pytest.mark.parametrize("collection", ["nodes", "edges"])
def test_attributes_must_be_objects(payload, collection):
    payload[collection][0]["attributes"] = []

    with pytest.raises(GraphValidationError, match="attributes must be an object"):
        build_graph(payload)


def test_json_loading_enforces_evidence_validation(payload, tmp_path):
    path = tmp_path / "graph.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert len(OrganisationalGraph.load(path).attestations("fact:test")) == 1

    payload["edges"][0]["attributes"]["agrees"] = 1
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(GraphValidationError, match="agrees"):
        OrganisationalGraph.load(path)


@pytest.mark.parametrize("completeness", [0.0, 1.0])
def test_validated_completeness_reaches_assessment(payload, completeness):
    from datetime import date

    from decidr.graph import CONFIG_PATH, GraphCredibilityFramework
    from decidr.graph.config import GraphCredibilityConfig

    payload["edges"][0]["attributes"]["completeness"] = completeness
    graph = build_graph(payload)
    engine = GraphCredibilityFramework(
        graph, GraphCredibilityConfig.load(CONFIG_PATH)
    )
    assessment = engine.evaluate_fact("fact:test", as_of=date(2026, 7, 31))

    assert len(assessment.evidence) == 1
    assert assessment.evidence[0].dimensions["evidence_completeness"] == completeness
