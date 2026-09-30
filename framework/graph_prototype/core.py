"""Standalone graph-governed credibility framework.

This module intentionally does not import or write to the existing relational
credibility framework.  A Fact is a searchable topic.  Values live only on
FORMAL or OBSERVED Document -> Fact edges as ``attests_value``.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import networkx as nx
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

CREDIBILITY_DIMENSIONS = (
    "source_authority",
    "approval_status",
    "version_recency",
    "directness",
    "specificity",
    "corroboration",
    "source_independence",
    "evidence_completeness",
)

CREDIBILITY_QUESTIONS = {
    "source_authority": "Is the source authoritative for this topic and is any named actor valid?",
    "approval_status": "Is the document approved/current rather than draft or superseded?",
    "version_recency": "Was the source effective at the date relevant to the claim?",
    "directness": "Is this a primary record or direct statement?",
    "specificity": "Does it address the exact threshold, event, scope or value?",
    "corroboration": "Is the same stance supported by a separate evidential origin?",
    "source_independence": "Is this genuinely independent rather than a duplicate?",
    "evidence_completeness": "Does it contain the material details needed for judgement?",
}

OUTCOMES = ("Supported", "Contradicted", "Contested", "Insufficient evidence")
CONFIDENCE_LEVELS = ("Higher confidence", "Moderate confidence", "Lower confidence")


class GraphValidationError(ValueError):
    """Raised when the standalone graph violates the declared schema."""


@dataclass(frozen=True, slots=True)
class GraphNode:
    node_id: str
    kind: str
    label: str
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GraphEdge:
    edge_id: str
    source: str
    target: str
    relationship: str
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EdgeAssessment:
    edge_id: str
    document_id: str
    document_title: str
    mode: str
    attests_value: str
    stance: str
    source_class: str
    lifecycle_status: str
    applicable: bool
    materiality_score: float | None
    material: bool
    dimensions: dict[str, float]
    limitations: tuple[str, ...]
    trace: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FactAssessment:
    fact_id: str
    statement: str
    category: str
    formal_outcome: str
    observed_outcome: str
    overall_outcome: str
    confidence: str
    summary: str
    evidence: tuple[EdgeAssessment, ...]
    gaps: tuple[str, ...]
    related_qualifiers: tuple[str, ...]
    rules_applied: tuple[str, ...]

    def model_dump(self) -> dict[str, Any]:
        """Return a JSON-safe structure without depending on existing models."""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class GraphCredibilityConfig:
    config_version: str
    materiality_threshold: float
    conflict_ratio: float
    dimension_weights: dict[str, float]
    source_class_weights: dict[str, float]
    approval_weights: dict[str, float]
    lifecycle_multipliers: dict[str, float]
    undated_weight: float
    stale_weight: float
    recency_years: int

    @classmethod
    def load(cls, path: Path) -> GraphCredibilityConfig:
        payload = json.loads(path.read_text(encoding="utf-8"))
        config = cls(**payload)
        if set(config.dimension_weights) != set(CREDIBILITY_DIMENSIONS):
            raise GraphValidationError(
                "Graph credibility weights must cover exactly the eight declared dimensions"
            )
        if not 0 <= config.materiality_threshold <= 1:
            raise GraphValidationError("materiality_threshold must be between 0 and 1")
        if sum(config.dimension_weights.values()) <= 0:
            raise GraphValidationError("dimension weights must total above zero")
        return config


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


class GraphCredibilityFramework:
    """Evaluate Fact attestations with source -> status -> date discipline."""

    def __init__(self, graph: OrganisationalGraph, config: GraphCredibilityConfig) -> None:
        self.graph = graph
        self.config = config

    @classmethod
    def load(cls, graph_path: Path, config_path: Path) -> GraphCredibilityFramework:
        return cls(
            OrganisationalGraph.load(graph_path),
            GraphCredibilityConfig.load(config_path),
        )

    def evaluate_fact(self, fact_id: str, *, as_of: date) -> FactAssessment:
        fact = self.graph.nodes.get(fact_id)
        if fact is None or fact.kind != "fact":
            raise KeyError(f"Unknown Fact: {fact_id}")
        attestations = self.graph.attestations(fact_id)
        duplicate_counts: dict[str, int] = {}
        corroboration_counts: dict[tuple[str, str], set[str]] = {}
        for edge in attestations:
            document = self.graph.document(edge.source)
            group = str(document.attributes.get("duplicate_group") or document.node_id)
            duplicate_counts[group] = duplicate_counts.get(group, 0) + 1
            key = (edge.relationship.lower(), self._stance(edge))
            corroboration_counts.setdefault(key, set()).add(group)

        reviewed = tuple(
            self._evaluate_edge(
                edge,
                as_of=as_of,
                duplicate_counts=duplicate_counts,
                corroboration_counts=corroboration_counts,
            )
            for edge in attestations
        )
        formal = self._lane_outcome(reviewed, "formal")
        observed = self._lane_outcome(reviewed, "observed")
        overall = self._overall_outcome(formal, observed)
        gaps = self._gaps(reviewed)
        related = tuple(self.graph.related_qualifiers(fact_id))
        confidence = self._confidence(reviewed, overall, gaps)
        summary = self._summary(formal, observed, overall, confidence, reviewed, related)
        return FactAssessment(
            fact_id=fact_id,
            statement=str(fact.attributes.get("statement", fact.label)),
            category=str(fact.attributes.get("category", "uncategorised")),
            formal_outcome=formal,
            observed_outcome=observed,
            overall_outcome=overall,
            confidence=confidence,
            summary=summary,
            evidence=reviewed,
            gaps=tuple(gaps),
            related_qualifiers=related,
            rules_applied=(
                "GCF1_APPLICABILITY_GATE",
                "GCF2_SOURCE_AUTHORITY_BACKBONE_CHECK",
                "GCF3_LIFECYCLE_STATUS",
                "GCF4_EFFECTIVE_DATE",
                "GCF5_INDEPENDENCE_AND_CORROBORATION",
                "GCF6_FORMAL_OBSERVED_SEPARATION",
                "GCF7_MISSINGNESS_IS_NOT_CONTRADICTION",
            ),
        )

    def _evaluate_edge(
        self,
        edge: GraphEdge,
        *,
        as_of: date,
        duplicate_counts: dict[str, int],
        corroboration_counts: dict[tuple[str, str], set[str]],
    ) -> EdgeAssessment:
        document = self.graph.document(edge.source)
        attributes = document.attributes
        edge_attributes = edge.attributes
        status = str(attributes.get("status", "unknown"))
        source_class = str(attributes.get("source_class", "unknown"))
        applicable = bool(edge_attributes.get("applicable", True)) and bool(
            edge_attributes.get("scope_match", True)
        )
        limitations: list[str] = []
        trace: list[str] = []
        if not applicable:
            limitations.append("The attestation does not match the Fact's scope or conditions.")
            return EdgeAssessment(
                edge_id=edge.edge_id,
                document_id=document.node_id,
                document_title=document.label,
                mode=edge.relationship.lower(),
                attests_value=str(edge_attributes["attests_value"]),
                stance=self._stance(edge),
                source_class=source_class,
                lifecycle_status=status,
                applicable=False,
                materiality_score=None,
                material=False,
                dimensions={},
                limitations=tuple(limitations),
                trace=("Applicability gate failed; evidence retained but not scored.",),
            )

        backbone_factor, backbone_trace = self.graph.backbone_resolution(edge)
        authority_base = self.config.source_class_weights.get(source_class, 0.4)
        authority = authority_base * backbone_factor
        trace.append(f"Source: {source_class} authority={authority_base:.2f}. {backbone_trace}")

        approval = self.config.approval_weights.get(
            str(attributes.get("approval_status", "unknown")), 0.5
        )
        lifecycle = self.config.lifecycle_multipliers.get(status, 0.5)
        trace.append(
            f"Status: {status} lifecycle multiplier={lifecycle:.2f}; approval={approval:.2f}."
        )

        recency, recency_note = self._recency(document, as_of)
        trace.append(f"Date: {recency_note} value={recency:.2f}.")

        group = str(attributes.get("duplicate_group") or document.node_id)
        independence = 1.0 / duplicate_counts[group]
        stance = self._stance(edge)
        corroborating_origins = len(
            corroboration_counts.get((edge.relationship.lower(), stance), set())
        )
        corroboration = (
            0.5
            if corroborating_origins <= 1
            else min(1.0, 0.5 + 0.25 * (corroborating_origins - 1))
        )
        if independence < 1:
            limitations.append("A duplicate source exists and is not counted as independent.")
        if corroborating_origins <= 1:
            limitations.append("No independent source corroborates this stance in the same lane.")

        dimensions = {
            "source_authority": authority,
            "approval_status": approval,
            "version_recency": recency,
            "directness": float(edge_attributes.get("directness", 0.5)),
            "specificity": float(edge_attributes.get("specificity", 0.5)),
            "corroboration": corroboration,
            "source_independence": independence,
            "evidence_completeness": float(edge_attributes.get("completeness", 0.5)),
        }
        total_weight = sum(self.config.dimension_weights.values())
        weighted_average = (
            sum(
                dimensions[name] * self.config.dimension_weights[name]
                for name in CREDIBILITY_DIMENSIONS
            )
            / total_weight
        )
        score = weighted_average * lifecycle * max(authority, 0.1)
        material = score >= self.config.materiality_threshold
        if edge_attributes.get("gap"):
            limitations.append(str(edge_attributes["gap"]))
        trace.append(
            "Materiality: weighted dimensions "
            f"{weighted_average:.3f} × lifecycle {lifecycle:.2f} × authority "
            f"{max(authority, 0.1):.2f} = {score:.3f}."
        )
        return EdgeAssessment(
            edge_id=edge.edge_id,
            document_id=document.node_id,
            document_title=document.label,
            mode=edge.relationship.lower(),
            attests_value=str(edge_attributes["attests_value"]),
            stance=stance,
            source_class=source_class,
            lifecycle_status=status,
            applicable=True,
            materiality_score=score,
            material=material,
            dimensions=dimensions,
            limitations=tuple(limitations),
            trace=tuple(trace),
        )

    def _recency(self, document: GraphNode, as_of: date) -> tuple[float, str]:
        start_text = document.attributes.get("effective_date")
        end_text = document.attributes.get("effective_end_date")
        updated_text = document.attributes.get("last_updated")
        if start_text and date.fromisoformat(str(start_text)) > as_of:
            return 0.0, "document was not yet effective"
        if end_text and date.fromisoformat(str(end_text)) < as_of:
            return self.config.stale_weight, "document was no longer effective"
        if not start_text and not updated_text:
            return (
                self.config.undated_weight,
                "no effective or updated date was available",
            )
        anchor = date.fromisoformat(str(updated_text or start_text))
        age_years = max(0.0, (as_of - anchor).days / 365.25)
        if age_years > self.config.recency_years:
            return self.config.stale_weight, f"source was {age_years:.1f} years old"
        return 1.0, "source aligned with the assessment date"

    @staticmethod
    def _stance(edge: GraphEdge) -> str:
        agrees = edge.attributes.get("agrees")
        if agrees is True:
            return "support"
        if agrees is False:
            return "contradict"
        return "qualify"

    def _lane_outcome(self, reviewed: tuple[EdgeAssessment, ...], mode: str) -> str:
        material = [item for item in reviewed if item.mode == mode and item.material]
        support = sum(item.materiality_score or 0 for item in material if item.stance == "support")
        contradict = sum(
            item.materiality_score or 0 for item in material if item.stance == "contradict"
        )
        if not support and not contradict:
            return "Insufficient evidence"
        if support and contradict:
            ratio = min(support, contradict) / max(support, contradict)
            if ratio >= self.config.conflict_ratio:
                return "Contested"
        return "Supported" if support > contradict else "Contradicted"

    @staticmethod
    def _overall_outcome(formal: str, observed: str) -> str:
        decisive = [item for item in (formal, observed) if item != "Insufficient evidence"]
        if not decisive:
            return "Insufficient evidence"
        if "Contested" in decisive or len(set(decisive)) > 1:
            return "Contested"
        return decisive[0]

    def _gaps(self, reviewed: tuple[EdgeAssessment, ...]) -> list[str]:
        gaps = []
        if not reviewed:
            gaps.append("No Document or structured row attests to this Fact.")
        for mode in ("formal", "observed"):
            decisive = [
                item
                for item in reviewed
                if item.mode == mode and item.material and item.stance in {"support", "contradict"}
            ]
            if not decisive:
                gaps.append(f"No material {mode} attestation resolves the asserted value.")
        for item in reviewed:
            for limitation in item.limitations:
                if "missing" in limitation.casefold() or "no linked" in limitation.casefold():
                    gaps.append(limitation)
        return list(dict.fromkeys(gaps))

    @staticmethod
    def _confidence(reviewed: tuple[EdgeAssessment, ...], overall: str, gaps: list[str]) -> str:
        decisive = [
            item for item in reviewed if item.material and item.stance in {"support", "contradict"}
        ]
        non_material_divergence = any(
            item.applicable and not item.material and item.stance == "contradict"
            for item in reviewed
        )
        if overall == "Insufficient evidence":
            return "Lower confidence"
        if overall == "Contested" or non_material_divergence or gaps:
            return "Moderate confidence"
        independent_documents = {item.document_id for item in decisive}
        return "Higher confidence" if len(independent_documents) >= 2 else "Moderate confidence"

    @staticmethod
    def _summary(
        formal: str,
        observed: str,
        overall: str,
        confidence: str,
        reviewed: tuple[EdgeAssessment, ...],
        related: tuple[str, ...],
    ) -> str:
        divergence = [item for item in reviewed if item.stance == "contradict" and item.applicable]
        parts = [
            f"Formal evidence: {formal}.",
            f"Observed evidence: {observed}.",
            f"Combined outcome: {overall}; {confidence.lower()}.",
        ]
        if divergence:
            parts.append(
                "Practice divergence is retained in the trace even where its source weight is "
                "not decisive."
            )
        if related:
            parts.append("Related Facts narrow the scope and are reported as qualifications.")
        return " ".join(parts)
