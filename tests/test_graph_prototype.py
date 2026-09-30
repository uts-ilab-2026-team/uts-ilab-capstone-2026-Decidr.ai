from datetime import date

from framework.graph_prototype import (
    CONFIG_PATH,
    GRAPH_PATH,
    GraphCredibilityFramework,
    GraphFactsRegister,
    OrganisationalGraph,
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
