"""Minimal, grounded intent contract for interpretation-2.0 Stage 2A."""

from collections import Counter
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from decidr.question_retrieval import RetrievedContextPackage

SCHEMA_VERSION = "interpretation-2.0-stage-2a"

QueryOperator = Literal[
    "claim_verification",
    "permission_check",
    "authority_lookup",
    "threshold_lookup",
    "timing_lookup",
    "follow_procedure",
    "practice_lookup",
    "recorded_state_lookup",
    "unknown",
]
RequestedField = Literal[
    "authorised_role",
    "threshold",
    "timing",
    "procedure",
    "claim_assessment",
    "practice_description",
    "recorded_value",
    "unknown",
]
KnowledgeTarget = Literal[
    "prescribed_rule", "actual_practice", "recorded_state", "unspecified"
]
ProtectedValueType = Literal[
    "date", "quantity", "identifier", "modality", "negation", "exclusion", "named_entity"
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ExactQuestionSpan(StrictModel):
    text: str = Field(min_length=1)
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, ge=1)


class ProtectedValue(ExactQuestionSpan):
    value_type: ProtectedValueType


class GroundedSearchPhrase(StrictModel):
    text: str = Field(min_length=1)
    origin: Literal["question", "retrieved_context"]
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, ge=1)
    evidence_id: str | None = None
    source_id: str | None = None

    @model_validator(mode="after")
    def coherent_origin(self):
        identifiers = self.evidence_id is not None and self.source_id is not None
        if self.origin == "question" and (self.evidence_id is not None or self.source_id is not None):
            raise ValueError("Question-grounded phrases cannot cite retrieved evidence")
        if self.origin == "retrieved_context" and not identifiers:
            raise ValueError("Retrieved-context phrases require evidence and source IDs")
        return self


class RepresentationCorrection(StrictModel):
    intent_index: int | None = Field(default=None, ge=0)
    field: str = Field(min_length=1)
    correction_type: Literal["exact_offset_completion", "null_string", "deterministic_ordering"]
    before: Any
    after: Any


class QueryIntentProvenance(StrictModel):
    method: Literal["local_model", "deterministic_fallback"]
    model_name: str | None = None
    retrieval_first: Literal[True] = True
    corrections: list[RepresentationCorrection] = Field(default_factory=list)


class QueryIntent(StrictModel):
    subquestion: ExactQuestionSpan
    query_operator: QueryOperator
    requested_fields: list[RequestedField] = Field(min_length=1, max_length=8)
    knowledge_target: KnowledgeTarget = "unspecified"
    grounded_search_phrases: list[GroundedSearchPhrase] = Field(max_length=20)
    conditions: list[ExactQuestionSpan] = Field(max_length=20)
    protected_values: list[ProtectedValue] = Field(max_length=30)
    unresolved_referents: list[ExactQuestionSpan] = Field(max_length=10)
    needs_clarification: bool
    clarification_question: str | None = None

    @model_validator(mode="after")
    def coherent_intent(self):
        if len(self.requested_fields) != len(set(self.requested_fields)):
            raise ValueError("Requested fields cannot be duplicated")
        if self.needs_clarification != bool(self.clarification_question):
            raise ValueError("Clarification flag and question must agree")
        return self


class QueryIntentSet(StrictModel):
    version: Literal["interpretation-2.0-stage-2a"] = SCHEMA_VERSION
    provenance: QueryIntentProvenance
    intents: list[QueryIntent] = Field(min_length=1, max_length=12)


class IntentValidationError(ValueError):
    pass


MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|November|December"
)
DATE_PATTERN = re.compile(
    rf"\b(?:\d{{4}}-\d{{2}}-\d{{2}}|\d{{1,2}}\s+(?:{MONTHS})\s+\d{{4}}|"
    rf"(?:{MONTHS})\s+(?:\d{{1,2}},?\s+)?\d{{4}})\b",
    re.IGNORECASE,
)
IDENTIFIER_PATTERN = re.compile(r"\b[A-Z][A-Z0-9]*-[0-9][A-Z0-9-]*\b")
QUANTITY_PATTERN = re.compile(
    r"(?<![\w-])(?:[$£€]\s*)?\d+(?:,\d{3})*(?:\.\d+)?\s*"
    r"(?:%|percent|days?|weeks?|months?|years?|hours?|minutes?)?(?![\w-])",
    re.IGNORECASE,
)
EXCLUSION_PATTERN = re.compile(
    r"\b(?:without|unless|except(?:\s+for)?)\s+[^?;,.]+", re.IGNORECASE
)
NEGATION_PATTERN = re.compile(r"\b(?:not|never|no|cannot)\b|\b(?:can't|won't|don't|doesn't)\b", re.IGNORECASE)
MODAL_PATTERN = re.compile(r"\b(?:can|may|must|shall|should)\b", re.IGNORECASE)
NAMED_ENTITY_PATTERN = re.compile(r"\b[A-Z][A-Za-z0-9]*(?:\s+[A-Z][A-Za-z0-9]*)*\b")
PRONOUN_PATTERN = re.compile(r"\b(?:it|them|they)\b|\b(?:this|that|these|those)\b(?!\s+[A-Za-z])", re.IGNORECASE)


def _overlaps(start: int, end: int, occupied: list[tuple[int, int]]) -> bool:
    return any(start < right and end > left for left, right in occupied)


def _calendar_may(question: str, match: re.Match[str]) -> bool:
    before, after = question[: match.start()], question[match.end() :]
    return bool(
        (re.search(r"\b\d{1,2}\s*$", before) and re.match(r"\s+\d{4}\b", after))
        or re.match(r"\s+(?:\d{1,2},?\s+)?\d{4}\b", after)
    )


def _modal_match(question: str) -> re.Match[str] | None:
    for match in MODAL_PATTERN.finditer(question):
        if match[0].casefold() != "may" or not _calendar_may(question, match):
            return match
    return None


def _clauses(question: str) -> list[str]:
    return [
        part.strip(" ,")
        for part in re.split(
            r"[,;]?\s+and\s+(?=(?:who|when|what|how|can|may|does|do)\b)|(?<=[?;])\s+",
            question,
            flags=re.IGNORECASE,
        )
        if part.strip()
    ]


def extract_protected_values(question: str) -> tuple[ProtectedValue, ...]:
    """Extract high-risk literals before interpretation, with exact question offsets."""
    found: list[ProtectedValue] = []
    occupied: list[tuple[int, int]] = []

    def add(match: re.Match[str], value_type: ProtectedValueType, *, allow_overlap: bool = False):
        if not allow_overlap and _overlaps(match.start(), match.end(), occupied):
            return
        found.append(
            ProtectedValue(
                text=question[match.start() : match.end()],
                start=match.start(),
                end=match.end(),
                value_type=value_type,
            )
        )
        if value_type in {"date", "identifier"}:
            occupied.append((match.start(), match.end()))

    for pattern, value_type in ((DATE_PATTERN, "date"), (IDENTIFIER_PATTERN, "identifier")):
        for match in pattern.finditer(question):
            add(match, value_type)
    for pattern, value_type in (
        (EXCLUSION_PATTERN, "exclusion"),
        (NEGATION_PATTERN, "negation"),
    ):
        for match in pattern.finditer(question):
            add(match, value_type, allow_overlap=True)
    for match in MODAL_PATTERN.finditer(question):
        if match[0].casefold() == "may" and _calendar_may(question, match):
            continue
        add(match, "modality")
    for match in QUANTITY_PATTERN.finditer(question):
        add(match, "quantity")
    ignored_names = {
        "as",
        "can",
        "does",
        "do",
        "how",
        "is",
        "may",
        "must",
        "shall",
        "should",
        "what",
        "when",
        "who",
        *{month.casefold() for month in MONTHS.split("|")},
    }
    for match in NAMED_ENTITY_PATTERN.finditer(question):
        entity = match[0]
        start = match.start()
        words = entity.split()
        while words and words[0].casefold() in ignored_names:
            removed = words.pop(0)
            start += len(removed)
            while start < match.end() and question[start].isspace():
                start += 1
        if not words:
            continue
        entity = question[start : match.end()]
        if _overlaps(start, match.end(), occupied):
            continue
        found.append(
            ProtectedValue(
                text=entity,
                start=start,
                end=match.end(),
                value_type="named_entity",
            )
        )
    return tuple(sorted(found, key=lambda item: (item.start or 0, item.end or 0, item.value_type)))


def subquestion_spans(question: str) -> tuple[ExactQuestionSpan, ...]:
    cursor = 0
    spans = []
    for part in _clauses(question):
        start = question.find(part, cursor)
        if start < 0:
            raise IntentValidationError("Subquestion is not a verbatim question span")
        spans.append(ExactQuestionSpan(text=part, start=start, end=start + len(part)))
        cursor = start + len(part)
    return tuple(spans)


def unresolved_referents(question: str) -> tuple[ExactQuestionSpan, ...]:
    return tuple(
        ExactQuestionSpan(text=match[0], start=match.start(), end=match.end())
        for match in PRONOUN_PATTERN.finditer(question)
    )


def generic_query_operator(question: str) -> QueryOperator:
    lower = question.casefold().strip()
    if re.search(r"\b(?:normally|usually|actually|in practice|operationally)\b", lower):
        return "practice_lookup"
    if re.search(r"\b(?:database|crm|audit log|system record|recorded|stored)\b", lower):
        return "recorded_state_lookup"
    if re.match(r"who\b", lower):
        return "authority_lookup"
    if re.search(r"\b(?:percentage|threshold|amount|limit)\b", lower):
        return "threshold_lookup"
    if re.match(r"when\b", lower):
        return "timing_lookup"
    if re.search(r"\b(?:procedure|steps)\b", lower) or re.match(r"how\b", lower):
        return "follow_procedure"
    modal = _modal_match(question)
    if modal and modal.start() == len(question) - len(question.lstrip()) and modal[0].casefold() in {
        "can",
        "may",
    }:
        return "permission_check"
    if re.match(r"(?:does?|is|are|was|were|has|have|will)\b", lower) or "policy" in lower:
        return "claim_verification"
    return "unknown"


def requested_field_for_operator(operator: QueryOperator) -> RequestedField:
    return {
        "authority_lookup": "authorised_role",
        "threshold_lookup": "threshold",
        "timing_lookup": "timing",
        "follow_procedure": "procedure",
        "practice_lookup": "practice_description",
        "recorded_state_lookup": "recorded_value",
        "permission_check": "claim_assessment",
        "claim_verification": "claim_assessment",
        "unknown": "unknown",
    }[operator]


def _target_signals(text: str) -> set[str]:
    signals = set()
    if re.search(
        r"\b(?:policy|rule|procedure|required|must|formally|prescribed)\b",
        text,
        re.IGNORECASE,
    ):
        signals.add("prescribed_rule")
    if re.search(
        r"\b(?:normally|usually|actually|in practice|operationally)\b",
        text,
        re.IGNORECASE,
    ):
        signals.add("actual_practice")
    if re.search(
        r"\b(?:database|crm|audit log|system (?:field|record)|recorded|stored)\b",
        text,
        re.IGNORECASE,
    ):
        signals.add("recorded_state")
    return signals


def _source_for_phrase(
    phrase: GroundedSearchPhrase,
    question: str,
    context: RetrievedContextPackage,
) -> str:
    if phrase.origin == "question":
        return question
    passage = next(
        (
            item
            for item in context.passages
            if item.evidence_id == phrase.evidence_id and item.source_id == phrase.source_id
        ),
        None,
    )
    if passage is None:
        raise IntentValidationError("Search phrase cites unavailable retrieved context")
    return passage.text


def _check_span(span: ExactQuestionSpan, source: str, label: str) -> None:
    if span.start is None or span.end is None or source[span.start : span.end] != span.text:
        raise IntentValidationError(f"{label} does not have exact source offsets")


def _protected_key(item: ProtectedValue) -> tuple[str, int | None, int | None, str]:
    return item.text, item.start, item.end, item.value_type


def validate_query_intents(
    value: QueryIntentSet,
    question: str,
    context: RetrievedContextPackage,
    *,
    expected_model: str | None = None,
) -> QueryIntentSet:
    """Validate grounding, protected meaning, target signals and compound integrity."""
    if value.provenance.method == "local_model" and expected_model != value.provenance.model_name:
        raise IntentValidationError("Intent provenance does not identify the configured model")
    expected_spans = subquestion_spans(question)
    actual_spans = [intent.subquestion for intent in value.intents]
    if len(actual_spans) != len(expected_spans) or any(
        actual.model_dump() != expected.model_dump()
        for actual, expected in zip(actual_spans, expected_spans, strict=False)
    ):
        raise IntentValidationError(
            "Compound intents must preserve every ordered subquestion without merging or duplication"
        )
    for index, intent in enumerate(value.intents):
        _check_span(intent.subquestion, question, "Subquestion")
        expected_field = requested_field_for_operator(intent.query_operator)
        if expected_field not in intent.requested_fields:
            raise IntentValidationError("Requested fields do not match the generic query operator")
        signals = _target_signals(intent.subquestion.text)
        if intent.knowledge_target != "unspecified" and intent.knowledge_target not in signals:
            raise IntentValidationError("Knowledge target is not grounded in explicit question wording")
        if len(signals) > 1 and (
            intent.knowledge_target != "unspecified" or not intent.needs_clarification
        ):
            raise IntentValidationError("Conflicting knowledge targets require clarification")
        for condition in intent.conditions:
            _check_span(condition, question, "Condition")
        for referent in intent.unresolved_referents:
            _check_span(referent, question, "Unresolved referent")
        expected_referents = [
            item
            for item in unresolved_referents(question)
            if intent.subquestion.start <= item.start and item.end <= intent.subquestion.end
        ]
        if [item.model_dump() for item in intent.unresolved_referents] != [
            item.model_dump() for item in expected_referents
        ]:
            raise IntentValidationError("Unresolved referents cannot be omitted or invented")
        if expected_referents and not intent.needs_clarification:
            raise IntentValidationError("An unresolved standalone pronoun requires clarification")
        for phrase in intent.grounded_search_phrases:
            source = _source_for_phrase(phrase, question, context)
            if phrase.start is None or phrase.end is None or source[phrase.start : phrase.end] != phrase.text:
                raise IntentValidationError("Search phrase does not have exact origin offsets")
        if index and intent.subquestion.start <= value.intents[index - 1].subquestion.start:
            raise IntentValidationError("Compound intent order is not stable")
    expected_protected = Counter(_protected_key(item) for item in extract_protected_values(question))
    actual_protected = Counter(
        _protected_key(item) for intent in value.intents for item in intent.protected_values
    )
    if actual_protected != expected_protected:
        raise IntentValidationError("Protected values were lost, altered, retyped, duplicated or invented")
    return value


def _unique_offsets(text: str, source: str) -> tuple[int, int] | None:
    matches = list(re.finditer(re.escape(text), source))
    if len(matches) != 1:
        return None
    return matches[0].start(), matches[0].end()


def normalise_query_intent_payload(
    payload: dict[str, Any], question: str, context: RetrievedContextPackage
) -> tuple[dict[str, Any], tuple[RepresentationCorrection, ...]]:
    """Apply representation-only recovery; never repair semantic content."""
    if not isinstance(payload, dict) or not isinstance(payload.get("intents"), list):
        raise IntentValidationError("Invalid QueryIntentSet structure")
    provenance = payload.get("provenance")
    if not isinstance(provenance, dict) or provenance.get("corrections") not in (None, []):
        raise IntentValidationError("Only trusted local code may record corrections")
    corrections: list[RepresentationCorrection] = []
    for index, intent in enumerate(payload["intents"]):
        if not isinstance(intent, dict):
            raise IntentValidationError("Each intent must be an object")
        for field in ("knowledge_target", "clarification_question"):
            value = intent.get(field)
            if isinstance(value, str) and value.strip().casefold() in {"null", "none", "n/a"}:
                replacement = "unspecified" if field == "knowledge_target" else None
                intent[field] = replacement
                corrections.append(
                    RepresentationCorrection(
                        intent_index=index,
                        field=field,
                        correction_type="null_string",
                        before=value,
                        after=replacement,
                    )
                )
        question_spans = [intent.get("subquestion")]
        question_spans.extend(intent.get("conditions", []))
        question_spans.extend(intent.get("protected_values", []))
        question_spans.extend(intent.get("unresolved_referents", []))
        for span in question_spans:
            if not isinstance(span, dict) or not isinstance(span.get("text"), str):
                continue
            if span.get("start") is None or span.get("end") is None:
                offsets = _unique_offsets(span["text"], question)
                if offsets is not None:
                    before = {"start": span.get("start"), "end": span.get("end")}
                    span["start"], span["end"] = offsets
                    corrections.append(
                        RepresentationCorrection(
                            intent_index=index,
                            field="span_offsets",
                            correction_type="exact_offset_completion",
                            before=before,
                            after={"start": offsets[0], "end": offsets[1]},
                        )
                    )
        for phrase in intent.get("grounded_search_phrases", []):
            if not isinstance(phrase, dict) or not isinstance(phrase.get("text"), str):
                continue
            if phrase.get("start") is not None and phrase.get("end") is not None:
                continue
            if phrase.get("origin") == "question":
                source = question
            else:
                source = next(
                    (
                        item.text
                        for item in context.passages
                        if item.evidence_id == phrase.get("evidence_id")
                        and item.source_id == phrase.get("source_id")
                    ),
                    "",
                )
            offsets = _unique_offsets(phrase["text"], source)
            if offsets is not None:
                before = {"start": phrase.get("start"), "end": phrase.get("end")}
                phrase["start"], phrase["end"] = offsets
                corrections.append(
                    RepresentationCorrection(
                        intent_index=index,
                        field="grounded_search_phrases",
                        correction_type="exact_offset_completion",
                        before=before,
                        after={"start": offsets[0], "end": offsets[1]},
                    )
                )
    starts = [item.get("subquestion", {}).get("start") for item in payload["intents"]]
    if starts and all(isinstance(item, int) for item in starts):
        ordered = sorted(payload["intents"], key=lambda item: item["subquestion"]["start"])
        if ordered != payload["intents"]:
            payload["intents"] = ordered
            corrections.append(
                RepresentationCorrection(
                    field="intents",
                    correction_type="deterministic_ordering",
                    before=starts,
                    after=sorted(starts),
                )
            )
    payload["provenance"]["corrections"] = [item.model_dump() for item in corrections]
    return payload, tuple(corrections)


def parse_query_intents(
    raw: str,
    question: str,
    context: RetrievedContextPackage,
    *,
    expected_model: str,
) -> QueryIntentSet:
    payload = json.loads(raw)
    normalised, _ = normalise_query_intent_payload(payload, question, context)
    try:
        value = QueryIntentSet.model_validate(normalised)
    except ValueError as error:
        raise IntentValidationError(str(error)) from error
    return validate_query_intents(value, question, context, expected_model=expected_model)


def deterministic_fallback_intents(question: str) -> QueryIntentSet:
    """Create an editable search intent without any factual or assessment output."""
    protected = extract_protected_values(question)
    referents = unresolved_referents(question)
    intents = []
    for span in subquestion_spans(question):
        operator = generic_query_operator(span.text)
        local_protected = [
            item
            for item in protected
            if span.start <= item.start and item.end <= span.end
        ]
        local_referents = [
            item for item in referents if span.start <= item.start and item.end <= span.end
        ]
        needs_clarification = operator == "unknown" or bool(local_referents)
        conditions = [
            ExactQuestionSpan(text=item.text, start=item.start, end=item.end)
            for item in local_protected
            if item.value_type in {"date", "quantity", "negation", "exclusion"}
        ]
        intents.append(
            QueryIntent(
                subquestion=span,
                query_operator=operator,
                requested_fields=[requested_field_for_operator(operator)],
                knowledge_target="unspecified",
                grounded_search_phrases=[
                    GroundedSearchPhrase(
                        text=span.text,
                        origin="question",
                        start=span.start,
                        end=span.end,
                    )
                ],
                conditions=conditions,
                protected_values=local_protected,
                unresolved_referents=local_referents,
                needs_clarification=needs_clarification,
                clarification_question=(
                    "Please clarify the unresolved reference or intended question."
                    if needs_clarification
                    else None
                ),
            )
        )
    return QueryIntentSet(
        provenance=QueryIntentProvenance(
            method="deterministic_fallback", model_name=None, corrections=[]
        ),
        intents=intents,
    )


__all__ = [
    "ExactQuestionSpan",
    "GroundedSearchPhrase",
    "IntentValidationError",
    "KnowledgeTarget",
    "ProtectedValue",
    "QueryIntent",
    "QueryIntentProvenance",
    "QueryIntentSet",
    "QueryOperator",
    "RepresentationCorrection",
    "RequestedField",
    "deterministic_fallback_intents",
    "extract_protected_values",
    "generic_query_operator",
    "normalise_query_intent_payload",
    "parse_query_intents",
    "requested_field_for_operator",
    "subquestion_spans",
    "unresolved_referents",
    "validate_query_intents",
]
