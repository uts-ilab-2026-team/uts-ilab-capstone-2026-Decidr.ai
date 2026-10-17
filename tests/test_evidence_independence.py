"""Repeated evidence must not change the balance of independent origins."""

from dataclasses import replace
from datetime import date
import json

from decidr.graph import CONFIG_PATH, GraphCredibilityFramework, GraphFactsRegister
from decidr.graph.config import GraphCredibilityConfig
from decidr.graph.graph import OrganisationalGraph
from decidr.graph.models import GraphEdge, GraphNode
import pytest

AS_OF = date(2026, 7, 31)
FACT_ID = "fact:duplicate-check"


def make_register(
    mode,
    repeated_agrees,
    copies,
    same_document,
    *,
    independent=False,
    include_opposing=True,
):
    nodes = {
        FACT_ID: GraphNode(
            node_id=FACT_ID,
            kind="fact",
            label="Approval is required.",
            attributes={},
        )
    }
    edges = []
    sources = [
        (
            "repeated" if same_document else f"copy-{index}",
            repeated_agrees,
            f"origin:copy-{index}" if independent else "origin:repeated",
        )
        for index in range(copies)
    ]
    if include_opposing:
        sources.append(("opposing", not repeated_agrees, "origin:opposing"))

    for index, (name, agrees, origin) in enumerate(sources):
        document_id = f"document:{name}"
        nodes[document_id] = GraphNode(
            node_id=document_id,
            kind="document",
            label=name,
            attributes={
                "source_class": "approved_policy",
                "approval_status": "approved",
                "status": "current",
                "effective_date": "2026-07-01",
                "duplicate_group": origin,
            },
        )
        edges.append(
            GraphEdge(
                edge_id=f"edge:{index}",
                source=document_id,
                target=FACT_ID,
                relationship=mode,
                attributes={
                    "attests_value": (
                        "Approval is required." if agrees else "Approval is not required."
                    ),
                    "agrees": agrees,
                    "independence_verified": True,
                    "independence_basis": "Synthetic origins stipulated independent of other groups.",
                    "directness": 1.0,
                    "specificity": 1.0,
                    "completeness": 1.0,
                },
            )
        )

    graph = OrganisationalGraph(list(nodes.values()), edges, version="duplicate-check")
    engine = GraphCredibilityFramework(graph, GraphCredibilityConfig.load(CONFIG_PATH))
    return GraphFactsRegister(engine, as_of=AS_OF)


@pytest.mark.parametrize("mode", ["FORMAL", "OBSERVED"])
@pytest.mark.parametrize("repeated_agrees", [True, False], ids=["support", "contradict"])
@pytest.mark.parametrize(
    "same_document", [False, True], ids=["copied-documents", "repeated-edges"]
)
def test_repetition_preserves_contested_verdict(mode, repeated_agrees, same_document):
    baseline = make_register(mode, repeated_agrees, 1, same_document).get(FACT_ID)
    register = make_register(mode, repeated_agrees, 4, same_document)
    repeated = register.get(FACT_ID)

    assert baseline.overall_outcome == "Contested"
    assert len(repeated.evidence) == 5
    exported = json.loads(register.to_json())[0]
    assert len(exported["evidence"]) == 5
    assert {item["edge_id"] for item in exported["evidence"]} == {
        f"edge:{index}" for index in range(5)
    }
    assert repeated.overall_outcome == baseline.overall_outcome


@pytest.mark.parametrize("mode", ["FORMAL", "OBSERVED"])
@pytest.mark.parametrize("repeated_agrees", [True, False])
def test_independent_origins_can_change_the_balance(mode, repeated_agrees):
    copied = make_register(mode, repeated_agrees, 4, False).get(FACT_ID)
    independent = make_register(mode, repeated_agrees, 4, False, independent=True).get(FACT_ID)

    assert copied.overall_outcome == "Contested"
    expected = "Supported" if repeated_agrees else "Contradicted"
    assert independent.overall_outcome == expected
    assert len(copied.evidence) == len(independent.evidence) == 5


@pytest.mark.parametrize("mode", ["FORMAL", "OBSERVED"])
@pytest.mark.parametrize("same_document", [False, True])
def test_repetition_preserves_source_quality(mode, same_document):
    baseline = make_register(mode, True, 1, same_document).get(FACT_ID)
    repeated = make_register(mode, True, 4, same_document).get(FACT_ID)
    original = next(item for item in baseline.evidence if item.stance == "support")
    copies = [item for item in repeated.evidence if item.stance == "support"]

    assert len(copies) == 4
    for item in copies:
        assert item.materiality_score == pytest.approx(original.materiality_score)
        assert item.material == original.material
        assert item.dimensions == original.dimensions


@pytest.mark.parametrize(
    "copies,independent,expected",
    [
        (1, False, "Moderate confidence"),
        (4, False, "Moderate confidence"),
        (4, True, "Higher confidence"),
    ],
    ids=["single-origin", "copied-origin", "independent-origins"],
)
def test_confidence_counts_origins(copies, independent, expected):
    register = make_register(
        "FORMAL",
        True,
        copies,
        False,
        independent=independent,
        include_opposing=False,
    )
    graph = register.framework.graph
    formal_edges = list(graph.edges.values())
    observed_edges = [
        replace(
            edge,
            edge_id=f"{edge.edge_id}:observed",
            relationship="OBSERVED",
        )
        for edge in formal_edges
    ]
    graph = OrganisationalGraph(
        list(graph.nodes.values()),
        formal_edges + observed_edges,
        version="confidence-check",
    )
    engine = GraphCredibilityFramework(graph, register.framework.config)
    record = GraphFactsRegister(engine, as_of=AS_OF).get(FACT_ID)

    assert record.formal_outcome == "Supported"
    assert record.observed_outcome == "Supported"
    assert record.overall_outcome == "Supported"
    assert record.gaps == ()
    assert record.confidence == expected
    assert len(record.evidence) == copies * 2


@pytest.mark.parametrize("mode", ["FORMAL", "OBSERVED"])
@pytest.mark.parametrize(
    "status,approval,can_corroborate",
    [
        ("current", "approved", True),
        ("superseded", "superseded", False),
        ("superseded", "approved", False),
        ("current", "superseded", False),
    ],
    ids=["current-control", "both-superseded", "lifecycle-only", "approval-only"],
)
def test_superseded_source_corroboration(mode, status, approval, can_corroborate):
    register = make_register(mode, True, 1, False, include_opposing=False)
    baseline = register.get(FACT_ID)
    graph = register.framework.graph
    original_edge = next(iter(graph.edges.values()))
    original_document = graph.document(original_edge.source)

    extra_document = replace(
        original_document,
        node_id="document:additional",
        label="Additional source",
        attributes={
            **original_document.attributes,
            "duplicate_group": "origin:additional",
            "status": status,
            "approval_status": approval,
        },
    )
    extra_edge = replace(
        original_edge,
        edge_id="edge:additional",
        source=extra_document.node_id,
    )
    graph = OrganisationalGraph(
        [*graph.nodes.values(), extra_document],
        [*graph.edges.values(), extra_edge],
        version="lifecycle-check",
    )
    engine = GraphCredibilityFramework(graph, register.framework.config)
    expanded = GraphFactsRegister(engine, as_of=AS_OF)
    result = expanded.get(FACT_ID)
    original = next(item for item in result.evidence if item.edge_id == original_edge.edge_id)
    extra = next(item for item in result.evidence if item.edge_id == extra_edge.edge_id)

    assert len(result.evidence) == 2
    exported = json.loads(expanded.to_json())[0]
    assert {item["edge_id"] for item in exported["evidence"]} == {
        original_edge.edge_id,
        extra_edge.edge_id,
    }
    assert extra.lifecycle_status == status

    before = baseline.evidence[0]
    if can_corroborate:
        assert original.dimensions["corroboration"] > before.dimensions["corroboration"]
        assert extra.material is True
    else:
        assert original.dimensions == before.dimensions
        assert original.materiality_score == pytest.approx(before.materiality_score)
        assert any("excluded from corroboration counts" in reason for reason in extra.limitations)
