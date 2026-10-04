"""Validated organisational graph: schema checks, retrieval and visualisation.

A ``Fact`` is a searchable topic and stores no value.  Asserted values live on
``FORMAL`` or ``OBSERVED`` Document -> Fact edges as ``attests_value``.  This
module holds the graph structure and read helpers only; credibility reasoning
lives in ``framework.credibility``.
"""

from __future__ import annotations

import json
from pathlib import Path

import networkx as nx
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from framework.errors import GraphValidationError
from framework.models import GraphEdge, GraphNode


class OrganisationalGraph:
    """Validated NetworkX graph for the standalone prototype."""

    def __init__(self, nodes: list[GraphNode], edges: list[GraphEdge], *, version: str) -> None:
        self.version = version
        self.nodes = {node.node_id: node for node in nodes}
        self.edges = {edge.edge_id: edge for edge in edges}
        self.graph = nx.MultiDiGraph(graph_version=version)
        self._validate()
        for node in nodes:
            self.graph.add_node(
                node.node_id,
                kind=node.kind,
                label=node.label,
                **node.attributes,
            )
        for edge in edges:
            self.graph.add_edge(
                edge.source,
                edge.target,
                key=edge.edge_id,
                edge_id=edge.edge_id,
                relationship=edge.relationship,
                **edge.attributes,
            )

    @classmethod
    def load(cls, path: Path) -> OrganisationalGraph:
        payload = json.loads(path.read_text(encoding="utf-8"))
        nodes = [
            GraphNode(
                node_id=item["id"],
                kind=item["kind"],
                label=item["label"],
                attributes=item.get("attributes", {}),
            )
            for item in payload["nodes"]
        ]
        edges = [
            GraphEdge(
                edge_id=item["id"],
                source=item["source"],
                target=item["target"],
                relationship=item["relationship"].upper(),
                attributes=item.get("attributes", {}),
            )
            for item in payload["edges"]
        ]
        return cls(nodes, edges, version=payload["graph_version"])

    def _validate(self) -> None:
        if len(self.nodes) == 0:
            raise GraphValidationError("The graph must contain nodes")
        if len(self.edges) != len(set(self.edges)):
            raise GraphValidationError("Edge IDs must be unique")
        for node in self.nodes.values():
            if node.kind == "fact" and "value" in node.attributes:
                raise GraphValidationError(
                    f"{node.node_id}: Fact nodes are topics and must not store a value"
                )
        for edge in self.edges.values():
            if edge.source not in self.nodes or edge.target not in self.nodes:
                raise GraphValidationError(f"{edge.edge_id}: edge endpoint does not exist")
            if edge.relationship in {"FORMAL", "OBSERVED"}:
                if self.nodes[edge.source].kind != "document":
                    raise GraphValidationError(
                        f"{edge.edge_id}: an attestation must start at a Document"
                    )
                if self.nodes[edge.target].kind != "fact":
                    raise GraphValidationError(
                        f"{edge.edge_id}: an attestation must end at a Fact"
                    )
                if not str(edge.attributes.get("attests_value", "")).strip():
                    raise GraphValidationError(
                        f"{edge.edge_id}: attestation edges require attests_value"
                    )
                agrees = edge.attributes.get("agrees")
                if agrees not in (True, False, None):
                    raise GraphValidationError(
                        f"{edge.edge_id}: agrees must be true, false or null"
                    )

    def fact_nodes(self) -> list[GraphNode]:
        return sorted(
            (node for node in self.nodes.values() if node.kind == "fact"),
            key=lambda item: item.node_id,
        )

    def document(self, document_id: str) -> GraphNode:
        node = self.nodes[document_id]
        if node.kind != "document":
            raise GraphValidationError(f"{document_id} is not a Document")
        return node

    def attestations(self, fact_id: str) -> list[GraphEdge]:
        return sorted(
            (
                edge
                for edge in self.edges.values()
                if edge.target == fact_id and edge.relationship in {"FORMAL", "OBSERVED"}
            ),
            key=lambda item: item.edge_id,
        )

    def retrieve_facts(self, query: str, *, limit: int = 3) -> list[tuple[GraphNode, float]]:
        """Retrieve candidate Facts with a local, deterministic vector index."""
        facts = self.fact_nodes()
        if not query.strip() or not facts:
            return []
        corpus = [
            " ".join(
                (
                    fact.label,
                    str(fact.attributes.get("statement", "")),
                    str(fact.attributes.get("category", "")),
                    str(fact.attributes.get("scope", "")),
                )
            )
            for fact in facts
        ]
        matrix = TfidfVectorizer(ngram_range=(1, 2), stop_words="english").fit_transform(
            corpus + [query]
        )
        similarities = cosine_similarity(matrix[-1], matrix[:-1]).ravel()
        ranked = sorted(zip(facts, similarities, strict=True), key=lambda item: -item[1])
        return [(fact, float(score)) for fact, score in ranked[:limit] if score > 0]

    def related_qualifiers(self, fact_id: str) -> list[str]:
        """Follow one Document RELATED hop and read the neighbour's own Fact edge."""
        source_documents = {edge.source for edge in self.attestations(fact_id)}
        related_documents: set[str] = set()
        reasons: dict[tuple[str, str], str] = {}
        for edge in self.edges.values():
            if edge.relationship != "RELATED":
                continue
            if edge.source in source_documents:
                related_documents.add(edge.target)
                reasons[(edge.source, edge.target)] = str(
                    edge.attributes.get("reason", "related document")
                )
            if edge.target in source_documents:
                related_documents.add(edge.source)
                reasons[(edge.target, edge.source)] = str(
                    edge.attributes.get("reason", "related document")
                )
        qualifiers = []
        for edge in self.edges.values():
            if (
                edge.source in related_documents
                and edge.relationship in {"FORMAL", "OBSERVED"}
                and edge.target != fact_id
            ):
                fact = self.nodes[edge.target]
                reason = next(
                    (
                        value
                        for (origin, related), value in reasons.items()
                        if related == edge.source and origin in source_documents
                    ),
                    "related document",
                )
                qualifiers.append(f"{fact.label}: {edge.attributes['attests_value']} ({reason}).")
        return sorted(dict.fromkeys(qualifiers))

    def backbone_resolution(self, edge: GraphEdge) -> tuple[float, str]:
        """Verify that an edge's named actor is active and holds the expected role."""
        actor_id = edge.attributes.get("actor_person_id")
        expected_role = edge.attributes.get("expected_role_id")
        if not actor_id:
            return 1.0, "No person-level authority resolution was required."
        person = self.nodes.get(str(actor_id))
        if person is None or person.kind != "person":
            return 0.5, "The named actor could not be resolved to a Person node."
        active = person.attributes.get("status") == "active"
        held_roles = {
            item.target
            for item in self.edges.values()
            if item.source == actor_id and item.relationship == "HOLDS"
        }
        if not active:
            return 0.5, f"{person.label} is not marked active."
        if expected_role and expected_role not in held_roles:
            return 0.6, f"{person.label} is active but does not hold the expected role."
        roles = ", ".join(self.nodes[item].label for item in sorted(held_roles)) or "no role"
        return 1.0, f"{person.label} is active and resolves to {roles}."

    def fact_dot(self, fact_id: str) -> str:
        """Render only the selected Fact, its Documents and one-hop related Documents."""
        lines = [
            "digraph graph_fact {",
            "rankdir=LR;",
            'node [shape=box, style="rounded,filled"];',
        ]
        fact = self.nodes[fact_id]
        label = fact.label.replace('"', "'")
        lines.append(f'"{fact_id}" [label="{label}", fillcolor="#f59e0b"];')
        document_ids = {edge.source for edge in self.attestations(fact_id)}
        for edge in self.edges.values():
            if edge.relationship == "RELATED" and (
                edge.source in document_ids or edge.target in document_ids
            ):
                document_ids.update((edge.source, edge.target))
        for document_id in sorted(document_ids):
            document = self.nodes[document_id]
            colour = (
                "#93c5fd"
                if document_id in {edge.source for edge in self.attestations(fact_id)}
                else "#d1d5db"
            )
            doc_label = document.label.replace('"', "'")
            lines.append(f'"{document_id}" [label="{doc_label}", fillcolor="{colour}"];')
        for edge in self.edges.values():
            if edge.relationship in {"FORMAL", "OBSERVED"} and edge.target == fact_id:
                lines.append(f'"{edge.source}" -> "{fact_id}" [label="{edge.relationship}"];')
            elif (
                edge.relationship == "RELATED"
                and edge.source in document_ids
                and edge.target in document_ids
            ):
                lines.append(
                    f'"{edge.source}" -> "{edge.target}" [label="RELATED", style=dashed];'
                )
        lines.append("}")
        return "\n".join(lines)
