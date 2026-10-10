"""Document-scoped header evidence and conservative metadata constraints."""

from datetime import date
from pathlib import Path
import re

METADATA_VERSION = "document-metadata-v1"
HEADER = re.compile(r"^- \*\*(?P<key>[^*]+):\*\*\s*(?P<value>.*)$")
DOCUMENT_REFERENCE = re.compile(r"\b[A-Z][A-Z0-9]*-\d+\b")


def read_header(path: Path) -> tuple[str, dict, list, list]:
    """Keep exact lines/character offsets; never read metadata from body sections."""
    title = path.stem
    entries, conflicts = [], []
    offset = 0
    seen_title = False
    with path.open(encoding="utf-8-sig", newline="") as handle:
        lines = handle.read().splitlines(True)
    for number, raw in enumerate(lines, 1):
        line = raw.rstrip("\r\n")
        if re.match(r"^#{1,6}\s", line):
            if seen_title or not line.startswith("# "):
                break
            title = line[2:].strip()
            seen_title = True
            offset += len(raw)
            continue
        match = HEADER.match(line)
        if match:
            entries.append(
                {
                    "key": match["key"].strip().casefold(),
                    "value": match["value"],
                    "quote": line,
                    "line": number,
                    "start": offset,
                    "end": offset + len(line),
                    "scope": "document_header",
                    "references": DOCUMENT_REFERENCE.findall(match["value"]),
                }
            )
        elif line.strip():
            break  # Ordinary prose/fences end the opening header, even without a heading.
        offset += len(raw)
    metadata = {}
    for key in dict.fromkeys(e["key"] for e in entries):
        values = list(dict.fromkeys(e["value"].strip() for e in entries if e["key"] == key))
        if len(values) == 1:
            metadata[key] = values[0]
        else:
            conflicts.append(
                {
                    "field": key.replace(" ", "_"),
                    "values": values,
                    "reason": "Conflicting repeated header fields; no value selected.",
                }
            )
    return title, metadata, entries, conflicts


def approval_lifecycle(value: str | None, code: str) -> tuple[str | None, list, list]:
    """Attribute approval clauses to this document or an explicit reference.

    Unrecognised/ambiguous clauses remain reviewable; no document-ID exceptions.
    """
    if not value:
        return None, [], []
    clauses, conflicts, states = [], [], set()
    for match in re.finditer(r"\([^)]*\)|[^()]+", value):
        for part in re.finditer(r".+?(?:[.;](?=\s)|$)", match[0], re.DOTALL):
            quote = part[0]
            start = match.start() + part.start()
            lower = quote.casefold()
            # A 'see' tail is a reference even when the preceding status is local.
            see = re.search(r"\bsee\s+", lower)
            if see and see.start() > 1:
                local = quote[: see.start()]
                tail = quote[see.start() :]
                pieces = [(local, start), (tail, start + see.start())]
            else:
                pieces = [(quote, start)]
            for text, pos in pieces:
                refs = DOCUMENT_REFERENCE.findall(text)
                external = [ref for ref in refs if ref != code]
                lower = text.casefold()
                reference_clause = re.match(r"^\s*\(?\s*(?:see|refer to)\b", lower)
                scope = "referenced_document" if external or reference_clause else "own_document"
                negative = bool(
                    re.search(r"\b(?:not\s+(?:formally\s+)?approved|unapproved|draft)\b", lower)
                )
                positive = bool(
                    re.search(
                        r"\bapproved\b", re.sub(r"\bnot\s+(?:formally\s+)?approved\b", "", lower)
                    )
                )
                state = "draft" if negative else "current" if positive else None
                if re.search(r"\b(?:superseded|no longer in force|withdrawn)\b", lower):
                    state = "superseded" if "withdrawn" not in lower else "withdrawn"
                    positive = False  # Historical approval is compatible with supersession.
                clauses.append(
                    {
                        "quote": text,
                        "start": pos,
                        "end": pos + len(text),
                        "scope": scope,
                        "references": refs,
                        "lifecycle": state,
                    }
                )
                if scope == "own_document":
                    if state:
                        states.add(state)
                    if negative and positive:
                        states.add("current")
    if "superseded" in states or "withdrawn" in states:
        states.discard("current")  # Approval and later retirement are compatible.
    if len(states) > 1:
        conflicts.append(
            {
                "field": "lifecycle_status",
                "values": sorted(states),
                "reason": "Conflicting approval assertions about this document.",
            }
        )
    if not states:
        conflicts.append(
            {
                "field": "lifecycle_status",
                "values": [value],
                "reason": "No resolved approval assertion about this document.",
            }
        )
    return (next(iter(states)) if len(states) == 1 else "unknown"), clauses, conflicts


def header_date(metadata: dict, key: str, conflicts: list) -> date | None:
    """Accept one leading ISO date, never a date inside a document reference."""
    raw = metadata.get(key)
    if not raw:
        return None
    matches = re.findall(r"\b\d{4}-\d{2}-\d{2}\b", raw)
    if not matches:
        return None
    if len(set(matches)) == 1 and raw.startswith(matches[0]):
        try:
            return date.fromisoformat(matches[0])
        except ValueError:
            pass
    conflicts.append(
        {
            "field": key.replace(" ", "_"),
            "values": [raw],
            "reason": "Invalid, multiple or non-local date; no date selected.",
        }
    )
    return None


def metadata_constraint(source: dict, start: date, end: date) -> tuple[str | None, list[str]]:
    """Additional constraints, not proof of applicability. Boundary equality is unknown.

    Legacy snapshots without the new fields keep their original behaviour.
    """
    temporal_fields = {
        "lifecycle_status",
        "approval_status",
        "effective_date",
        "superseded_date",
        "effective_start_date",
        "effective_end_date",
        "supersession",
        "date",
        "interview_date",
    }
    if any(c["field"] in temporal_fields for c in source.get("metadata_conflicts", [])):
        return "unknown", ["Unresolved source metadata conflict; temporal applicability unknown."]
    if source.get("metadata_version") and source.get("lifecycle_status") in {"draft", "withdrawn"}:
        return "no", ["Document's own lifecycle is draft or withdrawn."]
    superseded = source.get("superseded_date")
    if superseded:
        boundary = date.fromisoformat(superseded)
        if end > boundary:
            return "no", ["Assessed period extends beyond the documented superseded date."]
        if end == boundary:
            return "unknown", ["Superseded-date boundary inclusion is unspecified."]
    return None, []
