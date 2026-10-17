"""Shared backbone primitives: patterns, lookups, helpers, and the graph builder."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import re

from decidr.graph.models import GraphEdge, GraphNode

PROCESS_CODE_PATTERN = re.compile(r"\bP([1-8])\b")
LEFT_COMPANY_PATTERN = re.compile(
    r"^(?P<name>[A-Z][\w .'-]+?) left Northfield on (\d{4}-\d{2}-\d{2})"
)

# source_type (from ingestion) -> framework source_class config key.
# Best-effort for the skeleton; the per-claim shim (Phase 2, §7.3) may refine
# these when it attaches attestations. Document scoring only happens via the
# overlay, so an approximate class here does not change any Phase 1 outcome.
SOURCE_CLASS_BY_TYPE = {
    "policy": "approved_policy",
    "procedure": "approved_process",
    "interview": "interview",
    "meeting": "meeting_record",
    "internal_communication": "self_reported_communication",
    "crm_records": "structured_operational_record",
    "audit_events": "system_verified",
    "project_tasks": "structured_operational_record",
    "organisational_information": "role_description",
}

# Document codes -> process code (P1..P8). Derived from the titles, which are
# explicit. POL-05 (data handling) and POL-08 map by topic; anything absent here
# simply gets no GOVERNS edge.
PROCESS_BY_DOCUMENT_CODE = {
    "POL-01": "P1",
    "PROC-02": "P1",
    "POL-03": "P2",
    "PROC-01": "P2",
    "PROC-03": "P3",
    "POL-07": "P4",
    "PROC-04": "P4",
    "POL-04": "P5",
    "PROC-05": "P5",
    "POL-08": "P6",
    "PROC-06": "P7",
    "POL-06": "P8",
    "PROC-07": "P8",
}


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _approval_key(raw: str | None, lifecycle: str) -> str:
    """Map a raw approval-status header to a framework ``approval_weights`` key.

    Only the LEADING status clause is classified — the text before the first sentence/clause break
    (``. ( — , ;`` or newline). Status headers are written as "<status>. <explanation>" or
    "<status> (<note>)", and the explanation often mentions a DIFFERENT document's state
    (e.g. PROC-05: "Approved. … (See POL-04 for an unapproved draft revision.)"). Classifying the
    whole string would let that note's "unapproved" flip an approved document. The leading clause is
    this document's own status.
    """
    if lifecycle == "superseded":
        return "superseded"
    if not raw:
        return "unknown"
    head = re.split(r"[.(,;\n—-]", raw.casefold(), maxsplit=1)[0].strip()
    if "not approved" in head or "unapproved" in head:
        return "unapproved"
    if "approved" in head:
        return "approved"
    if "draft" in head:
        return "draft"
    return "unknown"


@dataclass(slots=True)
class _GraphBuilder:
    """Accumulates nodes/edges, de-duplicating by id, before validation."""

    nodes: dict[str, GraphNode] = field(default_factory=dict)
    edges: dict[str, GraphEdge] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    _seen_edges: set[tuple[str, str, str]] = field(default_factory=set)

    def add_node(self, node_id: str, kind: str, label: str, attributes: dict | None = None) -> str:
        if node_id not in self.nodes:
            self.nodes[node_id] = GraphNode(node_id, kind, label, attributes or {})
        return node_id

    def add_edge(
        self, source: str, target: str, relationship: str, attributes: dict | None = None
    ) -> None:
        signature = (relationship, source, target)
        if signature in self._seen_edges:
            return
        self._seen_edges.add(signature)
        edge_id = f"{relationship.lower()}:{source}->{target}"
        self.edges[edge_id] = GraphEdge(edge_id, source, target, relationship, attributes or {})
