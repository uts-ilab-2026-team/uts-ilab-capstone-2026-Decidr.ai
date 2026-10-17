"""Document-layer backbone: document nodes, supersession/related, governs, owned-by."""

from __future__ import annotations

import re

from decidr.backbone.common import (
    PROCESS_BY_DOCUMENT_CODE,
    SOURCE_CLASS_BY_TYPE,
    _approval_key,
    _GraphBuilder,
    _iso,
    _slug,
)
from decidr.corpus.models import Source

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
