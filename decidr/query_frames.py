"""Interpretation-1.3 query semantics, independent from factual AtomicClaim objects."""

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from decidr.span_alignment import align_payload, root, token_score
from decidr.structural_normalization import (
    NormalisationRecord,
    QueryOperator,
    answer_binding,
    arbitrate_target,
    grammar,
    inherit_compound_context,
    normalise_legacy_frame,
    query_operator,
    requested_field,
)

Target = Literal["prescribed_rule", "actual_practice", "recorded_state", "unknown"]
RequestedField = Literal[
    "authorised_role", "threshold", "timing", "procedure", "truth_status",
    "practice_description", "recorded_value", "unknown",
]
AnswerBinding = Literal[
    "known_actor", "grammatical_subject", "numeric_values", "temporal_scope",
    "procedure_result", "truth_status", "practice_description", "recorded_value", "unknown",
]
TARGET_DESCRIPTION = (
    "prescribed_rule: what an approved policy, procedure or decision-rights document requires "
    "or permits; actual_practice: what people operationally do; recorded_state: what a "
    "database, CRM, audit log or system record contains; unknown: unresolved or conflicting meaning."
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    @model_validator(mode="after")
    def no_placeholder_strings(self):
        if any(value.strip().casefold() in {"none", "null", "n/a"}
               for value in strings(self.model_dump())):
            raise ValueError("Use JSON null for absent values, not placeholder strings")
        return self


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from strings(child)


class SourceSpan(StrictModel):
    field: Literal[
        "process", "known_actor", "business_action", "business_object", "scope", "conditions",
        "numeric_values", "temporal_scope", "modality", "polarity", "assessment_target",
    ]
    text: str = Field(min_length=1)
    normalised_value: str | None = None
    source_span: str | None = None
    source_start: int | None = Field(default=None, ge=0)
    source_end: int | None = Field(default=None, ge=0)
    alignment_method: str | None = None
    alignment_score: float | None = Field(default=None, ge=0, le=1)
    context_index: int | None = Field(default=None, ge=0, le=3)


class AnswerSlot(StrictModel):
    requested_field: RequestedField
    binds_to: AnswerBinding
    value: str | None = Field(default=None, description="Null before retrieval")


class InheritedBinding(StrictModel):
    field: Literal["process", "business_object", "known_actor"]
    value: str = Field(min_length=1)
    source_fragment: int = Field(ge=0, le=11)
    source_span: str = Field(min_length=1)
    source_start: int = Field(ge=0)
    source_end: int = Field(ge=1)


class QueryFrame(StrictModel):
    original_question: str = Field(min_length=1)
    query_operator: QueryOperator
    business_action: str | None
    business_object: str | None
    known_actor: str | None
    requested_fields: list[RequestedField] = Field(min_length=1, max_length=7)
    answer_slots: list[AnswerSlot] = Field(min_length=1, max_length=7)
    modality: str | None
    process: str | None
    assessment_target: Target = Field(description=TARGET_DESCRIPTION)
    scope: str | None
    conditions: list[str]
    numeric_values: list[str]
    temporal_scope: list[str]
    polarity: Literal["positive", "negative", "unknown"]
    source_spans: list[SourceSpan] = Field(max_length=30)
    needs_clarification: bool
    missing_material_fields: list[str]
    clarification_question: str | None
    inherited_fields: list[InheritedBinding] = Field(default_factory=list)

    @model_validator(mode="after")
    def coherent_query(self):
        if len(set(self.requested_fields)) != len(self.requested_fields):
            raise ValueError("Do not repeat requested fields")
        if [slot.requested_field for slot in self.answer_slots] != self.requested_fields:
            raise ValueError("answer_slots must correspond one-for-one with requested_fields")
        if any(slot.value is not None for slot in self.answer_slots):
            raise ValueError("Requested answer slots must remain null before retrieval")
        expected = [answer_binding(field, self.original_question) for field in self.requested_fields]
        if [slot.binds_to for slot in self.answer_slots] != expected:
            raise ValueError("Each answer slot must identify its generic grammatical binding")
        if self.needs_clarification != bool(self.missing_material_fields):
            raise ValueError("Clarification flag and missing material inputs must agree")
        if self.needs_clarification != bool(self.clarification_question):
            raise ValueError("clarification_question must be null unless clarification is needed")
        requested_markers = set(self.requested_fields) | {slot.binds_to for slot in self.answer_slots}
        if any(item.casefold().replace(" ", "_") in requested_markers
               or re.search(r"\b(?:requested|answer)\b", item, re.IGNORECASE)
               for item in self.missing_material_fields):
            raise ValueError("Requested answers are not missing interpretation inputs")
        if self.business_action and words(self.business_action) & {
            "lookup", "know", "must", "may", "should", "can",
        }:
            raise ValueError("business_action cannot be a question operator, modal or meta-action")
        if not self.needs_clarification and (not self.business_action or not self.business_object):
            raise ValueError("A resolved query needs its underlying business action and object")
        if self.assessment_target == "unknown" and not self.needs_clarification:
            raise ValueError("Conflicting or unresolved assessment meaning requires confirmation")
        return self


class Interpretation(StrictModel):
    original_question: str = Field(min_length=1)
    frames: list[QueryFrame] = Field(min_length=1, max_length=12)

    def atomic_frames(self) -> tuple[QueryFrame, ...]:
        items = []
        for frame in self.frames:
            for index, field in enumerate(frame.requested_fields):
                payload = frame.model_dump()
                payload["requested_fields"] = [field]
                payload["answer_slots"] = [frame.answer_slots[index].model_dump()]
                items.append(QueryFrame.model_validate(payload))
        return tuple(items)


class AtomicClaim(StrictModel):
    subject: str = Field(min_length=1)
    predicate: str = Field(min_length=1)
    object: str = Field(min_length=1)
    process: str | None
    scope: str | None
    conditions: list[str]
    temporal_scope: list[str]
    modality: str | None
    polarity: Literal["positive", "negative", "unknown"]
    assessment_target: Target


class FieldIssue(StrictModel):
    frame_index: int = Field(ge=0)
    fields: list[str] = Field(min_length=1)
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)


class InterpretationValidationError(ValueError):
    def __init__(self, issues: list[FieldIssue]):
        self.issues = tuple(issues)
        super().__init__("; ".join(issue.message for issue in issues))


def words(text: str) -> set[str]:
    return set(re.findall(r"[\w%]+", text.casefold()))


def stems(text: str) -> set[str]:
    return {root(word) for word in words(text) if word not in {"a", "an", "the"}}


def bounded_context(context: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(text[:2000] for text in context[-4:])


def clauses(question: str) -> list[str]:
    return [part.strip(" ,") for part in re.split(
        r"[,;]?\s+and\s+(?=(?:who|when|what|how|can|may|does|do)\b)|(?<=[?;])\s+",
        question, flags=re.IGNORECASE,
    ) if part.strip()]


def _raise(frame_index: int, fields: list[str], code: str, message: str):
    raise InterpretationValidationError([FieldIssue(
        frame_index=frame_index, fields=fields, code=code, message=message,
    )])


def _semantic_checks(result: Interpretation, question: str, context: tuple[str, ...]) -> None:
    pieces = clauses(question)
    expected_fields = [requested_field(query_operator(piece)) for piece in pieces]
    actual_fields = [field for frame in result.frames for field in frame.requested_fields]
    if len(pieces) > 1:
        if (len(result.frames) != len(pieces)
                or any(len(frame.requested_fields) != 1 for frame in result.frames)
                or actual_fields != expected_fields):
            _raise(0, ["frames", "query_operator", "requested_fields", "answer_slots"],
                   "omitted_question",
                   "Compound questions require exactly one ordered frame per fragment")
    elif any(expected not in actual_fields for expected in expected_fields):
        _raise(0, ["requested_fields", "answer_slots"], "omitted_question",
               f"Missing requested answer field: {expected_fields[0]}")
    for index, frame in enumerate(result.frames):
        fragment = pieces[index] if len(result.frames) == len(pieces) else question
        operator = query_operator(fragment)
        if frame.query_operator != operator:
            _raise(index, ["query_operator"], "wrong_query_operator",
                   f"Complete question requires query_operator={operator}")
        expected_target, signals = arbitrate_target(fragment)
        if len(signals) > 1:
            if not frame.needs_clarification or frame.assessment_target != "unknown":
                _raise(index, ["assessment_target", "needs_clarification", "missing_material_fields",
                               "clarification_question"], "conflicting_target_signals",
                       "Conflicting target signals require employee confirmation")
        elif (expected_target != "unknown" and frame.assessment_target != expected_target
              and not (frame.needs_clarification and frame.assessment_target == "unknown")):
            _raise(index, ["assessment_target"], "wrong_target",
                   f"Complete question requires assessment_target={expected_target}")
        structure = grammar(fragment)
        for field in ("business_action", "business_object"):
            expected = structure[field]
            actual = getattr(frame, field)
            if (expected and stems(expected) != stems(actual or "")
                    and not (field == "business_object" and expected.casefold() in {
                        "it", "them", "this", "that",
                    } and actual and any(stems(actual) <= stems(item) for item in context))):
                _raise(index, [field], "changed_business_structure",
                       f"{field} must preserve the underlying organisational action structure")
        if structure["known_actor"] and stems(structure["known_actor"]) != stems(frame.known_actor or ""):
            _raise(index, ["known_actor"], "changed_actor", "Preserve the explicitly named actor")
        if structure["modality"] != (frame.modality.casefold() if frame.modality else None):
            _raise(index, ["modality"], "changed_modality", "Preserve explicit modality exactly")
        main_clause = re.split(
            r"\b(?:if|when|unless|without|provided)\b", fragment, maxsplit=1,
            flags=re.IGNORECASE,
        )[0]
        direct_negative = bool(re.search(r"\b(?:not|never|cannot)\b", main_clause, re.IGNORECASE))
        if direct_negative != (frame.polarity == "negative"):
            _raise(index, ["polarity"], "changed_negation",
                   "Preserve main-clause polarity without reversal")
        if any(value.casefold() in {"when", "what time", "how long", "must", "may", "should"}
               for value in frame.temporal_scope):
            _raise(index, ["temporal_scope"], "invalid_temporal_value",
                   "Question operators and modal auxiliaries are not temporal values")
        unresolved = bool(re.search(r"\b(?:it|them|this|that)\b", fragment, re.IGNORECASE)) and (
            not frame.business_object or frame.business_object.casefold() in {"it", "them", "this", "that"}
        )
        if unresolved and not frame.needs_clarification:
            _raise(index, ["needs_clarification", "missing_material_fields", "clarification_question"],
                   "unresolved_ambiguity", "Unresolved referent requires clarification")
        if frame.needs_clarification and not unresolved and not signals:
            _raise(index, ["needs_clarification", "missing_material_fields", "clarification_question"],
                   "unnecessary_clarification", "Requested answer slots are not missing inputs")
        numeric_text = " ".join(frame.numeric_values).casefold()
        for percentage in re.findall(r"\d+(?:\.\d+)?\s*%", fragment):
            if percentage.casefold() not in numeric_text:
                _raise(index, ["numeric_values"], "changed_protected_value",
                       f"Preserve explicit percentage in numeric_values: {percentage}")
        temporal_text = " ".join(frame.temporal_scope).casefold()
        date_pattern = (
            r"(?:as of |before |after |on |since |until |from )?"
            r"(?:\d{4}-\d{2}-\d{2}|(?:\d{1,2}\s+)?"
            r"(?:January|February|March|April|May|June|July|August|September|October|"
            r"November|December)\s+\d{1,4}(?:,?\s+\d{4})?)"
        )
        for date in re.findall(date_pattern, fragment, re.IGNORECASE):
            if date.casefold() not in temporal_text:
                _raise(index, ["temporal_scope"], "changed_protected_value",
                       f"Preserve exact date in temporal_scope: {date}")
        condition_text = " ".join(frame.conditions).casefold()
        for exclusion in re.findall(r"\bwithout\s+[^?;,]+", fragment, re.IGNORECASE):
            if exclusion.casefold() not in condition_text:
                _raise(index, ["conditions"], "changed_negation",
                       f"Preserve explicit exclusion in conditions: {exclusion}")
        if any(re.search(r"\b[A-Z]+-\d+\b", value, re.IGNORECASE)
               for value in frame.numeric_values):
            _raise(index, ["numeric_values"], "changed_protected_value",
                   "Recorded identifiers must remain distinct from numeric thresholds")

    extracted = " ".join(strings(result.model_dump(exclude={
        "original_question", "source_spans", "clarification_question", "missing_material_fields",
    })))
    for pattern, label in (
        (r"\d+(?:\.\d+)?\s*%", "percentage"),
        (r"\b[A-Z]+-\d+\b", "identifier"),
        (r"(?:as of |before |after |on |since |until |from )?(?:\d{4}-\d{2}-\d{2}|\d{1,2} [A-Za-z]+ \d{4})", "date"),
    ):
        for match in re.finditer(pattern, question, re.IGNORECASE):
            if match[0].casefold() not in extracted.casefold():
                _raise(0, ["numeric_values", "temporal_scope", "conditions", "business_object", "scope"],
                       "changed_protected_value", f"Preserve explicit {label}: {match[0]}")
    for phrase in re.findall(r"\b(?:without\s+[^?;,]+|not|never)\b", question, re.IGNORECASE):
        if phrase.casefold() not in extracted.casefold():
            _raise(0, ["conditions", "polarity"], "changed_negation",
                   "Preserve explicit negation or exclusion")


def validate_interpretation(raw: str, question: str, context: tuple[str, ...] = (), *,
                            alignment_threshold: float = .85,
                            corrections: list[dict[str, Any]] | None = None) -> Interpretation:
    context = bounded_context(context)
    payload = json.loads(raw)
    if not isinstance(payload, dict) or not isinstance(payload.get("frames"), list):
        _raise(0, ["frames"], "invalid_structure", "Invalid query-frame structure")
    try:
        aligned = align_payload(payload, question, context, alignment_threshold, corrections)
    finally:
        root.cache_clear()
        token_score.cache_clear()
    try:
        result = Interpretation.model_validate(aligned)
    except ValueError as error:
        fields = [str(part) for item in error.errors() for part in item.get("loc", ()) if isinstance(part, str)]
        raise InterpretationValidationError([FieldIssue(
            frame_index=0, fields=list(dict.fromkeys(fields)) or ["frames"],
            code="schema_semantics", message=str(error).split("\n", 1)[0],
        )]) from error
    if result.original_question != question or any(frame.original_question != question for frame in result.frames):
        _raise(0, ["original_question"], "changed_question", "Keep original_question unchanged")
    _semantic_checks(result, question, context)
    return result


def normalise_legacy_interpretation(raw: str, question: str, context: tuple[str, ...] = (), *,
                                    alignment_threshold: float = .85
                                    ) -> tuple[Interpretation, tuple[NormalisationRecord, ...]]:
    """Explicit adapter used for saved 1.2 responses and migration diagnostics."""
    payload = json.loads(raw)
    frames, records = [], []
    for index, frame in enumerate(payload["frames"]):
        canonical, changes = normalise_legacy_frame(frame, question, index)
        frames.append(canonical)
        records.extend(changes)
    fragments = [{"text": part, "start": question.find(part), "end": question.find(part) + len(part)}
                 for part in clauses(question)]
    frames, inherited = inherit_compound_context(frames, fragments)
    records.extend(NormalisationRecord(
        item.target_frame, {}, {item.field: item.value}, "unambiguous_compound_context_inheritance",
        ({"field": item.field, "text": item.source_span, "source_start": item.source_start,
          "source_end": item.source_end},), False,
    ) for item in inherited)
    interpretation = validate_interpretation(json.dumps({
        "original_question": question, "frames": frames,
    }), question, context, alignment_threshold=alignment_threshold)
    return interpretation, tuple(records)


def normalise_legacy_compound(responses: list[tuple[str, str]], question: str, *,
                              alignment_threshold: float = .85
                              ) -> tuple[Interpretation, tuple[NormalisationRecord, ...]]:
    """Assemble explicitly supplied saved 1.2 fragment responses for offline migration."""
    fragments = []
    frames: list[dict[str, Any]] = []
    records: list[NormalisationRecord] = []
    cursor = 0
    for index, (fragment, raw) in enumerate(responses):
        start = question.find(fragment, cursor)
        if start < 0:
            _raise(index, ["original_question"], "ungrounded_fragment",
                   "Saved decomposition fragment is not verbatim in the complete question")
        fragments.append({"text": fragment, "start": start, "end": start + len(fragment)})
        payload = json.loads(raw)
        canonical, changes = normalise_legacy_frame(payload["frames"][0], fragment, index)
        canonical["original_question"] = question
        frames.append(canonical)
        records.extend(changes)
        cursor = start + len(fragment)
    frames, inherited = inherit_compound_context(frames, fragments)
    records.extend(NormalisationRecord(
        item.target_frame, {}, {item.field: item.value}, "unambiguous_compound_context_inheritance",
        ({"field": item.field, "text": item.source_span, "source_start": item.source_start,
          "source_end": item.source_end},), False,
    ) for item in inherited)
    result = validate_interpretation(json.dumps({
        "original_question": question, "frames": frames,
    }), question, alignment_threshold=alignment_threshold)
    return result, tuple(records)


def query_frame_to_atomic_claim(frame: QueryFrame, *, subject: str,
                                object_override: str | None = None) -> AtomicClaim:
    """Explicit post-retrieval conversion; no legacy-field reinterpretation occurs."""
    if frame.needs_clarification or not frame.business_action or not frame.business_object:
        raise ValueError("Resolve and confirm the query frame before AtomicClaim conversion")
    return AtomicClaim(
        subject=subject, predicate=frame.business_action,
        object=object_override or frame.business_object, process=frame.process, scope=frame.scope,
        conditions=[*frame.conditions, *frame.numeric_values], temporal_scope=frame.temporal_scope,
        modality=frame.modality, polarity=frame.polarity,
        assessment_target=frame.assessment_target,
    )


__all__ = [
    "TARGET_DESCRIPTION",
    "AnswerSlot",
    "AtomicClaim",
    "FieldIssue",
    "InheritedBinding",
    "Interpretation",
    "InterpretationValidationError",
    "QueryFrame",
    "RequestedField",
    "SourceSpan",
    "StrictModel",
    "bounded_context",
    "clauses",
    "normalise_legacy_compound",
    "normalise_legacy_interpretation",
    "query_frame_to_atomic_claim",
    "stems",
    "validate_interpretation",
]
