from datetime import date

from framework import (
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

def test_reconciled_policy_metadata():
    graph = OrganisationalGraph.load(GRAPH_PATH)
    expected = (
        ("document:POL-01", "v3.0", "2025-03-01", "current"),
        ("document:POL-02-SUPERSEDED", "v2.1", "2021-06-01", "superseded"),
        ("document:POL-06", "v1.1", "2024-06-01", "current"),
    )
    for document_id, version, effective_date, status in expected:
        document = graph.document(document_id)
        assert version in document.label, document_id
        assert document.attributes["effective_date"] == effective_date, document_id
        assert document.attributes["approval_status"] == "approved", document_id
        assert document.attributes["status"] == status, document_id
        assert "last_updated" not in document.attributes, document_id

    historical = graph.document("document:POL-02-SUPERSEDED")
    assert historical.attributes["effective_end_date"] == "2025-02-28"


def test_reconciled_policy_effective_boundaries():
    engine = framework()
    cases = (
        (
            "fact:discount-new-business", "document:POL-02-SUPERSEDED",
            date(2021, 5, 31), False,
        ),
        (
            "fact:discount-new-business", "document:POL-02-SUPERSEDED",
            date(2021, 6, 1), True,
        ),
        (
            "fact:discount-renewal", "document:POL-06",
            date(2024, 5, 31), False,
        ),
        (
            "fact:discount-renewal", "document:POL-06",
            date(2024, 6, 1), True,
        ),
    )
    for fact_id, document_id, as_of, applicable in cases:
        result = engine.evaluate_fact(fact_id, as_of=as_of)
        evidence = next(
            item for item in result.evidence
            if item.document_id == document_id
        )
        assert evidence.applicable is applicable, (document_id, as_of)
        if applicable:
            assert evidence.materiality_score is not None
        else:
            assert evidence.materiality_score is None
            assert evidence.material is False


def test_renewal_policy_basis_and_no_exceptions_survive_assessment_and_register():
    engine = framework()
    fact_id = "fact:discount-renewal"
    assessment = engine.evaluate_fact(fact_id, as_of=AS_OF)
    record = GraphFactsRegister(engine, as_of=AS_OF).get(fact_id)
    policy = next(
        item for item in assessment.evidence
        if item.document_id == "document:POL-06"
    )

    assert "10 percent off the current contracted rate" in assessment.statement
    assert "no exceptions" in assessment.statement
    assert "10% off the current contracted rate" in policy.attests_value
    assert "no exceptions" in policy.attests_value
    assert "unless separately approved" not in assessment.statement
    assert "unless separately approved" not in policy.attests_value
    assert record.statement == assessment.statement
    assert record.evidence == assessment.evidence
