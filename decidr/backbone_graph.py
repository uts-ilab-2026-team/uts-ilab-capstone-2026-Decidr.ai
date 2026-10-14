"""Build the persistent organisational backbone (the skeleton) from the corpus.

Produces a validated :class:`framework.graph.OrganisationalGraph` containing
everything EXCEPT Fact nodes and FORMAL/OBSERVED attestation edges:

* ``document`` nodes + ``SUPERSEDED_BY`` / ``RELATED`` — reused directly from
  ``decidr.ingestion`` (no re-parsing of document metadata).
* ``person`` / ``role`` / ``function`` / ``process`` / ``system`` nodes and the
  backbone edges ``HOLDS`` / ``SITS_IN`` / ``REPORTS_TO`` / ``PARTICIPATES_IN`` /
  ``ACCESSES`` / ``GOVERNS`` — parsed deterministically from the clean markdown
  tables in ``data/00_overview/``.

Design note: this module lives in ``decidr/`` (not ``framework/``) because it
imports ``decidr.ingestion``. ``framework/`` only ever *loads* the graph. The
in-memory :class:`OrganisationalGraph` is the spine; the JSON dump is an
optional, inspectable snapshot (for review + demo).

Decision rights / "who approves what" are deliberately NOT encoded here — they
are per-claim evidence (the FORMAL/OBSERVED overlay), not structural identity.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
import json
from pathlib import Path
import re

from framework.graph import OrganisationalGraph
from framework.models import GraphEdge, GraphNode

from decidr.constants import (
    CORPUS_GRAPH_PATH as OUTPUT_PATH,  # re-exported for existing importers
)
from decidr.constants import (
    DATA_DIR,  # re-exported for existing importers
)
from decidr.ingestion import ingest
from decidr.retrieval_models import Source

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


# --------------------------------------------------------------------------- #
# Document layer (reused from ingestion — no document metadata is re-parsed)   #
# --------------------------------------------------------------------------- #


def _document_node_id(source_id: str) -> str:
    code = source_id.split(":", 1)[1] if ":" in source_id else source_id
    return f"document:{code}"


def _add_documents(builder: _GraphBuilder, sources: list[Source]) -> dict[str, str]:
    """Add one ``document`` node per usable source; return source_id -> node_id."""
    id_map: dict[str, str] = {}
    for source in sources:
        if source.ingestion_status == "excluded":
            continue
        if source.source_type in {"technical", "annotation"}:
            continue
        node_id = _document_node_id(source.source_id)
        id_map[source.source_id] = node_id
        attributes = {
            "source_id": source.source_id,
            "status": source.lifecycle_status or "unknown",
            "source_class": SOURCE_CLASS_BY_TYPE.get(source.source_type, "unknown"),
            "approval_status": _approval_key(
                source.approval_status, source.lifecycle_status or ""
            ),
            "duplicate_group": source.duplicate_group or node_id,
        }
        for key, value in (
            ("effective_date", _iso(source.effective_start_date)),
            ("effective_end_date", _iso(source.effective_end_date)),
            ("superseded_date", _iso(source.superseded_date)),
            ("last_updated", _iso(source.last_updated_date)),
        ):
            if value is not None:
                attributes[key] = value
        builder.add_node(node_id, "document", source.title, attributes)
    return id_map


def _add_supersession_and_related(
    builder: _GraphBuilder, sources: list[Source], id_map: dict[str, str]
) -> None:
    # document code (e.g. "POL-06") -> node id, to resolve stated "Related documents" references.
    node_by_code = {
        (source_id.split(":", 1)[1] if ":" in source_id else source_id): node_id
        for source_id, node_id in id_map.items()
    }
    for source in sources:
        if source.source_id not in id_map:
            continue
        old_id = id_map[source.source_id]
        # successor_source_id is set on the OLD document; edge is old -> new.
        successor = getattr(source, "successor_source_id", None)
        if successor and successor in id_map:
            builder.add_edge(old_id, id_map[successor], "SUPERSEDED_BY")
        for match in re.finditer(
            r"near_duplicate_candidate=([^:;]+:[^:;]+):", source.metadata_notes or ""
        ):
            other = match.group(1)
            if other in id_map:
                a, b = sorted((source.source_id, other))
                builder.add_edge(
                    id_map[a],
                    id_map[b],
                    "RELATED",
                    {"reason": "near-duplicate content (ingestion)"},
                )
        # Stated "Related documents:" links, emitted in the direction the document declares them.
        for related_code in getattr(source, "related_source_codes", []):
            target_id = node_by_code.get(related_code)
            if target_id and target_id != old_id:
                builder.add_edge(
                    old_id,
                    target_id,
                    "RELATED",
                    {"reason": "stated related document (header metadata)"},
                )


def _add_governs(
    builder: _GraphBuilder, id_map: dict[str, str], process_ids: dict[str, str]
) -> None:
    for source_id, node_id in id_map.items():
        code = source_id.split(":", 1)[1] if ":" in source_id else source_id
        process_code = PROCESS_BY_DOCUMENT_CODE.get(code)
        if process_code and process_code in process_ids:
            builder.add_edge(node_id, process_ids[process_code], "GOVERNS")


def _add_owned_by(builder: _GraphBuilder, sources: list[Source], id_map: dict[str, str]) -> None:
    """Emit OWNED_BY (document -> owning PERSON), stated as-is from the header.

    The owner is the named person in the document header ("Harriet Doyle, Head of Finance & People
    Ops" -> person:harriet-doyle). This is deliberately a Document->Person edge: the document OWNER
    is a different thing from the decision-right HOLDER (a role). Documents with no named person
    owner (e.g. PROC-07 "Jointly maintained by Sales and CS&D") get no edge -- a meaningful absence,
    not an error. Graph structure only: no scorer reads OWNED_BY.
    """
    for source in sources:
        node_id = id_map.get(source.source_id)
        owner = source.responsible_person_or_role
        if node_id is None or not owner:
            continue
        name = owner.split(",", 1)[0].strip()
        person_id = f"person:{_slug(name)}"
        person = builder.nodes.get(person_id)
        if person is not None and person.kind == "person":
            # Record whether the owner is still active: a document owned by someone who has left
            # may be unmaintained. Graph-structure signal only (no scorer reads it).
            owner_active = person.attributes.get("status") == "active"
            builder.add_edge(
                node_id,
                person_id,
                "OWNED_BY",
                {"reason": "document owner (header metadata)", "owner_active": owner_active},
            )
            if not owner_active:
                builder.warnings.append(
                    f"document owner no longer active: {source.source_id} -> {name!r}"
                )
        elif name:
            builder.warnings.append(
                f"document owner not in roster: {source.source_id} -> {name!r}"
            )


# --------------------------------------------------------------------------- #
# Backbone layer (parsed from the clean markdown tables)                       #
# --------------------------------------------------------------------------- #


def _table_rows(text: str, header_must_contain: str) -> list[list[str]]:
    """Return cell lists for a single GitHub markdown table matching the header."""
    rows: list[list[str]] = []
    capturing = False
    for line in text.splitlines():
        stripped = line.strip()
        if not capturing:
            if stripped.startswith("|") and header_must_contain in stripped:
                capturing = True
            continue
        if not stripped.startswith("|"):
            break
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if all(set(cell) <= {"-", ":", " "} for cell in cells):
            continue  # separator row
        rows.append(cells)
    return rows


def _add_processes(builder: _GraphBuilder, overview_text: str) -> dict[str, str]:
    """Create the 8 process nodes from the company-overview table. Returns code -> node_id."""
    process_ids: dict[str, str] = {}
    for cells in _table_rows(overview_text, "Process"):
        if len(cells) < 2:
            continue
        code_match = PROCESS_CODE_PATTERN.fullmatch(cells[0].strip())
        if not code_match:
            continue
        code = cells[0].strip()
        node_id = f"process:{code.casefold()}"
        builder.add_node(node_id, "process", f"{code} {cells[1]}", {"code": code})
        process_ids[code] = node_id
    return process_ids


def _add_roster(builder: _GraphBuilder, roster_text: str) -> tuple[dict[str, str], dict[str, str]]:
    """Parse the staff roster table. Returns (person_name -> role_id, role_label -> role_id)."""
    inactive = {
        match.group("name").strip()
        for line in roster_text.splitlines()
        if (match := LEFT_COMPANY_PATTERN.match(line.strip()))
    }
    name_to_role: dict[str, str] = {}
    role_by_label: dict[str, str] = {}
    name_to_person: dict[str, str] = {}
    pending_reports: list[tuple[str, str]] = []  # (person_name, manager_name)

    for cells in _table_rows(roster_text, "Employee"):
        if len(cells) < 4:
            continue
        name, function_name, role_name, reports_to = cells[0], cells[1], cells[2], cells[3]
        start = cells[4] if len(cells) > 4 else ""
        if not name or not role_name:
            continue
        person_id = f"person:{_slug(name)}"
        role_id = f"role:{_slug(role_name)}"
        function_id = f"function:{_slug(function_name)}"
        date_match = re.search(r"\d{4}-\d{2}-\d{2}", start)
        person_attrs = {"status": "inactive" if name in inactive else "active"}
        if date_match:
            person_attrs["start_date"] = date_match.group()
        builder.add_node(person_id, "person", name, person_attrs)
        builder.add_node(role_id, "role", role_name, {})
        builder.add_node(function_id, "function", function_name, {})
        builder.add_edge(person_id, role_id, "HOLDS")
        builder.add_edge(role_id, function_id, "SITS_IN")
        name_to_role[name] = role_id
        name_to_person[name] = person_id
        role_by_label[role_name] = role_id
        if reports_to and reports_to.casefold() != "board":
            pending_reports.append((name, reports_to))

    for name, manager in pending_reports:
        self_role = name_to_role.get(name)
        manager_role = name_to_role.get(manager)
        if self_role and manager_role and self_role != manager_role:
            builder.add_edge(self_role, manager_role, "REPORTS_TO")
        elif manager not in name_to_role:
            builder.warnings.append(f"reports-to manager not in roster: {name!r} -> {manager!r}")
    return name_to_role, role_by_label


def _resolve_role(role_name: str, role_by_label: dict[str, str]) -> str | None:
    """Match a role-description heading to a roster role (handles minor variants)."""
    if role_name in role_by_label:
        return role_by_label[role_name]
    target = _slug(role_name)
    for label, role_id in role_by_label.items():
        candidate = _slug(label)
        if candidate == target or candidate.startswith(target) or target.startswith(candidate):
            return role_id
        # "Product Managers" -> "Product Manager"; "CEO / Founder" -> "CEO"
        if candidate.rstrip("s") == target.rstrip("s"):
            return role_id
    return None


def _add_role_descriptions(
    builder: _GraphBuilder,
    roles_text: str,
    role_by_label: dict[str, str],
    process_ids: dict[str, str],
) -> None:
    """Add ACCESSES (role->system) and PARTICIPATES_IN (role->process) from role descriptions."""
    current_role_id: str | None = None
    for line in roles_text.splitlines():
        heading = re.match(r"^##\s+(?P<name>.+?)\s*[—–-]\s*.+$", line)
        if heading:
            current_role_id = _resolve_role(heading.group("name").strip(), role_by_label)
            if current_role_id is None:
                builder.warnings.append(
                    f"role-description heading unmatched: {heading.group('name')!r}"
                )
            continue
        if current_role_id is None:
            continue
        systems = re.match(r"^- \*\*Systems accessed:\*\*\s*(?P<value>.+)$", line)
        if systems:
            for raw in systems.group("value").split(","):
                name = re.sub(r"\(.*?\)", "", raw).strip().rstrip(".")
                if not name or name.casefold().startswith("all "):
                    continue
                system_id = f"system:{_slug(name)}"
                builder.add_node(system_id, "system", name, {})
                builder.add_edge(current_role_id, system_id, "ACCESSES")
            continue
        participation = re.match(r"^- \*\*Process participation:\*\*\s*(?P<value>.+)$", line)
        if participation:
            for code_num in PROCESS_CODE_PATTERN.findall(participation.group("value")):
                process_id = process_ids.get(f"P{code_num}")
                if process_id:
                    builder.add_edge(current_role_id, process_id, "PARTICIPATES_IN")


# --------------------------------------------------------------------------- #
# Public API                                                                   #
# --------------------------------------------------------------------------- #


def build_corpus_graph(
    data_dir: Path = DATA_DIR, *, release: str = "phase1"
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


if __name__ == "__main__":
    main()
