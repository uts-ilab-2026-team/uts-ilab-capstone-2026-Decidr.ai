"""Claim-centred graph views derived from the relational evidence ledger."""

import json
import sqlite3

import networkx as nx


def build_ledger_graph(connection: sqlite3.Connection) -> nx.MultiDiGraph:
    """Build the shared provenance graph from explicit ledger fields only."""
    graph = nx.MultiDiGraph(graph_type="shared_evidence_ledger")
    for row in connection.execute("SELECT source_id,payload_json FROM sources ORDER BY source_id"):
        source = json.loads(row[1])
        graph.add_node(row[0], kind="document", label=source["title"])
        owner = source.get("responsible_person_or_role") or source.get("author_or_system")
        if owner:
            owner_id = f"actor:{owner}"
            graph.add_node(owner_id, kind="person_or_role", label=owner)
            graph.add_edge(
                row[0], owner_id, relationship="OWNED_BY",
                origin="explicit_metadata", validation_status="validated",
            )
        for field, relationship in (
            ("predecessor_source_id", "SUPERSEDES"),
            ("derived_from_source_id", "DERIVED_FROM"),
        ):
            if source.get(field):
                graph.add_edge(
                    row[0], source[field], relationship=relationship,
                    origin="explicit_metadata", validation_status="validated",
                )
    for row in connection.execute("SELECT evidence_id,source_id,payload_json FROM evidence"):
        evidence = json.loads(row[2])
        graph.add_node(row[0], kind="evidence", label=evidence["locator"])
        graph.add_edge(
            row[0], row[1], relationship="EXTRACTED_FROM",
            origin="deterministic_ingestion", validation_status="validated",
        )
        for field, kind, relationship in (
            ("process", "process", "APPLIES_TO"),
            ("actor", "person", "APPLIES_TO"),
            ("role", "role", "APPLIES_TO"),
            ("system", "system", "APPLIES_TO"),
            ("row_identifier", "operational_event", "APPLIES_TO"),
        ):
            value = evidence.get(field)
            if value:
                node_id = f"{kind}:{value}"
                graph.add_node(node_id, kind=kind, label=value)
                graph.add_edge(
                    row[0], node_id, relationship=relationship,
                    origin="explicit_metadata", validation_status="validated",
                )
    return graph


def build_claim_graph(connection: sqlite3.Connection, claim_id: str) -> nx.MultiDiGraph:
    """Build a bounded claim graph; the graph does not determine credibility."""
    graph = nx.MultiDiGraph(claim_id=claim_id)
    claim_row = connection.execute(
        "SELECT payload_json FROM claims WHERE claim_id=?", (claim_id,)
    ).fetchone()
    if claim_row is None:
        raise ValueError(f"Unknown claim_id: {claim_id}")
    claim = json.loads(claim_row[0])
    graph.add_node(claim_id, kind="claim", label=claim["claim_text"])
    rows = connection.execute(
        """
        SELECT l.relationship, l.reviewer, e.evidence_id, e.locator,
               s.source_id, s.payload_json
        FROM claim_evidence_links l
        JOIN evidence e ON e.evidence_id=l.evidence_id
        JOIN sources s ON s.source_id=e.source_id
        WHERE l.claim_id=?
        ORDER BY l.reviewer, e.evidence_id
        """,
        (claim_id,),
    ).fetchall()
    included_sources: set[str] = set()
    for relationship, reviewer, evidence_id, locator, source_id, payload in rows:
        source = json.loads(payload)
        included_sources.add(source_id)
        graph.add_node(source_id, kind="source", label=source["title"])
        graph.add_node(evidence_id, kind="evidence", label=locator)
        graph.add_edge(
            evidence_id, source_id, relationship="EXTRACTED_FROM",
            origin="deterministic_ingestion", validation_status="validated",
        )
        graph.add_edge(
            evidence_id,
            claim_id,
            relationship=relationship.upper(),
            reviewer=reviewer,
            origin="human_validated",
            validation_status="human_validated",
        )
    source_payloads = {}
    for source_id in included_sources:
        payload = connection.execute(
            "SELECT payload_json FROM sources WHERE source_id=?", (source_id,)
        ).fetchone()[0]
        source_payloads[source_id] = json.loads(payload)
    for source_id, source in source_payloads.items():
        for field, relationship in (
            ("predecessor_source_id", "SUPERSEDES"),
            ("derived_from_source_id", "DERIVED_FROM"),
        ):
            target = source.get(field)
            if target:
                graph.add_node(target, kind="source", label=target)
                graph.add_edge(
                    source_id, target, relationship=relationship,
                    origin="explicit_metadata", validation_status="validated",
                )
        duplicate_group = source.get("duplicate_group")
        if duplicate_group:
            peers = [
                peer_id
                for peer_id, peer in source_payloads.items()
                if peer_id > source_id and peer.get("duplicate_group") == duplicate_group
            ]
            for peer_id in peers:
                graph.add_edge(
                    source_id, peer_id, relationship="DUPLICATES",
                    origin="explicit_metadata", validation_status="validated",
                )
    return graph


def to_graphviz(graph: nx.MultiDiGraph) -> str:
    """Render a small graph as Graphviz DOT for Streamlit."""
    colours = {"claim": "#f59e0b", "evidence": "#60a5fa", "source": "#86efac"}
    lines = ["digraph evidence {", "rankdir=LR;", 'node [shape=box, style="rounded,filled"];']
    for node, attributes in graph.nodes(data=True):
        label = str(attributes.get("label", node)).replace('"', "'")[:80]
        colour = colours.get(str(attributes.get("kind")), "#d1d5db")
        lines.append(f'"{node}" [label="{label}", fillcolor="{colour}"];')
    for source, target, attributes in graph.edges(data=True):
        relationship = str(attributes.get("relationship", "RELATED_TO"))
        lines.append(f'"{source}" -> "{target}" [label="{relationship}"];')
    lines.append("}")
    return "\n".join(lines)
