"""Auditable, domain-independent grammatical normalisation for query frames."""

from copy import deepcopy
from dataclasses import asdict, dataclass
import re
from typing import Any, Literal

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

_MODAL = r"can|may|must|shall|should"
_OPERATIONAL = r"normally|usually|actually|in practice|operationally"
_SYSTEM = r"database|CRM|audit (?:log|record)|system (?:field|record)|stored|contained"
_NORMATIVE = r"required|permitted|approved (?:policy|procedure)|formally documented"


@dataclass(frozen=True)
class NormalisationRecord:
    frame_index: int
    original_fields: dict[str, Any]
    normalised_fields: dict[str, Any]
    transformation_type: str
    supporting_source_spans: tuple[dict[str, Any], ...]
    protected_meaning_changed: bool = False

    def model_dump(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class InheritedField:
    target_frame: int
    field: str
    value: str
    source_fragment: int
    source_span: str
    source_start: int
    source_end: int

    def model_dump(self) -> dict[str, Any]:
        return asdict(self)


def _modal_match(question: str):
    """Find a modal auxiliary without treating the month name May as one."""
    for match in re.finditer(rf"\b({_MODAL})\b", question, re.IGNORECASE):
        if match[1].casefold() == "may":
            before, after = question[:match.start()], question[match.end():]
            day_month_year = (
                re.search(r"\b\d{1,2}\s*$", before)
                and re.match(r"\s+\d{4}\b", after)
            )
            month_day_year = re.match(r"\s+(?:\d{1,2},?\s+)?\d{4}\b", after)
            if day_month_year or month_day_year:
                continue
        return match
    return None


def query_operator(question: str) -> QueryOperator:
    lower = question.casefold().strip()
    if re.search(rf"\b(?:{_OPERATIONAL})\b", lower):
        return "practice_lookup"
    if re.search(
        rf"\bwhat\b.*\b(?:value|field|status)\b.*\b(?:recorded|{_SYSTEM})\b",
        question,
        re.IGNORECASE,
    ):
        return "recorded_state_lookup"
    if re.match(r"who\b", lower):
        return "authority_lookup"
    if re.search(r"\bwhat\b.*\b(?:percentage|threshold|amount|limit)\b", lower):
        return "threshold_lookup"
    if re.match(r"when\b", lower):
        return "timing_lookup"
    if re.search(r"\b(?:procedure|steps)\b", lower) or re.match(r"how (?:do|can|should)\b", lower):
        return "follow_procedure"
    modal = _modal_match(question)
    if modal and modal.start() == len(question) - len(question.lstrip()) \
            and modal[1].casefold() in {"can", "may"}:
        return "permission_check"
    if re.search(r"\bpolicy\b.*\bapply\b", lower):
        return "claim_verification"
    return "unknown"


def requested_field(operator: QueryOperator) -> str:
    return {
        "authority_lookup": "authorised_role",
        "threshold_lookup": "threshold",
        "timing_lookup": "timing",
        "follow_procedure": "procedure",
        "practice_lookup": "practice_description",
        "recorded_state_lookup": "recorded_value",
        "permission_check": "truth_status",
        "claim_verification": "truth_status",
        "unknown": "unknown",
    }[operator]


def answer_binding(field: str, question: str) -> str:
    if field == "threshold" and re.match(r"\s*what\b", question, re.IGNORECASE):
        return "grammatical_subject"
    return {
        "authorised_role": "known_actor",
        "threshold": "numeric_values",
        "timing": "temporal_scope",
        "procedure": "procedure_result",
        "truth_status": "truth_status",
        "practice_description": "practice_description",
        "recorded_value": "recorded_value",
        "unknown": "unknown",
    }[field]


def arbitrate_target(question: str) -> tuple[str, tuple[str, ...]]:
    """Read the complete question; conflicting explicit signal classes stay unresolved."""
    signals = []
    if re.search(rf"\b(?:{_OPERATIONAL})\b", question, re.IGNORECASE):
        signals.append("actual_practice")
    if re.search(rf"\b(?:{_SYSTEM})\b", question, re.IGNORECASE):
        signals.append("recorded_state")
    if _modal_match(question) or re.search(_NORMATIVE, question, re.IGNORECASE):
        signals.append("prescribed_rule")
    unique = tuple(dict.fromkeys(signals))
    if len(unique) == 1:
        return unique[0], unique
    if len(unique) > 1:
        return "unknown", unique
    operator = query_operator(question)
    if operator in {"authority_lookup", "threshold_lookup", "timing_lookup", "permission_check",
                    "claim_verification"}:
        return "prescribed_rule", ()
    if operator == "recorded_state_lookup":
        return "recorded_state", ()
    if operator == "practice_lookup":
        return "actual_practice", ()
    return "unknown", ()


def _lemma(word: str) -> str:
    lower = word.casefold()
    if lower.endswith("ied") and len(lower) > 4:
        return lower[:-3] + "y"
    if lower.endswith("ed") and len(lower) > 4:
        base = lower[:-2]
        if base.endswith(base[-1:] * 2):
            base = base[:-1]
        if base.endswith(("at", "iz", "iv", "ur", "or", "u")):
            base += "e"
        return base
    if lower.endswith("es") and len(lower) > 4:
        return lower[:-2] if lower[-3] in "sxz" else lower[:-1]
    if lower.endswith("s") and len(lower) > 3:
        return lower[:-1]
    return lower


def _span(question: str, text: str, field: str) -> dict[str, Any]:
    match = re.search(re.escape(text), question, re.IGNORECASE)
    if not match:
        raise ValueError(f"Cannot ground {field} in question")
    return {
        "field": field,
        "text": question[match.start():match.end()],
        "context_index": None,
    }


def grammar(question: str) -> dict[str, Any]:
    """Return only structure supported by generic English patterns."""
    operator = query_operator(question)
    modal_match = _modal_match(question)
    modality = modal_match[1].casefold() if modal_match else None
    action = obj = actor = None
    transformation = "question_operator_separation"
    spans: list[dict[str, Any]] = []

    purpose = re.search(r"\bto\s+([A-Za-z]+)\s+(.+?)[?.!]*$", question)
    passive = re.search(rf"\b(?:{_MODAL})\s+(.+?)\s+be\s+([A-Za-z]+ed)\b", question, re.IGNORECASE)
    authority = re.search(r"\bauthority\s+to\s+([A-Za-z]+)\s+(.+?)[?.!]*$", question, re.IGNORECASE)
    threshold = re.match(r"\s*what\s+(.+?)\s+([A-Za-z]+s)\s+(.+?)[?.!]*$", question, re.IGNORECASE)
    recorded = re.match(
        r"\s*what\s+(.+?)\s+(?:is|are)\s+([A-Za-z]+ed)\s+(.+?)[?.!]*$",
        question,
        re.IGNORECASE,
    )
    direct_who = re.match(r"\s*who\s+([A-Za-z]+)\s+(.+?)[?.!]*$", question, re.IGNORECASE)

    if operator == "follow_procedure" and purpose:
        action, obj = _lemma(purpose[1]), purpose[2].strip()
        transformation = "purpose_infinitive"
        spans.extend((_span(question, purpose[1], "business_action"),
                      _span(question, purpose[2].strip(), "business_object")))
    elif operator == "timing_lookup" and passive:
        obj, action = passive[1].strip(), _lemma(passive[2])
        transformation = "passive_to_active"
        spans.extend((_span(question, passive[2], "business_action"),
                      _span(question, passive[1].strip(), "business_object")))
    elif authority:
        action, obj = _lemma(authority[1]), authority[2].strip()
        transformation = "authority_infinitive"
        spans.extend((_span(question, authority[1], "business_action"),
                      _span(question, authority[2].strip(), "business_object")))
    elif operator == "recorded_state_lookup" and recorded:
        obj, action = recorded[1].strip(), _lemma(recorded[2])
        transformation = "passive_to_active"
        spans.extend((_span(question, recorded[2], "business_action"),
                      _span(question, recorded[1].strip(), "business_object")))
    elif operator == "threshold_lookup" and threshold:
        action, obj = _lemma(threshold[2]), threshold[3].strip()
        transformation = "requested_subject_separation"
        spans.extend((_span(question, threshold[2], "business_action"),
                      _span(question, threshold[3].strip(), "business_object")))
    elif direct_who:
        action, obj = _lemma(direct_who[1]), direct_who[2].strip()
        transformation = "question_operator_separation"
        spans.extend((_span(question, direct_who[1], "business_action"),
                      _span(question, direct_who[2].strip(), "business_object")))

    if operator in {"permission_check", "practice_lookup"}:
        actor_noun = r"employees?|staff|people|users?|workers?|personnel|members?|teams?"
        pattern = rf"^(?:{_MODAL}|do|does)\s+(.+?\b(?:{actor_noun}))\s+(?:(?:{_OPERATIONAL})\s+)?([A-Za-z]+)\s+(.+?)[?.!]*$"
        match = re.match(pattern, question, re.IGNORECASE)
        if match:
            actor, action, obj = match[1].strip(), _lemma(match[2]), match[3].strip()
            spans.extend((_span(question, actor, "known_actor"),
                          _span(question, match[2], "business_action"),
                          _span(question, obj, "business_object")))
    if operator == "follow_procedure":
        actor_match = re.search(rf"\b(?:{_MODAL})\s+(.+?)\s+(?:follow|use)\b", question, re.IGNORECASE)
        if actor_match:
            actor = actor_match[1].strip()
            spans.append(_span(question, actor, "known_actor"))
    if modality:
        spans.append(_span(question, modal_match[1], "modality"))
    return {
        "query_operator": operator,
        "business_action": action,
        "business_object": obj,
        "known_actor": actor,
        "modality": modality,
        "transformation_type": transformation,
        "supporting_source_spans": spans,
    }


def normalise_legacy_frame(frame: dict[str, Any], question: str, frame_index: int = 0
                           ) -> tuple[dict[str, Any], list[NormalisationRecord]]:
    """Explicit 1.2 adapter. Runtime 1.3 schema never accepts these legacy keys."""
    original = deepcopy(frame)
    structure = grammar(question)
    operator = structure["query_operator"]
    field = requested_field(operator)
    target, target_signals = arbitrate_target(question)
    action = structure["business_action"] or frame.get("predicate")
    obj = structure["business_object"] or frame.get("object")
    actor = structure["known_actor"] or frame.get("known_subject")
    missing = list(frame.get("missing_material_fields", []))
    unresolved = bool(re.search(r"\b(?:it|them|this|that)\b", question, re.IGNORECASE)) and (
        not obj or obj.casefold() in {"it", "them", "this", "that"}
    )
    requested_words = {field, answer_binding(field, question), "threshold referent"}
    if field == "threshold":
        requested_words.add("object referent")
    removed_requested = [] if unresolved else [
        item for item in missing if item.casefold() in requested_words
    ]
    missing = [item for item in missing if item not in removed_requested]
    needs_clarification = unresolved or bool(missing) or len(target_signals) > 1
    if len(target_signals) > 1:
        missing.append("assessment target")
    clarification = frame.get("clarification_question") if needs_clarification else None
    if needs_clarification and not clarification:
        clarification = "Which material input or assessment perspective did you mean?"
    conditions = [value for value in frame.get("conditions", [])
                  if value.casefold() not in {structure["modality"], "obtained"}]
    temporal = [value for value in frame.get("temporal_scope", [])
                if value.casefold() not in {_MODAL.split("|")[i] for i in range(5)}]
    canonical = {
        "original_question": question,
        "query_operator": operator,
        "business_action": action,
        "business_object": obj,
        "known_actor": actor,
        "requested_fields": [field],
        "answer_slots": [{"requested_field": field, "binds_to": answer_binding(field, question),
                          "value": None}],
        "modality": structure["modality"] or frame.get("modality"),
        "process": frame.get("process"),
        "assessment_target": target,
        "scope": frame.get("scope"),
        "conditions": conditions,
        "numeric_values": list(frame.get("numeric_values", [])),
        "temporal_scope": temporal,
        "polarity": frame.get("polarity", "positive"),
        "source_spans": structure["supporting_source_spans"],
        "needs_clarification": needs_clarification,
        "missing_material_fields": list(dict.fromkeys(missing)),
        "clarification_question": clarification,
        "inherited_fields": [],
    }
    changed = {key: value for key, value in canonical.items()
               if key not in original or original.get(key) != value}
    records = [NormalisationRecord(
        frame_index=frame_index,
        original_fields={key: original.get(key) for key in (
            "intent", "predicate", "object", "known_subject", "requested_fields", "modality",
            "process", "assessment_target", "conditions", "temporal_scope",
        )},
        normalised_fields=changed,
        transformation_type=structure["transformation_type"],
        supporting_source_spans=tuple(structure["supporting_source_spans"]),
    )]
    if removed_requested:
        records.append(NormalisationRecord(
            frame_index, {"missing_material_fields": frame.get("missing_material_fields"),
                          "clarification_question": frame.get("clarification_question")},
            {"missing_material_fields": missing, "clarification_question": None},
            "requested_answer_not_missing_input", (), False,
        ))
    if target != frame.get("assessment_target"):
        records.append(NormalisationRecord(
            frame_index, {"assessment_target": frame.get("assessment_target")},
            {"assessment_target": target}, "complete_question_target_arbitration",
            tuple(structure["supporting_source_spans"]), False,
        ))
    return canonical, records


def normalise_canonical_frame(frame: dict[str, Any], question: str, frame_index: int = 0
                              ) -> tuple[dict[str, Any], list[NormalisationRecord]]:
    """Correct grammatical structure without changing protected employee meaning."""
    original = deepcopy(frame)
    canonical = deepcopy(frame)
    structure = grammar(question)
    operator = structure["query_operator"]
    field = requested_field(operator)
    target, target_signals = arbitrate_target(question)
    changes: dict[str, Any] = {}

    for name in ("query_operator", "business_action", "business_object"):
        value = structure[name]
        if (value is not None and canonical.get(name) != value
                and not (name == "business_object" and value.casefold() in {
                    "it", "them", "this", "that",
                } and canonical.get(name))):
            canonical[name] = value
            changes[name] = value
    supplied_fields = canonical.get("requested_fields")
    fields = supplied_fields if isinstance(supplied_fields, list) and field in supplied_fields else [field]
    if canonical.get("requested_fields") != fields:
        canonical["requested_fields"] = fields
        changes["requested_fields"] = fields
    slots = [
        {"requested_field": requested, "binds_to": answer_binding(requested, question),
         "value": None}
        for requested in fields
    ]
    if canonical.get("answer_slots") != slots:
        canonical["answer_slots"] = slots
        changes["answer_slots"] = slots
    # Modality, actor, numbers, dates, polarity, conditions and named entities are
    # protected. They are validated, never rewritten here.
    if len(target_signals) == 1 and canonical.get("assessment_target") != target:
        canonical["assessment_target"] = target
        changes["assessment_target"] = target
    elif len(target_signals) > 1:
        conflict = "assessment target"
        missing = list(canonical.get("missing_material_fields", []))
        if conflict not in missing:
            missing.append(conflict)
        canonical.update(
            assessment_target="unknown",
            needs_clarification=True,
            missing_material_fields=missing,
            clarification_question=canonical.get("clarification_question")
            or "Should this be assessed as a rule, observed practice, or a system record?",
        )
        changes.update({key: canonical[key] for key in (
            "assessment_target", "needs_clarification", "missing_material_fields",
            "clarification_question",
        )})
    unresolved = bool(re.search(r"\b(?:it|them|this|that)\b", question, re.IGNORECASE)) and (
        not canonical.get("business_object")
        or str(canonical["business_object"]).casefold() in {"it", "them", "this", "that"}
    )
    requested_markers = {
        *fields,
        *(slot["binds_to"] for slot in slots),
        "object referent",
        "threshold referent",
    }
    missing = list(canonical.get("missing_material_fields", []))
    if not unresolved and missing and all(item.casefold() in requested_markers for item in missing):
        canonical.update(needs_clarification=False, missing_material_fields=[], clarification_question=None)
        changes.update(needs_clarification=False, missing_material_fields=[], clarification_question=None)
    temporal = list(canonical.get("temporal_scope", []))
    filtered_temporal = [value for value in temporal
                         if value.casefold() not in {"must", "may", "should", "can", "shall"}]
    if filtered_temporal != temporal and canonical.get("modality"):
        canonical["temporal_scope"] = filtered_temporal
        changes["temporal_scope"] = filtered_temporal
    if not changes:
        return canonical, []
    record = NormalisationRecord(
        frame_index=frame_index,
        original_fields={key: original.get(key) for key in changes},
        normalised_fields=changes,
        transformation_type=structure["transformation_type"],
        supporting_source_spans=tuple(structure["supporting_source_spans"]),
        protected_meaning_changed=False,
    )
    return canonical, [record]


def normalise_interpretation_payload(payload: dict[str, Any], question: str, *, legacy: bool = False
                                     ) -> tuple[dict[str, Any], tuple[NormalisationRecord, ...]]:
    frames, records = [], []
    normaliser = normalise_legacy_frame if legacy else normalise_canonical_frame
    for index, frame in enumerate(payload.get("frames", [])):
        canonical, changes = normaliser(frame, question, index)
        frames.append(canonical)
        records.extend(changes)
    return {"original_question": question, "frames": frames}, tuple(records)


def inherit_compound_context(frames: list[dict[str, Any]], fragments: list[dict[str, Any]]
                             ) -> tuple[list[dict[str, Any]], list[InheritedField]]:
    """Inherit one unambiguous named process/object from an earlier fragment."""
    values = []
    for index, frame in enumerate(frames):
        candidate = frame.get("business_object")
        if candidate and candidate.casefold() not in {"approval", "it", "them", "this", "that"}:
            values.append((index, candidate))
    unique = {value.casefold(): (index, value) for index, value in values}
    if len(unique) != 1:
        return frames, []
    source_index, value = next(iter(unique.values()))
    fragment = fragments[source_index]
    start = fragment["start"] + fragment["text"].casefold().find(value.casefold())
    if start < fragment["start"]:
        return frames, []
    inherited = []
    for index, frame in enumerate(frames):
        if index == source_index or frame.get("process") not in {None, "approval", "approval process"}:
            continue
        frame["process"] = value
        record = InheritedField(index, "process", value, source_index, value, start, start + len(value))
        frame.setdefault("inherited_fields", []).append({
            key: item for key, item in record.model_dump().items() if key != "target_frame"
        })
        frame.setdefault("source_spans", []).append({
            "field": "process", "text": value, "context_index": None,
        })
        inherited.append(record)
    return frames, inherited
