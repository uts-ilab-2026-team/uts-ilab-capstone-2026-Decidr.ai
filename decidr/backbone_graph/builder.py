"""Assemble and validate the full backbone graph, dump JSON, and the CLI entry point."""

from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path

from decidr.backbone_graph.common import _GraphBuilder
from decidr.backbone_graph.roster import (
    _add_processes,
    _add_role_descriptions,
    _add_roster,
)
from decidr.backbone_graph.structure import (
    _add_documents,
    _add_governs,
    _add_owned_by,
    _add_supersession_and_related,
)
from decidr.constants import (
    CORPUS_GRAPH_PATH as OUTPUT_PATH,  # re-exported for existing importers
)
from decidr.constants import (
    RAW_DATA_DIR,  # ingestion root (corpus lives under data/raw)
)
from decidr.graph.graph import OrganisationalGraph
from decidr.graph.models import GraphEdge
from decidr.ingestion import ingest

# --------------------------------------------------------------------------- #
# Public API                                                                   #
# --------------------------------------------------------------------------- #


def build_corpus_graph(
    data_dir: Path = RAW_DATA_DIR, *, release: str = "phase1"
) -> OrganisationalGraph:
    """Build and validate the persistent backbone graph from the corpus.

    The returned :class:`OrganisationalGraph` is the live object fed to the
    engine. It is validated on construction (schema enforced by the graph).
    """
    result = ingest({release: data_dir})
    builder = _GraphBuilder(warnings=list(result.warnings))

    id_map = _add_documents(builder, result.sources)

    overview_text = (data_dir / "00_overview" / "company_overview.md").read_text(encoding="utf-8")
    roster_text = (data_dir / "00_overview" / "org_chart_and_roster.md").read_text(
        encoding="utf-8"
    )
    roles_text = (data_dir / "00_overview" / "role_descriptions.md").read_text(encoding="utf-8")

    process_ids = _add_processes(builder, overview_text)
    _name_to_role, role_by_label = _add_roster(builder, roster_text)
    _add_role_descriptions(builder, roles_text, role_by_label, process_ids)

    _add_supersession_and_related(builder, result.sources, id_map)
    _add_governs(builder, id_map, process_ids)
    _add_owned_by(builder, result.sources, id_map)

    version = f"corpus-backbone-v1:{result.dataset_fingerprint[:12]}"
    graph = OrganisationalGraph(
        list(builder.nodes.values()), list(builder.edges.values()), version=version
    )
    graph.build_warnings = tuple(builder.warnings)  # type: ignore[attr-defined]
    return graph


def dump_json(graph: OrganisationalGraph, path: Path = OUTPUT_PATH) -> Path:
    """Write an inspectable JSON snapshot that ``OrganisationalGraph.load`` can read back."""
    payload = {
        "graph_version": graph.version,
        "nodes": [
            {"id": n.node_id, "kind": n.kind, "label": n.label, "attributes": n.attributes}
            for n in graph.nodes.values()
        ],
        "edges": [
            {
                "id": e.edge_id,
                "source": e.source,
                "target": e.target,
                "relationship": e.relationship,
                "attributes": e.attributes,
            }
            for e in graph.edges.values()
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _summary(graph: OrganisationalGraph) -> None:
    kinds: dict[str, int] = defaultdict(int)
    for node in graph.nodes.values():
        kinds[node.kind] += 1
    relationships: dict[str, int] = defaultdict(int)
    for edge in graph.edges.values():
        relationships[edge.relationship] += 1
    print(f"graph_version: {graph.version}")
    print(f"nodes: {len(graph.nodes)}  edges: {len(graph.edges)}")
    print("  node kinds:  " + ", ".join(f"{k}={v}" for k, v in sorted(kinds.items())))
    print("  edge types:  " + ", ".join(f"{k}={v}" for k, v in sorted(relationships.items())))


def _resolution_checks(graph: OrganisationalGraph) -> None:
    """Prove backbone_resolution works off the built skeleton (the marquee win)."""
    print("\nbackbone_resolution sanity checks:")
    cases = [
        ("Diane holds Head of Sales", "person:diane-okafor", "role:head-of-sales"),
        ("Diane is NOT Head of Finance", "person:diane-okafor", "role:head-of-finance-people-ops"),
        ("Wei Zhang is inactive", "person:wei-zhang", "role:engineer"),
    ]
    for label, actor, expected in cases:
        probe = GraphEdge(
            edge_id="probe",
            source="document:__probe__",
            target="fact:__probe__",
            relationship="OBSERVED",
            attributes={"actor_person_id": actor, "expected_role_id": expected},
        )
        factor, reason = graph.backbone_resolution(probe)
        print(f"  [{factor:.2f}] {label}: {reason}")


def main() -> None:
    graph = build_corpus_graph()
    _summary(graph)
    warnings = getattr(graph, "build_warnings", ())
    if warnings:
        print(f"\nwarnings ({len(warnings)}):")
        for warning in warnings:
            print(f"  - {warning}")
    _resolution_checks(graph)
    path = dump_json(graph)
    reloaded = OrganisationalGraph.load(path)
    print(f"\nwrote + re-validated snapshot: {path} ({len(reloaded.nodes)} nodes)")
