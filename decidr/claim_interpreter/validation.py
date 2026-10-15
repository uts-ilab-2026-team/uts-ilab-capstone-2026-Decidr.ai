"""Deterministic numeric validation of interpretation and evidence output."""

from decimal import Decimal, InvalidOperation
import json

from decidr.claim_interpreter.admission import _threshold_support_exclusion
from decidr.claim_interpreter.providers import ProviderError
from decidr.claim_interpreter.text_numeric import (
    _IDENTIFIERS,
    _boundary,
    _numbers,
    _numeric_unit,
    _scalar_observations,
)
from decidr.claims.spans import exact_claim_span


def _validate_claim_numbers(claim: str, output: dict) -> None:
    ids = {x.casefold() for x in _IDENTIFIERS.findall(claim)}
    interpreted = " ".join(
        json.dumps(
            {key: value for key, value in component.items() if key != "id"}, ensure_ascii=False
        )
        for component in output["components"]
    )
    extracted_ids = {x.casefold() for x in _IDENTIFIERS.findall(interpreted)}
    if ids != extracted_ids:
        raise ProviderError(
            "invalid_model_output", "The interpretation omitted or invented a record identifier."
        )
    extracted_numbers = set()
    for component in output["components"]:
        original_span = exact_claim_span(claim, component["claim_quote"])
        if original_span is None:
            raise ProviderError(
                "invalid_model_output", "An interpretation quote is not an exact claim span."
            )
        component["claim_quote"] = original_span
        for quantity in component["quantities"]:
            try:
                number = Decimal(quantity["value"].replace(",", ""))
            except InvalidOperation as exc:
                raise ProviderError(
                    "invalid_model_output", "An extracted quantity is not numeric."
                ) from exc
            if number not in _numbers(claim):
                raise ProviderError(
                    "invalid_model_output", "The interpretation invented or changed a quantity."
                )
            extracted_numbers.add(number)
            boundary = _boundary(component["claim_quote"], quantity["value"])
            if boundary and boundary != quantity["comparator"]:
                raise ProviderError(
                    "invalid_model_output",
                    "The interpretation changed an inclusive or exclusive boundary.",
                )
    # Years and versions may be entities or temporal qualifiers, not measured quantities.
    non_quantity_context = " ".join(
        component["temporal"] + " " + " ".join(component["entities"])
        for component in output["components"]
    )
    if not _numbers(claim) <= extracted_numbers | _numbers(non_quantity_context):
        raise ProviderError(
            "invalid_model_output", "The interpretation omitted a stated quantity."
        )


def _validate_evidence_numbers(component: dict, finding: dict, passage: dict) -> None:
    if finding["relationship"] != "supports":
        return
    threshold = _threshold_support_exclusion(component, finding["quotation"])
    if threshold:
        raise ProviderError("invalid_model_output", threshold)
    if finding["directness"] != "direct":
        return
    observations = _scalar_observations(finding["quotation"])
    for quantity in component["quantities"]:
        # Different ranges can entail one another in opposite directions depending on
        # the predicate. The semantic verifier handles that role, rather than assuming equality.
        if quantity["comparator"] != "eq":
            continue
        unit = _numeric_unit(quantity["unit"])
        if not unit:
            continue
        dimension, multiplier = unit
        value = Decimal(quantity["value"].replace(",", "")) * multiplier
        comparable = {number for number, kind in observations if kind == dimension}
        if comparable and value not in comparable:
            raise ProviderError(
                "invalid_model_output",
                "Direct support changed an explicit scalar value or fixed duration.",
            )
        if (
            not comparable
            and dimension.startswith("currency:")
            and dimension != "currency:unspecified"
        ):
            explicit_currencies = {
                kind for _, kind in observations if kind.startswith("currency:")
            }
            if explicit_currencies and "currency:unspecified" not in explicit_currencies:
                raise ProviderError(
                    "invalid_model_output",
                    "Direct support substituted a different explicitly named currency without an exchange basis.",
                )
