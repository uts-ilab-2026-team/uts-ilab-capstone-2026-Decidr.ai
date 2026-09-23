"""Claim-centred graph views derived from the relational evidence ledger."""

import json
import sqlite3
import textwrap

import networkx as nx

from decidr.corpus import active_source, eligible_modelling_evidence


def build_ledger_graph(connection: sqlite3.Connection) -> nx.MultiDiGraph:
    """Build the shared provenance graph from explicit ledger fields only."""
    graph = nx.MultiDiGraph(graph_type="shared_evidence_ledger")
    sources = {}
    for sid, payload, status in connection.execute(
        "SELECT source_id,payload_json,ingestion_status FROM sources ORDER BY source_id"
    ):
        source = json.loads(payload)
        if eligible_modelling_evidence(source, {}, status):
            sources[sid] = source
            graph.add_node(sid, kind="document", label=source["title"])
    for sid, source in sources.items():
        for field, relationship in (
            ("responsible_person_or_role", "OWNED_BY"),
            ("author_or_system", "AUTHORED_BY"),
        ):
            if owner := source.get(field):
                owner_id = f"actor:{owner}"
                graph.add_node(owner_id, kind="person_or_role", label=owner)
                graph.add_edge(
                    sid,
                    owner_id,
                    relationship=relationship,
                    origin="source_metadata",
                    validation_status="metadata_only",
                )
        for field, relationship in (
            ("predecessor_source_id", "SUPERSEDES"),
            ("derived_from_source_id", "DERIVED_FROM"),
        ):
            target = source.get(field)
            if target in sources:
                graph.add_edge(
                    sid,
                    target,
                    relationship=relationship,
                    origin="explicit_metadata",
                    validation_status="validated",
                )
        if group := source.get("duplicate_group"):
            graph.add_node(group, kind="source_group", label=group)
            graph.add_edge(
                sid,
                group,
                relationship="SHARED_ORIGIN",
                origin="ingestion_provenance",
                validation_status="metadata_only",
            )
    for eid, sid, payload in connection.execute(
        "SELECT evidence_id,source_id,payload_json FROM evidence ORDER BY evidence_id"
    ):
        evidence = json.loads(payload)
        if sid not in sources or not eligible_modelling_evidence(
            sources[sid], evidence, "ingested"
        ):
            continue
        graph.add_node(eid, kind="evidence", label=evidence["locator"])
        graph.add_edge(
            eid,
            sid,
            relationship="EXTRACTED_FROM",
            origin="deterministic_ingestion",
            validation_status="validated",
        )
        for field, kind in (
            ("process", "process"),
            ("actor", "person"),
            ("role", "role"),
            ("system", "system"),
            ("row_identifier", "operational_event"),
        ):
            if value := evidence.get(field):
                node_id = f"{kind}:{value}"
                graph.add_node(node_id, kind=kind, label=value)
                graph.add_edge(
                    eid,
                    node_id,
                    relationship="APPLIES_TO",
                    origin="extracted_metadata",
                    validation_status="metadata_only",
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
               s.source_id, s.payload_json, l.payload_json
        FROM claim_evidence_links l
        JOIN evidence e ON e.evidence_id=l.evidence_id
        JOIN sources s ON s.source_id=e.source_id
        WHERE l.claim_id=? AND s.source_id LIKE 'phase2:%'
        ORDER BY l.reviewer, e.evidence_id
        """,
        (claim_id,),
    ).fetchall()
    included_sources: set[str] = set()
    for relationship, reviewer, evidence_id, locator, source_id, payload, link_payload in rows:
        source = json.loads(payload)
        link = json.loads(link_payload)
        reviewed = link.get("method") == "human_review" and link.get("review_status") == "complete"
        included_sources.add(source_id)
        graph.add_node(source_id, kind="source", label=source["title"])
        graph.add_node(evidence_id, kind="evidence", label=locator)
        graph.add_edge(
            evidence_id,
            source_id,
            relationship="EXTRACTED_FROM",
            origin="deterministic_ingestion",
            validation_status="validated",
        )
        graph.add_edge(
            evidence_id,
            claim_id,
            relationship=relationship.upper(),
            reviewer=reviewer,
            origin="human_validated" if reviewed else "proposed_relationship",
            validation_status="human_validated" if reviewed else "unreviewed",
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
            if target and active_source(target):
                graph.add_node(target, kind="source", label=target)
                graph.add_edge(
                    source_id,
                    target,
                    relationship=relationship,
                    origin="explicit_metadata",
                    validation_status="validated",
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
                    source_id,
                    peer_id,
                    relationship="DUPLICATES",
                    origin="explicit_metadata",
                    validation_status="validated",
                )
    return graph


def to_graphviz(graph: nx.MultiDiGraph) -> str:
    """Render a small graph as Graphviz DOT for Streamlit."""
    colours = {"claim": "#f59e0b", "evidence": "#60a5fa", "source": "#86efac"}
    relationships = {
        "support": ("Supports", "#15803d"),
        "contradict": ("Contradicts", "#b91c1c"),
        "qualify": ("Qualifies", "#a16207"),
        "contextual": ("Context", "#2563eb"),
        "excluded": ("Excluded", "#6b7280"),
        "unclassified": ("Unclassified", "#7e22ce"),
    }
    lines = ["digraph evidence {", "rankdir=LR;", 'node [shape=box, style="rounded,filled"];']
    for node, attributes in graph.nodes(data=True):
        label = "\n".join(
            textwrap.wrap(str(attributes.get("label", node)), width=34, break_long_words=False)
        )
        colour = colours.get(str(attributes.get("kind")), "#d1d5db")
        details = "".join(
            f", {key}={json.dumps(str(attributes[key]))}"
            for key in ("URL", "tooltip")
            if key in attributes
        )
        lines.append(
            f'{json.dumps(str(node))} [label={json.dumps(label)}, fillcolor="{colour}"{details}];'
        )
    for source, target, attributes in graph.edges(data=True):
        relationship = str(attributes.get("relationship", "RELATED_TO"))
        label, colour = relationships.get(
            relationship.lower(), (relationship.replace("_", " ").capitalize(), "#475569")
        )
        if attributes.get("assessment_target"):
            label += "\n" + attributes["assessment_target"].replace("_", " ")
            if attributes.get("disposition") == "excluded":
                label += (
                    "\n(" + str(attributes.get("assessed_relationship") or "unclassified") + ")"
                )
        style = "dashed" if relationship.lower() in {"excluded", "unclassified"} else "solid"
        lines.append(
            f"{json.dumps(str(source))} -> {json.dumps(str(target))} [label={json.dumps(label)}, color={json.dumps(colour)}, fontcolor={json.dumps(colour)}, style={json.dumps(style)}, tooltip={json.dumps(attributes.get('tooltip', label))}];"
        )
    lines.append("}")
    return "\n".join(lines)
