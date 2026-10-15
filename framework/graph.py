"""Validated organisational graph: schema checks, retrieval and visualisation.

A ``Fact`` is a searchable topic and stores no value.  Asserted values live on
``FORMAL`` or ``OBSERVED`` Document -> Fact edges as ``attests_value``.  This
module holds the graph structure and read helpers only; credibility reasoning
lives in ``framework.credibility``.
"""

from __future__ import annotations

from datetime import date
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

        node_ids = [node.node_id for node in nodes]
        if len(node_ids) != len(set(node_ids)):
            raise GraphValidationError("Node IDs must be unique")

        edge_ids = [edge.edge_id for edge in edges]
        if len(edge_ids) != len(set(edge_ids)):
            raise GraphValidationError("Edge IDs must be unique")

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
        for node in self.nodes.values():
            if not isinstance(node.attributes, dict):
                raise GraphValidationError(f"{node.node_id}: attributes must be an object")
            if node.kind == "document":
                self._validate_document_dates(node)
            if node.kind == "fact" and "value" in node.attributes:
                raise GraphValidationError(
                    f"{node.node_id}: Fact nodes are topics and must not store a value"
                )
        for edge in self.edges.values():
            if not isinstance(edge.attributes, dict):
                raise GraphValidationError(f"{edge.edge_id}: attributes must be an object")
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
                value = edge.attributes.get("attests_value")
                if not isinstance(value, str) or not value.strip():
                    raise GraphValidationError(
                        f"{edge.edge_id}: attestation edges require attests_value"
                    )
                agrees = edge.attributes.get("agrees")
                if agrees is not None and type(agrees) is not bool:
                    raise GraphValidationError(
                        f"{edge.edge_id}: agrees must be true, false or null"
                    )

                verified = edge.attributes.get("independence_verified", False)
                basis = edge.attributes.get("independence_basis", "")
                if type(verified) is not bool or not isinstance(basis, str):
                    raise GraphValidationError("Invalid independence judgement types")
                if verified and not basis.strip():
                    raise GraphValidationError("Verified independence requires a basis")

                for name in ("applicable", "scope_match"):
                    if name in edge.attributes and type(edge.attributes[name]) is not bool:
                        raise GraphValidationError(f"{edge.edge_id}: {name} must be true or false")
                for name in ("directness", "specificity", "completeness"):
                    if name not in edge.attributes:
                        continue
                    score = edge.attributes[name]
                    if type(score) not in (int, float) or not 0 <= score <= 1:
                        raise GraphValidationError(
                            f"{edge.edge_id}: {name} must be a finite number between 0 and 1"
                        )

    @staticmethod
    def _validate_document_dates(document: GraphNode) -> None:
        parsed = {}
        for name in ("effective_date", "effective_end_date", "last_updated", "superseded_date"):
            value = document.attributes.get(name)
            if value is None:
                continue
            try:
                if not isinstance(value, str):
                    raise TypeError("Date must be a string")
                parsed_date = date.fromisoformat(value)
                if parsed_date.isoformat() != value:
                    raise ValueError("Date must use YYYY-MM-DD")
            except (TypeError, ValueError) as error:
                raise GraphValidationError(
                    f"{document.node_id}: {name} must be a valid YYYY-MM-DD date or null"
                ) from error
            parsed[name] = parsed_date
        start = parsed.get("effective_date")
        end = parsed.get("effective_end_date")
        if start is not None and end is not None and end < start:
            raise GraphValidationError(
                f"{document.node_id}: effective_end_date must not precede effective_date"
            )

    def fact_nodes(self) -> list[GraphNode]:
        return sorted(
            (self.nodes[nid] for nid, kind in self.graph.nodes(data="kind") if kind == "fact"),
            key=lambda item: item.node_id,
        )

    def document(self, document_id: str) -> GraphNode:
        node = self.nodes[document_id]
        if node.kind != "document":
            raise GraphValidationError(f"{document_id} is not a Document")
        return node

    def attestations(self, fact_id: str) -> list[GraphEdge]:
        if fact_id not in self.graph:
            return []
        return sorted(
            (
                self.edges[key]
                for _, _, key, rel in self.graph.in_edges(fact_id, keys=True, data="relationship")
                if rel in {"FORMAL", "OBSERVED"}
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
            target
            for _, target, rel in self.graph.out_edges(actor_id, data="relationship")
            if rel == "HOLDS"
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
