"""Deterministic event-date admission check (first cut).

For a ``target: event`` claim that asserts a date (e.g. "DEAL-014 closed on 2 July 2025"),
compare the claim's asserted date against the matching field of a *structured* record passage
(e.g. a CRM row's ``close_date``). When the record positively states a date that does not
satisfy the claim's asserted date under its stated operator (on / before / after / by), return
a human-readable reason. The reader uses that reason to demote the finding from ``supports`` to
``context`` — so an authoritative record can no longer "support" a claim whose date it actually
contradicts.

Scope of this first cut (deliberately narrow to avoid false positives):
  * acts ONLY when it can confidently extract exactly one dated mention from the claim AND a
    single matching date field from a structured (JSON) record; any ambiguity returns ``None``;
  * compares the claim's date against ONE record field (chosen by predicate). Ordering against a
    second event in the same record (e.g. "approval BEFORE close") is a separate, later step.

Worked example:
    claim predicate "closed", claim text "... closed on 2 July 2025 ..."  -> (eq, 2025-07-02)
    record {"close_date": "2025-07-05", ...}                              -> close_date 2025-07-05
    2025-07-05 == 2025-07-02 ? no -> returns a mismatch reason (finding demoted to context)
"""

from __future__ import annotations

from datetime import date
import json
import re

# Operators the claim's wording can imply, keyed by how we compare record (r) to claim (c).
_SATISFIES = {
    "eq": lambda r, c: r == c,
    "lt": lambda r, c: r < c,
    "le": lambda r, c: r <= c,
    "gt": lambda r, c: r > c,
    "ge": lambda r, c: r >= c,
}
_OP_PHRASE = {
    "eq": "on",
    "lt": "before",
    "le": "on or before",
    "gt": "after",
    "ge": "on or after",
}

_MONTHS = {
    name: index
    for index, group in enumerate(
        [
            ("january", "jan"),
            ("february", "feb"),
            ("march", "mar"),
            ("april", "apr"),
            ("may",),
            ("june", "jun"),
            ("july", "jul"),
            ("august", "aug"),
            ("september", "sep", "sept"),
            ("october", "oct"),
            ("november", "nov"),
            ("december", "dec"),
        ],
        start=1,
    )
    for name in group
}

_MONTH_ALT = "|".join(sorted(_MONTHS, key=len, reverse=True))
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
# "2 July 2025" / "2 Jul 2025"
_DMY = re.compile(rf"\b(\d{{1,2}})\s+({_MONTH_ALT})\.?\s+(\d{{4}})\b", re.IGNORECASE)
# "July 2, 2025" / "July 2 2025" / "July 2nd 2025"
_MDY = re.compile(
    rf"\b({_MONTH_ALT})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.IGNORECASE
)


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _iso_field_date(value: str) -> date | None:
    """Parse a record field value only if it is EXACTLY an ISO date (no partial matches)."""
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", value.strip())
    if not match:
        return None
    return _safe_date(int(match[1]), int(match[2]), int(match[3]))


def _operator_before(text: str, start: int) -> str:
    """Infer the comparison operator from the words immediately preceding a date mention.

    Scoped to a short window before the date so an unrelated word elsewhere in the claim (e.g.
    "without any prior approval") cannot leak into the date's operator.
    """
    lead = text[max(0, start - 28) : start].lower().rstrip()
    if re.search(r"(?:on or before|no later than|by)\s*$", lead):
        return "le"
    if re.search(r"(?:on or after|no earlier than)\s*$", lead):
        return "ge"
    if re.search(r"(?:before|prior to|earlier than)\s*$", lead):
        return "lt"
    if re.search(r"(?:after|later than|since)\s*$", lead):
        return "gt"
    return "eq"


def _dated_mentions(text: str) -> list[tuple[str, date]]:
    """All (operator, date) pairs found in free text across ISO / D-Mon-Y / Mon-D-Y forms."""
    found: list[tuple[str, date]] = []
    for match in _ISO.finditer(text):
        parsed = _safe_date(int(match[1]), int(match[2]), int(match[3]))
        if parsed:
            found.append((_operator_before(text, match.start()), parsed))
    for match in _DMY.finditer(text):
        parsed = _safe_date(int(match[3]), _MONTHS[match[2].lower()], int(match[1]))
        if parsed:
            found.append((_operator_before(text, match.start()), parsed))
    for match in _MDY.finditer(text):
        parsed = _safe_date(int(match[3]), _MONTHS[match[1].lower()], int(match[2]))
        if parsed:
            found.append((_operator_before(text, match.start()), parsed))
    return found


def _claim_date(component: dict) -> tuple[str, date] | None:
    """Exactly one distinct date asserted by the claim -> (operator, date); else None."""
    text = " ".join(
        str(component.get(key, ""))
        for key in ("temporal", "claim_quote", "text", "predicate")
    )
    mentions = _dated_mentions(text)
    distinct = {parsed for _op, parsed in mentions}
    if len(distinct) != 1:
        return None
    target = next(iter(distinct))
    # Use the operator of the first mention of that date.
    for operator, parsed in mentions:
        if parsed == target:
            return operator, target
    return None


def _record_date_fields(passage: dict) -> dict[str, date]:
    """Date-valued fields of a structured (JSON object) record passage; {} for prose/non-JSON."""
    try:
        obj = json.loads(passage.get("text", ""))
    except (ValueError, TypeError):
        return {}
    if not isinstance(obj, dict):
        return {}
    dated: dict[str, date] = {}
    for key, value in obj.items():
        parsed = _iso_field_date(value)
        if parsed is not None:
            dated[key] = parsed
    return dated


# Predicate verb -> the stem we expect in the matching record field name.
_FIELD_STEM = {
    "closed": "close",
    "close": "close",
    "won": "close",
    "signed": "sign",
    "effective": "effective",
    "approved": "approv",
    "created": "creat",
    "started": "start",
    "launched": "launch",
}


def _pick_field(fields: dict[str, date], predicate: str) -> str | None:
    """Choose the record date field matching the claim's predicate; unambiguous or None."""
    tokens = re.findall(r"[a-z]+", predicate.lower())
    wanted = {_FIELD_STEM.get(token, token) for token in tokens}
    matches = [key for key in fields if any(stem in key.lower() for stem in wanted)]
    if len(matches) == 1:
        return matches[0]
    if not matches and len(fields) == 1:
        return next(iter(fields))
    return None


def event_date_exclusion(component: dict, passage: dict) -> str | None:
    """Return a demotion reason if a structured record's date contradicts the claim's date.

    ``None`` means "no confident mismatch" — either the claim asserts no single date, the record
    is not a structured record with a matching date field, or the dates satisfy the claim's
    operator. The caller demotes a ``supports`` finding to ``context`` when a reason is returned.
    """
    claim = _claim_date(component)
    if claim is None:
        return None
    operator, claim_date = claim
    fields = _record_date_fields(passage)
    if not fields:
        return None
    field = _pick_field(fields, str(component.get("predicate", "")))
    if field is None:
        return None
    record_date = fields[field]
    if _SATISFIES[operator](record_date, claim_date):
        return None
    return (
        f"The record field '{field}' states {record_date.isoformat()}, which does not satisfy "
        f"the claim's asserted date ({_OP_PHRASE[operator]} {claim_date.isoformat()})."
    )
