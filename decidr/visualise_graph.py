"""Render the backbone graph (``corpus_graph.json``) to an interactive HTML (pyvis).

Drag nodes, zoom, and hover to read a node's kind + attributes. The HTML inlines
its JS, so it works offline (good for the demo). The full graph is busy, so pick
a *view*:

    uv run python -m decidr.visualise_graph org        # people side: person/role/function
    uv run python -m decidr.visualise_graph process     # process side: role/process/document
    uv run python -m decidr.visualise_graph discount     # just the P1 discount scenario
    uv run python -m decidr.visualise_graph all          # everything

Writes ``graph_views/backbone_<view>.html`` — open it in any browser.
"""

from __future__ import annotations

from pathlib import Path
import sys

from framework.graph import OrganisationalGraph
import networkx as nx
from pyvis.network import Network

from decidr.constants import CORPUS_GRAPH_PATH as GRAPH_PATH
from decidr.constants import REPO_ROOT

OUTPUT_DIR = REPO_ROOT / "graph_views"

KIND_COLOUR = {
    "person": "#60a5fa",
    "role": "#f59e0b",
    "function": "#34d399",
    "process": "#f472b6",
    "system": "#a78bfa",
    "document": "#d1d5db",
}

# view -> (node kinds to keep, relationships to keep or None for all)
VIEWS = {
    "org": ({"person", "role", "function"}, {"HOLDS", "SITS_IN", "REPORTS_TO"}),
    "process": ({"role", "process", "document"}, {"PARTICIPATES_IN", "GOVERNS"}),
    "all": (set(KIND_COLOUR), None),
}


def _subgraph(og: OrganisationalGraph, view: str) -> nx.MultiDiGraph:
    full = og.graph
    if view == "discount":
        # Keep the discount neighbourhood: process P1, its docs/roles and their people.
        keep = {"process:p1"}
        for u, v, rel in full.edges(data="relationship"):
            if v == "process:p1" and rel in {"GOVERNS", "PARTICIPATES_IN"}:
                keep.add(u)
        for role in keep:
            for u, v, rel in full.edges(data="relationship"):
                if v == role and rel == "HOLDS":
                    keep.add(u)  # person holding a discount role
        return full.subgraph(keep).copy()
    kinds, rels = VIEWS[view]
    nodes = [n for n, d in full.nodes(data=True) if d.get("kind") in kinds]
    sub = full.subgraph(nodes).copy()
    if rels is not None:
        drop = [
            (u, v, k) for u, v, k, r in sub.edges(keys=True, data="relationship") if r not in rels
        ]
        sub.remove_edges_from(drop)
    sub.remove_nodes_from([n for n in list(sub) if sub.degree(n) == 0])
    return sub


def _node_title(attributes: dict) -> str:
    """Tooltip text: kind first, then each attribute on its own line."""
    lines = [f"kind: {attributes.get('kind', '')}"]
    lines += [f"{k}: {v}" for k, v in attributes.items() if k not in {"kind", "label"}]
    return "\n".join(lines)


def render(view: str = "org") -> Path:
    og = OrganisationalGraph.load(GRAPH_PATH)
    sub = _subgraph(og, view)
    if sub.number_of_nodes() == 0:
        raise SystemExit(f"view {view!r} produced an empty graph")

    net = Network(
        height="900px",
        width="100%",
        directed=True,
        bgcolor="#ffffff",
        font_color="#111827",
        cdn_resources="in_line",  # inline JS -> works offline
    )

    for node_id, data in sub.nodes(data=True):
        kind = data.get("kind", "")
        net.add_node(
            node_id,
            label=data.get("label", node_id),
            title=_node_title(data),
            color=KIND_COLOUR.get(kind, "#999999"),
            shape="box" if kind == "document" else "dot",
            size=20 if kind in {"role", "process"} else 15,
        )
    for source, target, relationship in sub.edges(data="relationship"):
        net.add_edge(source, target, label=relationship, title=relationship)

    # Middle-ground spacing (enough room to read, not flung apart) + a live tuning
    # panel ("configure") so you can drag the spacing/physics sliders in the page.
    # avoidOverlap keeps labels from stacking on top of each other.
    net.set_options(
        """
    {
      "nodes": {"font": {"size": 16, "face": "sans-serif"}, "borderWidth": 1},
      "edges": {
        "font": {"size": 10, "align": "middle", "color": "#6b7280"},
        "color": {"color": "#9ca3af"}, "smooth": false,
        "arrows": {"to": {"enabled": true, "scaleFactor": 0.5}}
      },
      "physics": {
        "barnesHut": {
          "gravitationalConstant": -6000, "centralGravity": 0.3,
          "springLength": 160, "springConstant": 0.04,
          "damping": 0.4, "avoidOverlap": 1
        },
        "minVelocity": 0.75,
        "stabilization": {"enabled": true, "iterations": 400}
      },
      "interaction": {"hover": true, "tooltipDelay": 100, "navigationButtons": true},
      "configure": {"enabled": true, "filter": ["physics"], "showButton": true}
    }
    """
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / f"backbone_{view}.html"
    net.write_html(str(out), notebook=False)
    return out


def main() -> None:
    view = sys.argv[1] if len(sys.argv) > 1 else "org"
    if view not in {*VIEWS, "discount"}:
        raise SystemExit(f"unknown view {view!r}; choose: org, process, discount, all")
    out = render(view)
    print(f"wrote {out}  — open it in a browser")


if __name__ == "__main__":
    main()
