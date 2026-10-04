"""Immutable data structures for the graph and its assessments.

These dataclasses are pure records: validated graph nodes and edges, and the
results of a credibility assessment.  They contain no reasoning logic.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


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
