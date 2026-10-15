"""Faithful evidence extraction from Markdown blocks and CSV rows."""

from collections import Counter
import csv
import json
from pathlib import Path
import re

from decidr.ingestion.helpers import HEADING_PATTERN, _evidence_id, _parse_date
from decidr.retrieval_models import Evidence, Source


def extract_markdown(source: Source, path: Path) -> list[Evidence]:
    """Extract paragraphs/list/table rows with heading-based stable locators."""
    units: list[Evidence] = []
    headings: list[str] = []
    section_counts: Counter[str] = Counter()
    buffer: list[str] = []

    def emit() -> None:
        nonlocal buffer
        text = "\n".join(buffer).strip()
        buffer = []
        if not text:
            return
        # Standalone Markdown separators are layout, not evidence.
        if all(
            re.fullmatch(r"[ \t]*([-*_])(?:[ \t]*\1){2,}[ \t]*", line)
            for line in text.splitlines()
        ):
            return
        section = " > ".join(headings) if headings else "document"
        section_counts[section] += 1
        locator = f"heading:{section}#block:{section_counts[section]:03d}"
        units.append(
            Evidence(
                evidence_id=_evidence_id(source.source_id, locator),
                source_id=source.source_id,
                locator=locator,
                text=text,
                source_type=source.source_type,
                section=section,
                heading=headings[-1] if headings else None,
                paragraph=section_counts[section],
                version=source.version,
                extraction_method="markdown_heading_blocks_v1",
                structured_metadata={"release": source.source_id.split(":", 1)[0]},
            )
        )

    in_fence = False
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.rstrip()
        if line.startswith("```"):
            in_fence = not in_fence
            buffer.append(line)
            continue
        heading = None if in_fence else HEADING_PATTERN.match(line)
        if heading:
            emit()
            level = len(heading.group("level"))
            headings[:] = headings[: level - 1]
            headings.append(heading.group("title").strip())
        elif not line.strip():
            emit()
        else:
            buffer.append(line)
    emit()
    return units


def _csv_value(row: dict[str, str], field: str) -> str | None:
    """Return a non-empty CSV value without inventing missing metadata."""
    value = row.get(field)
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _csv_context(
    source: Source,
    row: dict[str, str],
) -> tuple[dict[str, str | None], dict[str, str]]:
    """Map explicit structured fields into the shared Evidence context schema."""
    context: dict[str, str | None] = {
        "process": None,
        "actor": None,
        "role": None,
        "system": None,
    }
    provenance: dict[str, str] = {}

    if source.source_type == "project_tasks":
        mappings = {
            "process": "process_or_capability",
            "actor": "owner_name",
            "role": "owner_role",
        }
        for target, field in mappings.items():
            value = _csv_value(row, field)
            if value:
                context[target] = value
                provenance[target] = f"direct:csv_column:{field}"
        context["system"] = "Project System"
        provenance["system"] = "inferred:source_type:project_tasks"

    elif source.source_type == "audit_events":
        mappings = {
            "actor": "actor_name",
            "role": "actor_role",
            "system": "system",
        }
        for target, field in mappings.items():
            value = _csv_value(row, field)
            if value:
                context[target] = value
                provenance[target] = f"direct:csv_column:{field}"

    elif source.source_type == "crm_records":
        actor = _csv_value(row, "ae_owner")
        if actor:
            context["actor"] = actor
            provenance["actor"] = "direct:csv_column:ae_owner"
        role = _csv_value(row, "approval_role")
        if role:
            context["role"] = role
            provenance["role"] = "direct:csv_column:approval_role"
        context["system"] = "CRM"
        provenance["system"] = "inferred:source_type:crm_records"

    return context, provenance


def extract_csv(source: Source, path: Path) -> list[Evidence]:
    """Extract one faithful evidence unit per CSV record."""
    units: list[Evidence] = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("CSV has no header")
        identifier_field = reader.fieldnames[0]
        for row_number, row in enumerate(reader, start=2):
            row_identifier = (row.get(identifier_field) or f"row-{row_number}").strip()
            locator = f"csv:row:{row_number};{identifier_field}:{row_identifier}"
            faithful = json.dumps(row, ensure_ascii=False, sort_keys=True)
            relevant_dates = [_parse_date(value) for value in row.values()]
            relevant_dates = [value for value in relevant_dates if value]
            context, field_mapping = _csv_context(source, row)
            units.append(
                Evidence(
                    evidence_id=_evidence_id(source.source_id, locator),
                    source_id=source.source_id,
                    locator=locator,
                    text=faithful,
                    source_type=source.source_type,
                    row_identifier=row_identifier,
                    process=context["process"],
                    actor=context["actor"],
                    role=context["role"],
                    system=context["system"],
                    relevant_start_date=min(relevant_dates) if relevant_dates else None,
                    relevant_end_date=max(relevant_dates) if relevant_dates else None,
                    extraction_method="csv_dict_row_v1",
                    structured_metadata={
                        "row_number": row_number,
                        "record": row,
                        "field_mapping": field_mapping,
                    },
                )
            )
    return units
