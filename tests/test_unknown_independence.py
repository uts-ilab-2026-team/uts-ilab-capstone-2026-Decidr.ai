"""Packet-relative independence is a supplied judgement, never an ID heuristic."""

from datetime import date

from framework import CONFIG_PATH, GraphCredibilityFramework
from framework.config import GraphCredibilityConfig
from framework.errors import GraphValidationError
from framework.graph import OrganisationalGraph
from framework.models import GraphEdge, GraphNode
import pytest

DAY = date(2026, 7, 31)


def assess(specs, *, both=False, reverse=False):
    nodes = [GraphNode("fact:test", "fact", "An event occurred")]
    edges = []
    for i, (origin, verified, agrees) in enumerate(specs):
        nodes.append(
            GraphNode(
                f"doc:{i}",
                "document",
                f"Record {i}",
                {
                    "source_class": "system_verified",
                    "approval_status": "system_record",
                    "status": "current",
                    "effective_date": "2026-07-01",
                    "duplicate_group": origin,
                },
            )
        )
        for lane in ["FORMAL", "OBSERVED"] if both else ["OBSERVED"]:
            attrs = {
                "attests_value": "Event account",
                "agrees": agrees,
                "directness": 1.0,
                "specificity": 1.0,
                "completeness": 1.0,
            }
            if verified is not None:
                attrs.update(
                    independence_verified=verified,
                    independence_basis="Synthetic packet-relative judgement",
                )
            edges.append(GraphEdge(f"edge:{i}:{lane}", f"doc:{i}", "fact:test", lane, attrs))
    if reverse:
        nodes.reverse()
        edges.reverse()
    engine = GraphCredibilityFramework(
        OrganisationalGraph(nodes, edges, version="independence-test"),
        GraphCredibilityConfig.load(CONFIG_PATH),
    )
    return engine.evaluate_fact("fact:test", as_of=DAY)


@pytest.mark.parametrize("verified", [None, False])
@pytest.mark.parametrize("agrees", [True, False])
def test_unknown_repetition_cannot_outvote_opposition(verified, agrees):
    one = assess([("a", verified, agrees), ("other", True, not agrees)])
    many = assess([(str(i), verified, agrees) for i in range(20)] + [("other", True, not agrees)])
    assert one.overall_outcome == many.overall_outcome == "Contested"
    assert len(many.evidence) == 21
    assert all(e.dimensions["corroboration"] == 0.5 for e in many.evidence)
    assert all("duplicate" not in " ".join(e.limitations).lower() for e in many.evidence)


def test_unknown_does_not_borrow_verified_corroboration_or_add_weight():
    base = [("a", True, True), ("b", True, True), ("opposition", True, False)]
    before = assess(base)
    after = assess(base + [(f"unknown:{i}", None, True) for i in range(20)])
    assert before.overall_outcome == after.overall_outcome == "Contested"
    by_id = {e.edge_id: e for e in after.evidence}
    for item in before.evidence:
        assert item.materiality_score == by_id[item.edge_id].materiality_score
    unknown = [e for e in after.evidence if int(e.document_id.split(":")[1]) >= 3]
    assert all(e.dimensions["corroboration"] == 0.5 for e in unknown)


def test_established_origins_can_add_weight():
    result = assess([(str(i), True, True) for i in range(4)] + [("opposition", True, False)])
    assert result.overall_outcome == "Supported"


@pytest.mark.parametrize(
    "verified,expected",
    [(None, "Moderate confidence"), (False, "Moderate confidence"), (True, "Higher confidence")],
)
def test_confidence_requires_established_origins(verified, expected):
    result = assess([(str(i), verified, True) for i in range(4)], both=True)
    assert result.confidence == expected


def test_shared_origin_never_becomes_independent_copies():
    single = assess([("a", True, True)], both=True)
    copies = assess([("a", True, True)] * 4, both=True)
    assert single.confidence == copies.confidence == "Moderate confidence"
    assert {e.materiality_score for e in single.evidence} == {
        e.materiality_score for e in copies.evidence
    }


def test_conflicting_group_declarations_are_conservative_and_order_independent():
    specs = [("a", True, True), ("a", False, True), ("b", True, True)]
    forward, backward = assess(specs), assess(specs, reverse=True)
    assert forward == backward
    assert all(e.dimensions["corroboration"] == 0.5 for e in forward.evidence)


@pytest.mark.parametrize(
    "attrs",
    [
        {"independence_verified": "true"},
        {"independence_verified": 1},
        {"independence_verified": True},
        {"independence_verified": True, "independence_basis": "  "},
        {"independence_basis": None},
    ],
)
def test_invalid_independence_judgements_rejected(attrs):
    with pytest.raises(GraphValidationError):
        OrganisationalGraph(
            [GraphNode("d", "document", "D"), GraphNode("f", "fact", "F")],
            [GraphEdge("e", "d", "f", "OBSERVED", {"attests_value": "X", **attrs})],
            version="invalid",
        )
