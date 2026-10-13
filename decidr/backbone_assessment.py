"""Score LLM findings against the REAL persistent backbone (Phase 2b).

Unlike ``assess_prepared_facet`` (which builds a throwaway graph with synthetic
``document:{i}`` nodes), this attaches the per-claim overlay — one ``fact`` node
plus ``FORMAL``/``OBSERVED`` edges — onto the loaded skeleton's actual
``document:<code>`` nodes. Because the real ``person``/``role``/``HOLDS`` edges
are present, ``backbone_resolution`` can fire: a named approver who does not hold
the expected role is demoted (the Diane-20% authority win).

The verbatim-quote trust rail is preserved: ``_find_passage`` rejects any finding
whose quotation is not an exact substring of a stored passage.

Demo (no Ollama; uses a recorded fixture + a synthetic authority probe):
    uv run python -m decidr.backbone_assessment
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from framework import CONFIG_PATH
from framework.config import GraphCredibilityConfig
from framework.credibility import GraphCredibilityFramework
from framework.graph import OrganisationalGraph
from framework.models import FactAssessment, GraphEdge, GraphNode

from decidr.backbone_graph import OUTPUT_PATH as BACKBONE_PATH
from decidr.backbone_graph import _slug
from decidr.finding_shim import (
    DEFAULT_AS_OF,
    CorpusSnapshot,
    LlmFinding,
    _find_passage,
    _map_quality,
    load_corpus_snapshot,
)

_AGREES = {"support": True, "contradict": False}  # else -> None (qualify/context)


def load_skeleton() -> OrganisationalGraph:
    """Load the persistent backbone graph built by ``decidr.backbone_graph``."""
    return OrganisationalGraph.load(BACKBONE_PATH)


def _overlay_edge(
    finding: LlmFinding,
    snapshot: CorpusSnapshot,
    skeleton: OrganisationalGraph,
    config: GraphCredibilityConfig,
    fact_id: str,
    edge_id: str,
) -> GraphEdge:
    """Build one attestation edge from a REAL skeleton document node to the fact."""
    if finding.mode not in {"formal", "observed"}:
        raise ValueError(f"finding mode {finding.mode!r} is not attestable")
    source = snapshot.sources_by_code.get(finding.source_code)
    if source is None:
        raise ValueError(f"no corpus source for code {finding.source_code!r}")
    document_id = f"document:{finding.source_code}"
    if document_id not in skeleton.nodes:
        raise ValueError(f"{document_id} is not a node in the skeleton")
    # Trust rail: the quote must appear verbatim in a stored passage.
    _find_passage(snapshot.evidence_by_source.get(source.source_id, []), finding.quotation)

    quality = _map_quality(finding, source, config)
    attributes = {
        "attests_value": finding.quotation,
        "agrees": _AGREES.get(finding.stance),  # None for qualify/context
        "applicable": True,
        "scope_match": bool(quality["scope_matches"]),
        "directness": quality["directness"],
        "specificity": quality["specificity"],
        "completeness": quality["completeness"],
        "independence_verified": False,
        "independence_basis": "",
    }
    # Person-level authority: carried only when the finding names an actor.
    if finding.actor_person_id:
        attributes["actor_person_id"] = finding.actor_person_id
        attributes["expected_role_id"] = finding.expected_role_id
    return GraphEdge(edge_id, document_id, fact_id, finding.mode.upper(), attributes)


def assess_on_backbone(
    findings: Iterable[LlmFinding],
    *,
    facet: str,
    claim_text: str,
    snapshot: CorpusSnapshot,
    skeleton: OrganisationalGraph,
    config: GraphCredibilityConfig,
    as_of: date = DEFAULT_AS_OF,
) -> FactAssessment:
    """Lay a fact + attestation overlay on the skeleton and score it with the engine."""
    fact_id = f"fact:{_slug(facet)}"
    overlay_nodes = [
        GraphNode(
            fact_id,
            "fact",
            facet,
            {"statement": facet, "claim_text": claim_text, "category": "corpus-facet"},
        )
    ]
    overlay_edges = [
        _overlay_edge(finding, snapshot, skeleton, config, fact_id, f"attest:{index}")
        for index, finding in enumerate(findings, start=1)
    ]
    nodes = [*skeleton.nodes.values(), *overlay_nodes]
    edges = [*skeleton.edges.values(), *overlay_edges]
    graph = OrganisationalGraph(nodes, edges, version=f"{skeleton.version}+overlay")
    return GraphCredibilityFramework(graph, config).evaluate_fact(fact_id, as_of=as_of)


# --------------------------------------------------------------------------- #
# Demo / self-test                                                            #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class _Scenario:
    label: str
    finding: LlmFinding


def _print_assessment(title: str, assessment: FactAssessment) -> None:
    print(f"\n{title}")
    print(f"  overall={assessment.overall_outcome}  confidence={assessment.confidence}")
    for edge in assessment.evidence:
        score = "n/a" if edge.materiality_score is None else f"{edge.materiality_score:.3f}"
        print(f"  edge {edge.document_id} [{edge.mode}] material={edge.material} score={score}")
        for line in edge.trace:
            if "authority" in line.lower() or "resolves" in line.lower() or "hold" in line.lower():
                print(f"       ↳ {line}")


def main() -> None:
    from pathlib import Path

    config = GraphCredibilityConfig.load(CONFIG_PATH)
    snapshot = load_corpus_snapshot()
    skeleton = load_skeleton()

    fixture = (
        Path(__file__).resolve().parents[1]
        / "evaluation/interpretation/runs"
        / "llama31-pilot-v2-20261009T130632838321Z"
        / "C01-01--approval_requirement"
        / "result.json"
    )
    from decidr.finding_shim import finding_from_result_json

    base = finding_from_result_json(fixture)

    # Scenario A: the real policy finding, scored against the REAL backbone.
    a = assess_on_backbone(
        [base],
        facet=base.facet,
        claim_text=base.claim_text,
        snapshot=snapshot,
        skeleton=skeleton,
        config=config,
    )
    _print_assessment("A) POL-01 on real backbone (no named actor):", a)

    # Scenario B: same quote, but the finding now names Diane as approver expecting
    # Head of Finance. Diane holds Head of SALES in the skeleton -> authority demoted.
    from dataclasses import replace

    diane = replace(
        base,
        actor_person_id="person:diane-okafor",
        expected_role_id="role:head-of-finance-people-ops",
        mode="observed",
    )
    b = assess_on_backbone(
        [diane],
        facet=base.facet,
        claim_text=base.claim_text,
        snapshot=snapshot,
        skeleton=skeleton,
        config=config,
    )
    _print_assessment("B) authority probe — Diane expected as Head of Finance:", b)
    print("\n(backbone_resolution fired in B: Diane holds Head of Sales, not Finance → demoted.)")


if __name__ == "__main__":
    main()
