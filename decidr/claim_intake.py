"""Lossless, deliberately bounded claim intake. No portfolio lookup or model calls."""

from datetime import date
import re
from typing import Literal
from uuid import uuid4

from pydantic import ConfigDict, Field

from decidr.models import AtomicClaim, EvidenceTarget, StrictModel

VERSION = "claim-intake-3"
# These are language patterns, not organisational facts or authorised roles.
VERB = re.compile(
    r"\b(must(?:\s+not)?|shall(?:\s+not)?|may(?:\s+not)?|cannot|can(?:\s+not)?|"
    r"does\s+not|do\s+not|did\s+not|is\s+not|are\s+not|was\s+not|were\s+not|"
    r"follows?|requires?|records?|recorded|shows?|showed|states?|stipulates?|"
    r"is|are|was|were|has|have|had)\b",
    re.IGNORECASE,
)
TARGETS = {
    "prescribed_rule": re.compile(
        r"\b(policy|policies|procedure|rule|must|shall|prescribed)\b",
        re.IGNORECASE,
    ),
    "actual_practice": re.compile(r"\b(in practice|actually|observed|routinely)\b", re.IGNORECASE),
    "recorded_state": re.compile(
        r"\b(records?|recorded|register|log|system field|crm)\b", re.IGNORECASE
    ),
}
DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
PROTECTED = re.compile(
    r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s+(?:weeks?|days?|hours?)\b|"
    r"\b\d{4}-\d{2}-\d{2}\b|(?:[<>]=?\s*)?\d+(?:\.\d+)?\s*(?:%|[A-Za-z]+)?|"
    r"\b(?:not|never|no|without|except|excluding|unless|only|at least|at most|"
    r"more than|less than|must|shall|may|cannot)\b",
    re.IGNORECASE,
)


class IntakePart(StrictModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    text: str
    start: int
    end: int
    status: Literal["awaiting_clarification", "awaiting_evidence_review"]
    claim: AtomicClaim | None = None
    clarification: str | None = None
    protected_values: list[dict] = Field(default_factory=list)
    provenance: dict = Field(default_factory=dict)


class Intake(StrictModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    original_wording: str
    parts: list[IntakePart]
    version: str = VERSION


def _spans(text: str) -> list[tuple[int, int]]:
    # Split only explicit sentence/semicolon boundaries or an independently stated
    # second subject+predicate. Shared-context coordination is retained for review.
    boundaries = list(re.finditer(r";\s*|(?<=[.!?])\s+(?=[A-Za-z])", text))
    if not boundaries:
        for match in re.finditer(r"\s+and\s+", text, re.IGNORECASE):
            right = text[match.end() :]
            verb = VERB.search(right)
            if verb and right[: verb.start()].strip() and VERB.search(text[: match.start()]):
                # A leading scope/condition could apply to both; do not invent its distribution.
                if re.search(
                    r"\b(if|when|unless|except|for|during|under)\b|,", text, re.IGNORECASE
                ):
                    return [(0, len(text))]
                boundaries.append(match)
    spans, start = [], 0
    for boundary in boundaries:
        spans.append((start, boundary.start()))
        start = boundary.end()
    spans.append((start, len(text)))
    return [(a, b) for a, b in spans if text[a:b].strip()]


def interpret_claim(wording: str, *, target: str | None = None) -> Intake:
    """Retain all text and extract only explicit bounded language structures.

    A target clarification adds context; it never rewrites the submitted proposition.
    Dates with ambiguous formats and unresolved coordination remain pending. All
    extracted fields are verbatim spans, and the complete object includes qualifiers.
    """
    if not wording.strip() or len(wording) > 6000:
        raise ValueError("Enter a claim of 1–6000 characters")
    if target is not None and target not in {*TARGETS, "all"}:
        raise ValueError("Unknown knowledge target")
    parts = []
    for start, end in _spans(wording):
        text = wording[start:end]
        protected = [
            {"text": m.group(), "start": start + m.start(), "end": start + m.end()}
            for m in PROTECTED.finditer(text)
        ]
        provenance = {
            "method": VERSION,
            "transformation": "verbatim spans only",
            "target_clarification": target,
            "original_span": [start, end],
        }
        issue = None
        verb = VERB.search(text)
        if text.rstrip().endswith("?") or re.match(
            r"\s*(who|what|why|how|does|do|can|is)\b", text, re.IGNORECASE
        ):
            issue = "Please state the organisational claim you want assessed."
        elif re.match(
            r"\s*(if|when|unless|because|although|while)\b", text, re.IGNORECASE
        ) and not re.search(r",|\bthen\b", text, re.IGNORECASE):
            issue = "Please include the main statement that applies under this condition."
        elif re.search(
            r"^\s*(this|that|these|those)\b|\b(it|they|he|she|something|someone)\b",
            text,
            re.IGNORECASE,
        ):
            issue = "What does the unclear reference refer to in your claim?"
        elif not verb or not text[: verb.start()].strip() or not text[verb.end() :].strip(" ."):
            issue = "Please state who or what does the action, and what the action applies to."
        elif (
            verb.group().casefold().split()[0] in {"must", "shall", "may", "can", "cannot"}
            and len(text[verb.end() :].strip(" .").split()) < 2
        ):
            issue = "Please include the complete action and what it applies to."
        # Keep shared conditions and coordinated actions verbatim. A classifier's
        # inability to compare them is a coverage limitation, not an intake gate.
        detected = [key for key, pattern in TARGETS.items() if pattern.search(text)]
        if verb and verb.group().casefold() in {"records", "recorded", "shows", "showed"}:
            detected = ["recorded_state"]
        elif "actual_practice" in detected:
            detected = ["actual_practice"]
        elif (
            re.search(r"\b(must|shall)\b", text, re.IGNORECASE)
            and "actual_practice" not in detected
        ):
            detected = ["prescribed_rule"]
        resolved_target = (
            (None if target == "all" else target)
            if target
            else (detected[0] if len(detected) == 1 else None)
        )
        provenance["assessment_scope"] = resolved_target or "all"
        dates = []
        try:
            dates = [date.fromisoformat(m.group()) for m in DATE.finditer(text)]
        except ValueError:
            issue = "Please provide a valid date in YYYY-MM-DD format."
        other_dates = re.search(
            r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d|"
            r"\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b|\b(today|yesterday|currently|last year)\b",
            text,
            re.IGNORECASE,
        )
        dated_text = DATE.sub("DATE", text)
        unsupported_period = re.search(
            r"\b(?:since|before|after|by|until|through)\s+DATE|\b(?:in|during|since)\s+\d{4}\b",
            dated_text,
            re.IGNORECASE,
        )
        if dates and not re.search(
            r"\b(?:on|as of)\s+DATE\b|\bfrom\s+DATE\s+to\s+DATE\b", dated_text, re.IGNORECASE
        ):
            issue = "Please clarify what the date refers to; an event date or period is distinct from a recorded date value."
        if unsupported_period:
            issue = "Please clarify whether the date is an event date, a deadline, or a period; your wording is retained."
        if other_dates or len(dates) > 2 or (len(dates) == 2 and dates[0] > dates[1]):
            issue = "Please clarify the relevant date or period using YYYY-MM-DD; your wording is retained."
        claim = None
        if issue is None:
            obj = text[verb.end() :].strip().rstrip(".")
            claim = AtomicClaim(
                claim_id="CF-" + uuid4().hex[:16],
                subject=text[: verb.start()].strip(),
                predicate=verb.group(),
                object=obj,
                scope=text.strip(),
                conditions=[
                    m.group()
                    for m in re.finditer(
                        r"\b(?:if|when|unless|except|excluding|without|for)\b.*",
                        text,
                        re.IGNORECASE,
                    )
                ],
                claim_type="employee_entered",
                evidence_target=EvidenceTarget(resolved_target) if resolved_target else None,
                claim_text=text.strip(),
                original_claim_text=wording,
                applicable_start_date=dates[0] if dates else None,
                applicable_end_date=dates[-1] if dates else None,
                proposition_polarity="negative"
                if re.search(r"\b(not|cannot)\b", verb.group(), re.IGNORECASE)
                or re.match(r"\s*No\b", text, re.IGNORECASE)
                else "positive",
                atomicity_status="bounded_intake_requires_evidence_review",
            )
        parts.append(
            IntakePart(
                text=text,
                start=start,
                end=end,
                status="awaiting_clarification" if issue else "awaiting_evidence_review",
                claim=claim,
                clarification=issue,
                protected_values=protected,
                provenance=provenance,
            )
        )
    return Intake(original_wording=wording, parts=parts)
