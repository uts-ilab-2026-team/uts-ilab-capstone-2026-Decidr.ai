"""Generic LLM call → schema-validate → one-shot repair engine."""

import json

from pydantic import ValidationError

from decidr.claim_interpreter.providers import Provider, ProviderError
from decidr.claim_interpreter.schemas import _Strict


def _model_prompt(schema: dict, instruction: str, data: dict) -> str:
    return (
        instruction
        + "\nOUTPUT_SCHEMA (all required fields must be supplied with the declared types):\n"
        + json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
        + "\nDATA:\n"
        + json.dumps(data, ensure_ascii=False, default=str, separators=(",", ":"))
    )


def _complete(provider: Provider, model: type[_Strict], instruction: str, data: dict) -> dict:
    schema = model.model_json_schema()
    prompt = _model_prompt(schema, instruction, data)
    for attempt in range(2):
        try:
            output = provider.complete(schema, prompt)
            result = model.model_validate(output).model_dump(by_alias=True)
            if attempt:
                _record_validation(provider, model.__name__, "invalid_model_output", True)
            return result
        except ProviderError:
            raise
        except (ValidationError, TypeError, ValueError) as exc:
            fields = (
                [
                    {
                        "field": ".".join(str(part) for part in error["loc"]),
                        "message": error["msg"],
                        "type": error["type"],
                    }
                    for error in exc.errors(include_input=False, include_url=False)
                ]
                if isinstance(exc, ValidationError)
                else [
                    {
                        "field": "response",
                        "message": "Expected schema-valid fields.",
                        "type": type(exc).__name__,
                    }
                ]
            )
            record_fields = getattr(provider, "record_validation_fields", None)
            if callable(record_fields):
                record_fields(model.__name__, fields)
            if attempt:
                raise ProviderError(
                    "invalid_model_output",
                    f"The local model returned invalid {model.__name__} fields after one schema repair: "
                    + "; ".join(field["field"] + ": " + field["message"] for field in fields)[
                        :900
                    ],
                ) from exc
            _record_validation(provider, model.__name__, "invalid_model_output", False)
            prompt += (
                "\nSCHEMA REPAIR: The previous JSON was invalid. Return a COMPLETE corrected object, not a patch. Re-read the supplied data; never invent values to satisfy a schema. Numeric quantities must contain the actual numeric value from the claim. No empty placeholder values.\nValidation error: "
                + json.dumps(fields, ensure_ascii=False, separators=(",", ":"))[:3000]
            )
        except Exception as exc:
            raise ProviderError(
                "provider_failure", "The configured interpreter failed to complete."
            ) from exc
    raise AssertionError("unreachable")


def _record_validation(provider: Provider, stage: str, code: str, repaired: bool) -> None:
    record = getattr(provider, "record_validation_attempt", None)
    if callable(record):
        record(stage, code, repaired)
