from datetime import date
import json

import pytest

from framework.graph_prototype import (
    CONFIG_PATH,
    GRAPH_PATH,
    GraphCredibilityFramework,
    GraphFactsRegister,
    OrganisationalGraph,
)
from framework.graph_prototype.core import (
    GraphCredibilityConfig,
    GraphEdge,
    GraphNode,
    GraphValidationError,
)

AS_OF = date(2026, 7, 31)


def framework() -> GraphCredibilityFramework:
    return GraphCredibilityFramework.load(GRAPH_PATH, CONFIG_PATH)


def test_fact_nodes_are_topics_without_values() -> None:
    graph = OrganisationalGraph.load(GRAPH_PATH)
    assert graph.fact_nodes()
    assert all("value" not in fact.attributes for fact in graph.fact_nodes())
    assert all(
        edge.attributes.get("attests_value")
        for edge in graph.edges.values()
        if edge.relationship in {"FORMAL", "OBSERVED"}
    )


def test_discount_fact_separates_formal_and_observed_evidence() -> None:
    result = framework().evaluate_fact("fact:discount-new-business", as_of=AS_OF)
    assert result.formal_outcome == "Supported"
    assert result.observed_outcome == "Supported"
    assert result.overall_outcome == "Supported"
    assert result.confidence == "Moderate confidence"
    superseded = next(item for item in result.evidence if item.document_id.endswith("SUPERSEDED"))
    slack = next(item for item in result.evidence if item.document_id == "document:COMMS-01")
    assert superseded.stance == "contradict"
    assert superseded.material is False
    assert slack.stance == "contradict"
    assert slack.material is False
    assert result.related_qualifiers


def test_missing_signoff_is_gap_not_contradiction() -> None:
    result = framework().evaluate_fact("fact:billing-signoff-2026-02-18", as_of=AS_OF)
    assert result.formal_outcome == "Insufficient evidence"
    assert result.observed_outcome == "Insufficient evidence"
    assert result.overall_outcome == "Insufficient evidence"
    assert result.confidence == "Lower confidence"
    audit = next(item for item in result.evidence if item.document_id == "document:AUD-0111")
    assert audit.stance == "qualify"
    assert any("No linked Head of Engineering" in gap for gap in result.gaps)


def test_local_vector_retrieval_finds_discount_fact() -> None:
    graph = OrganisationalGraph.load(GRAPH_PATH)
    matches = graph.retrieve_facts("Who approves discounts above 15 percent?")
    assert matches[0][0].node_id == "fact:discount-new-business"


def test_graph_facts_register_exports_without_existing_ledger() -> None:
    register = GraphFactsRegister(framework(), as_of=AS_OF)
    records = register.list_records()
    assert len(records) == 3
    assert "fact:billing-signoff-2026-02-18" in register.to_json()
    assert "formal_outcome" in register.to_csv()


def test_duplicate_node_ids_are_rejected() -> None:
    nodes = [
        GraphNode("duplicate", "fact", "Fact", {"statement": "A fact"}),
        GraphNode("duplicate", "document", "Document"),
    ]

    with pytest.raises(GraphValidationError, match="Node IDs must be unique"):
        OrganisationalGraph(nodes, [], version="test")


def test_duplicate_edge_ids_are_rejected() -> None:
    nodes = [
        GraphNode("fact", "fact", "Fact", {"statement": "A fact"}),
        GraphNode("document:a", "document", "Document A"),
        GraphNode("document:b", "document", "Document B"),
    ]
    edges = [
        GraphEdge(
            "duplicate",
            "document:a",
            "fact",
            "FORMAL",
            {"attests_value": "yes", "agrees": True},
        ),
        GraphEdge(
            "duplicate",
            "document:b",
            "fact",
            "FORMAL",
            {"attests_value": "yes", "agrees": True},
        ),
    ]

    with pytest.raises(GraphValidationError, match="Edge IDs must be unique"):
        OrganisationalGraph(nodes, edges, version="test")


def test_malformed_configuration_uses_graph_validation_error(tmp_path) -> None:
    config_path = tmp_path / "malformed.json"
    config_path.write_text(json.dumps({"config_version": "incomplete"}), encoding="utf-8")

    with pytest.raises(
        GraphValidationError,
        match="Invalid graph credibility configuration",
    ):
        GraphCredibilityConfig.load(config_path)


def test_non_applicable_edges_do_not_inflate_evidence_counts() -> None:
    document_attributes = {
        "status": "current",
        "approval_status": "approved",
        "source_class": "approved_policy",
        "effective_date": "2026-01-01",
    }
    nodes = [
        GraphNode("fact", "fact", "Fact", {"statement": "A fact"}),
        GraphNode(
            "document:applicable",
            "document",
            "Applicable document",
            {**document_attributes, "duplicate_group": "origin-a"},
        ),
        GraphNode(
            "document:duplicate",
            "document",
            "Out-of-scope duplicate",
            {**document_attributes, "duplicate_group": "origin-a"},
        ),
        GraphNode(
            "document:other",
            "document",
            "Out-of-scope other origin",
            {**document_attributes, "duplicate_group": "origin-b"},
        ),
    ]
    shared_edge_attributes = {
        "attests_value": "yes",
        "agrees": True,
        "directness": 1.0,
        "specificity": 1.0,
        "completeness": 1.0,
    }
    edges = [
        GraphEdge(
            "edge:applicable",
            "document:applicable",
            "fact",
            "FORMAL",
            {**shared_edge_attributes, "applicable": True, "scope_match": True},
        ),
        GraphEdge(
            "edge:duplicate",
            "document:duplicate",
            "fact",
            "FORMAL",
            {**shared_edge_attributes, "applicable": False, "scope_match": True},
        ),
        GraphEdge(
            "edge:other",
            "document:other",
            "fact",
            "FORMAL",
            {**shared_edge_attributes, "applicable": True, "scope_match": False},
        ),
    ]
    credibility_framework = GraphCredibilityFramework(
        OrganisationalGraph(nodes, edges, version="test"),
        GraphCredibilityConfig.load(CONFIG_PATH),
    )

    result = credibility_framework.evaluate_fact("fact", as_of=AS_OF)
    applicable = next(item for item in result.evidence if item.edge_id == "edge:applicable")
    excluded = [item for item in result.evidence if item.edge_id != "edge:applicable"]

    assert applicable.dimensions["source_independence"] == 1.0
    assert applicable.dimensions["corroboration"] == 0.5
    assert all(item.applicable is False for item in excluded)
