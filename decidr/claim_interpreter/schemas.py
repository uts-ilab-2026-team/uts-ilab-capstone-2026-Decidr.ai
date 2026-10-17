"""Pydantic schemas and dynamic model builders for claim interpretation."""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, create_model

from decidr.claim_interpreter.text_numeric import _normative_threshold_claim


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Quantity(_Strict):
    value: str = Field(
        min_length=1,
        pattern=r"^-?\d+(?:\.\d+)?$",
        description="The actual numeric value from the claim, digits only; never empty or a placeholder. Convert number words, omit units and grouping commas.",
    )
    unit: str
    comparator: Literal["eq", "gt", "gte", "lt", "lte", "approx", "range"]


class Component(_Strict):
    id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    claim_quote: str = Field(min_length=1)
    entities: list[str]
    predicate: str = Field(min_length=1)
    polarity: Literal["positive", "negative"]
    quantities: list[Quantity]
    scope: list[str]
    temporal: str
    modality: str


class Interpretation(_Strict):
    target: Literal[
        "formal_requirement",
        "formal_authority",
        "event",
        "observed_practice",
        "reported_statement",
        "value_accuracy",
        "current_state",
        "historical_state",
    ]
    components: list[Component] = Field(
        min_length=1,
        max_length=20,
        description="Independently asserted propositions joined as logical AND. A conditional permission or obligation is ONE component containing all its conditions. Never assert its premise separately or link components by IDs to express implication.",
    )
    ambiguities: list[str] = Field(
        description="Actual competing plausible readings or material missing claim meaning, such as unspecified currency or scope. Return [] for unambiguous wording; comparator normalization explanations and evidence gaps are not ambiguities."
    )
    search_queries: list[str] = Field(min_length=1, max_length=12)


class _FindingSelection(_Strict):
    component_id: str
    evidence_id: str
    relationship: Literal["supports", "contradicts", "qualifies", "context", "unresolved"]
    reason: str = Field(min_length=1)
    scope_fit: Literal["yes", "no", "unknown"]
    time_fit: Literal["yes", "no", "unknown"] = Field(
        description="Applicability to evaluating the target period, including counterevidence; not whether dates match or the claim is true."
    )
    directness: Literal["direct", "indirect"]
    limitations: list[str]
    basis: Literal[
        "direct_statement",
        "recorded_action",
        "reported_statement",
        "independent_validation",
        "contextual",
    ]


class Evaluation(_Strict):
    findings: list[_FindingSelection] = Field(max_length=160)
    unresolved_questions: list[str]


def _selection_model(component_ids: list[str], evidence_ids: list[str]) -> type[_Strict]:
    if not evidence_ids:
        return create_model(
            "Evaluation",
            __base__=Evaluation,
            findings=(list[_FindingSelection], Field(max_length=0)),
        )
    selection = create_model(
        "FindingSelection",
        __base__=_FindingSelection,
        component_id=(Literal[tuple(component_ids)], ...),
        evidence_id=(Literal[tuple(evidence_ids)], ...),
    )
    return create_model(
        "Evaluation",
        __base__=Evaluation,
        findings=(
            list[selection],
            Field(max_length=min(160, 2 * len(component_ids) * len(evidence_ids))),
        ),
    )


class ClaimCheck(_Strict):
    component_id: str
    valid: bool
    reason: str = Field(min_length=1)


class OmittedClaimSpan(_Strict):
    claim_quote: str = Field(
        min_length=1,
        description="Exact original-claim substring whose meaning is NOT represented by any current component.",
    )
    reason: str = Field(
        min_length=1,
        description="Explain the specific missing meaning; this is not a place for success commentary.",
    )


class InterpretationVerification(_Strict):
    component_checks: list[ClaimCheck]
    omitted_claim_spans: list[OmittedClaimSpan] = Field(
        description="Concrete missing claim spans only. Return [] when every material assertion is represented."
    )


class _MeaningCheck(_Strict):
    valid: bool
    reason: str = Field(
        min_length=1,
        description="Concise grounded explanation. If invalid, name the incorrect field and its defect; an explanation affirming every field means valid=true.",
    )


def _check_map(
    name: str, keys: list[str], check_model=_MeaningCheck, models=None
) -> type[_Strict]:
    return create_model(
        name,
        __base__=_Strict,
        **{
            f"check_{index}": ((models or {}).get(key, check_model), Field(alias=key))
            for index, key in enumerate(keys)
        },
    )


def _claim_verifier_model(component_ids: list[str]) -> type[_Strict]:
    return create_model(
        "InterpretationVerification",
        __base__=InterpretationVerification,
        component_checks=(_check_map("ComponentChecks", component_ids), ...),
    )


def _verbatim_claim_kind(claim: str) -> str | None:
    if re.search(
        r"\b(?:if|unless|when|whenever|provided|providing|subject\s+to|as\s+long\s+as|on\s+condition\s+that)\b",
        claim,
        re.IGNORECASE,
    ):
        return "conditional"
    if re.search(r"\b(?:all|every|each)\b", claim, re.IGNORECASE):
        return "quantified"


def _interpretation_model(claim: str) -> type[_Strict]:
    # Coarser assessment preserves shared conditions/scope without inventing predicate joins.
    fields = {}
    kind = _verbatim_claim_kind(claim)
    if kind:
        component = create_model(
            "ConditionalComponent" if kind == "conditional" else "QuantifiedComponent",
            __base__=Component,
            text=(Literal[claim], ...),
            claim_quote=(Literal[claim], ...),
        )
        fields["components"] = (
            list[component],
            Field(
                min_length=1,
                max_length=1,
                description="Keep this complete original statement as one proposition. Preserve every condition, quantifier, predicate, shared scope and timing; do not assert conditions or universal conjuncts separately.",
            ),
        )
    if _normative_threshold_claim(claim):
        fields["target"] = (Literal["formal_requirement"], ...)
    return (
        create_model("Interpretation", __base__=Interpretation, **fields)
        if fields
        else Interpretation
    )
