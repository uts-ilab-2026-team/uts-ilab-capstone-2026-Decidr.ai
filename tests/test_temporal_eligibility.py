"""Temporal eligibility through the real engine and Facts Register."""

from datetime import date
import json

import pytest

from decidr.graph import CONFIG_PATH, GraphCredibilityFramework, GraphFactsRegister
from decidr.graph.config import GraphCredibilityConfig
from decidr.graph.graph import OrganisationalGraph
from decidr.graph.models import GraphEdge, GraphNode


AS_OF = date(2026, 7, 31)
FACT_ID = "fact:temporal-test"


def make_register(mode, documents):
    nodes = [
        GraphNode(
            node_id=FACT_ID,
            kind="fact",
            label="Approval requirement at the assessment date",
        )
    ]
    edges = []

    for index, attributes in enumerate(documents):
        document_id = f"document:{index}"
        nodes.append(
            GraphNode(
                node_id=document_id,
                kind="document",
                label=f"Synthetic source {index}",
                attributes={
                    "source_class": "approved_policy",
                    "approval_status": "approved",
                    "status": "current",
                    **attributes,
                },
            )
        )
        edges.append(
            GraphEdge(
                edge_id=f"edge:{index}",
                source=document_id,
                target=FACT_ID,
                relationship=mode,
                attributes={
                    "attests_value": "Approval is required.",
                    "agrees": True,
                    "applicable": True,
                    "scope_match": True,
                    "directness": 1.0,
                    "specificity": 1.0,
                    "completeness": 1.0,
                },
            )
        )

    graph = OrganisationalGraph(nodes, edges, version="temporal-test")
    config = GraphCredibilityConfig.load(CONFIG_PATH)
    engine = GraphCredibilityFramework(graph, config)
    return GraphFactsRegister(engine, as_of=AS_OF)


@pytest.mark.parametrize("mode", ["FORMAL", "OBSERVED"])
@pytest.mark.parametrize(
    "dates, eligible, reason",
    [
        pytest.param(
            {"effective_date": "2026-07-31"},
            True, None, id="starts-today",
        ),
        pytest.param(
            {
                "effective_date": "2026-07-01",
                "effective_end_date": "2026-07-31",
            },
            True, None, id="ends-today",
        ),
        pytest.param(
            {"effective_date": "2026-08-01"},
            False, "not yet effective", id="starts-tomorrow",
        ),
        pytest.param(
            {
                "effective_date": "2026-07-01",
                "effective_end_date": "2026-07-30",
            },
            False, "no longer effective", id="ended-yesterday",
        ),
    ],
)
def test_effective_period_controls_eligibility(mode, dates, eligible, reason):
    register = make_register(mode, [dates])
    record = register.get(FACT_ID)

    assert len(record.evidence) == 1
    evidence = record.evidence[0]
    assert evidence.applicable is eligible
    assert evidence.material is eligible
    assert record.overall_outcome == (
        "Supported" if eligible else "Insufficient evidence"
    )

    if not eligible:
        assert evidence.materiality_score is None
        assert any(reason in item for item in evidence.limitations)
        assert any(reason in item for item in evidence.trace)

        # Exclusion must survive export without removing the evidence.
        exported = json.loads(register.to_json())[0]
        assert len(exported["evidence"]) == 1
        saved = exported["evidence"][0]
        assert saved["applicable"] is False
        assert saved["material"] is False
        assert saved["materiality_score"] is None
        assert any(reason in item for item in saved["limitations"])


@pytest.mark.parametrize("mode", ["FORMAL", "OBSERVED"])
def test_old_but_still_effective_source_remains_eligible(mode):
    register = make_register(mode, [{"effective_date": "2010-01-01"}])
    evidence = register.get(FACT_ID).evidence[0]

    assert evidence.applicable is True
    assert evidence.materiality_score is not None
    assert evidence.dimensions["version_recency"] < 1.0


@pytest.mark.parametrize(
    "excluded_dates",
    [
        pytest.param(
            {"effective_date": "2026-08-01"}, id="future",
        ),
        pytest.param(
            {
                "effective_date": "2026-07-01",
                "effective_end_date": "2026-07-30",
            },
            id="expired",
        ),
    ],
)
@pytest.mark.parametrize("same_origin", [False, True])
def test_excluded_source_does_not_change_valid_source_weight(
    excluded_dates, same_origin
):
    current = {
        "effective_date": "2026-07-01",
        "duplicate_group": "origin:current",
    }
    excluded = {
        **excluded_dates,
        "duplicate_group": (
            "origin:current" if same_origin else "origin:separate"
        ),
    }

    baseline = make_register("FORMAL", [current]).get(FACT_ID)
    expanded = make_register("FORMAL", [current, excluded]).get(FACT_ID)

    before = baseline.evidence[0]
    after = expanded.evidence[0]

    # A separate excluded origin must not add corroboration.
    # An excluded copy must not penalise the valid source's independence.
    for dimension in ("corroboration", "source_independence"):
        assert after.dimensions[dimension] == before.dimensions[dimension]
    assert after.materiality_score == pytest.approx(before.materiality_score)
    assert expanded.overall_outcome == baseline.overall_outcome
    assert expanded.confidence == baseline.confidence

    assert len(expanded.evidence) == 2
    assert expanded.evidence[1].applicable is False
    assert expanded.evidence[1].material is False
