"""Trimmed evidence reader: ONE batched LLM call, no per-passage verification (Phase 3b).

``claim_interpreter.evaluate_evidence`` makes a single batched read AND THEN fires one
extra LLM call per passage in ``_verify_passage_findings`` — that loop is the ~10-minute
cost. This module reuses the exact same batched read and the exact same *deterministic*
guards (boundary/number/identifier checks, whole-passage citation binding) but omits the
per-passage LLM verification, per the single-path decision to let the deterministic engine
do the judging.

`claim_interpreter.py` is left completely untouched; everything here is composed from its
public-enough helpers. Trust rails kept:
  * citations are whole frozen passages (start=0, end=len) — binding is exact by construction,
  * numeric / identifier / claim-boundary admission checks run identically.

Result: ~1 LLM call for the read (plus ~1 for interpret_claim) = ~2 per claim, seconds.

Demo (REQUIRES a local Ollama model running; counts the LLM calls to prove it is batched):
    DECIDR_ASSESSMENT_PROVIDER=ollama DECIDR_ASSESSMENT_MODEL=llama3.1:8b \
        uv run python -m decidr.fast_reader
"""

from __future__ import annotations

from datetime import date

from decidr.claim_interpreter import (
    _EVALUATION_INSTRUCTION,
    _IDENTIFIERS,
    CITATION_METHOD,
    NUMERIC_VALIDATION_LIMITATIONS,
    NUMERIC_VALIDATION_METHOD,
    Provider,
    ProviderError,
    _complete,
    _evidence_data,
    _selection_model,
    _validate_evidence_numbers,
    _validated_retry,
    claim_evidence_exclusion,
)


def _evaluate_evidence_fast_once(
    interpretation: dict,
    claim: str,
    passages: list[dict],
    as_of: date | str,
    provider: Provider,
    feedback: str = "",
) -> dict:
    """One batched read + deterministic admission checks. No per-passage LLM verification.

    Mirrors ``claim_interpreter._evaluate_evidence_once`` up to the point where the original
    calls ``_verify_passage_findings``; stops there and returns deterministically-checked
    findings.
    """
    evidence = {p["evidence_id"]: p for p in passages}
    if len(evidence) != len(passages):
        raise ProviderError(
            "interpretation_failure", "Selected passages contain duplicate evidence identifiers."
        )
    components = {component["id"]: component for component in interpretation["components"]}
    component_ids = set(components)
    data = {
        **_evidence_data(interpretation, claim, passages, as_of),
        "validation_feedback": feedback,
    }
    # THE single batched read: all passages + all components -> all findings, one LLM call.
    output = _complete(
        provider,
        _selection_model(list(components), list(evidence)),
        _EVALUATION_INSTRUCTION,
        data,
    )

    binding_counts: dict[tuple[str, str], int] = {}
    for finding in output["findings"]:
        binding = (finding["component_id"], finding["evidence_id"])
        binding_counts[binding] = binding_counts.get(binding, 0) + 1
        if binding_counts[binding] > 2:
            raise ProviderError(
                "invalid_model_output",
                "A component/passage pair exceeds the two-relationship representation limit.",
            )

    admission_adjustments = []
    for finding in output["findings"]:
        p = evidence.get(finding["evidence_id"])
        if finding["component_id"] not in component_ids or p is None:
            raise ProviderError(
                "invalid_model_output",
                "A finding references an unknown component, passage or source.",
            )
        # Whole-passage citation binding: the quote IS the frozen passage text.
        finding.update(
            source_id=p["source_id"],
            quotation=p["text"],
            locator=p.get("locator", ""),
            start=0,
            end=len(p["text"]),
        )
        boundary_exclusion = claim_evidence_exclusion(
            components[finding["component_id"]], finding, interpretation["target"]
        )
        if boundary_exclusion:
            adjustment = {
                "component_id": finding["component_id"],
                "evidence_id": finding["evidence_id"],
                "proposed_relationship": finding["relationship"],
                "admitted_relationship": "context",
                "reason": boundary_exclusion,
            }
            admission_adjustments.append(adjustment)
            record = getattr(provider, "record_admission_adjustment", None)
            if callable(record):
                record(adjustment)
            finding["relationship"] = "context"
            finding["reason"] = (
                "Retained as context after a deterministic admission check. " + boundary_exclusion
            )
            finding["limitations"].append(boundary_exclusion)
        _validate_evidence_numbers(components[finding["component_id"]], finding, p)
        if (
            interpretation["target"] == "value_accuracy"
            and finding["relationship"] == "supports"
            and finding["basis"] != "independent_validation"
        ):
            raise ProviderError(
                "invalid_model_output",
                "A recorded value was incorrectly treated as independently accurate.",
            )
        if finding["relationship"] in {"supports", "contradicts"}:
            component = components[finding["component_id"]]
            required_ids = {
                i.casefold() for i in _IDENTIFIERS.findall(" ".join(component["entities"]))
            }
            if not required_ids:
                required_ids = {i.casefold() for i in _IDENTIFIERS.findall(claim)}
            source_ids = {
                i.casefold()
                for i in _IDENTIFIERS.findall(p["text"] + " " + (p.get("heading") or ""))
            }
            if required_ids and source_ids and required_ids.isdisjoint(source_ids):
                raise ProviderError(
                    "invalid_model_output",
                    "A finding uses a different record identifier without a documented link.",
                )

    output["semantic_validation"] = {
        "method": "deterministic-only",
        "status": "not_verified",
        "finding_count": len(output["findings"]),
        "admission_adjustments": admission_adjustments,
        "citation_method": CITATION_METHOD,
        "numeric_validation_method": NUMERIC_VALIDATION_METHOD,
        "numeric_validation_limitations": list(NUMERIC_VALIDATION_LIMITATIONS),
        "note": (
            "Per-passage LLM verification skipped (trimmed reader). Trust comes from verbatim "
            "citation binding + deterministic engine scoring."
        ),
    }
    return output


def evaluate_evidence_fast(
    interpretation: dict, claim: str, passages: list[dict], as_of: date | str, provider: Provider
) -> dict:
    """Public entry: validated-retry around the single batched read (no verify loop)."""
    return _validated_retry(
        "evidence_evaluation",
        provider,
        lambda feedback: _evaluate_evidence_fast_once(
            interpretation, claim, passages, as_of, provider, feedback
        ),
    )


# --------------------------------------------------------------------------- #
# Demo / self-test (needs a live Ollama model; proves the read is 1 call)      #
# --------------------------------------------------------------------------- #


class _CountingProvider:
    """Wrap a provider and count .complete() calls, to prove batching."""

    def __init__(self, inner: Provider) -> None:
        self.inner = inner
        self.calls = 0

    def complete(self, schema: dict, prompt: str) -> dict:
        self.calls += 1
        return self.inner.complete(schema, prompt)

    def provenance(self) -> dict:
        return self.inner.provenance()

    def __getattr__(self, name):  # forward record_* hooks
        return getattr(self.inner, name)


def main() -> None:
    from decidr.claim_interpreter import get_provider, interpret_claim
    from decidr.finding_shim import load_corpus_snapshot

    claim = "Discounts above 15% require Head of Finance approval before the deal is closed."
    as_of = date(2026, 7, 31)

    try:
        provider = _CountingProvider(get_provider())
    except ProviderError as error:
        print(f"no local provider available: {error}")
        return

    interpretation = interpret_claim(claim, as_of, provider)
    after_interpret = provider.calls
    print(f"interpret_claim: {after_interpret} LLM call(s); facets:")
    for component in interpretation["components"]:
        print(f"  - {component['id']}")

    snapshot = load_corpus_snapshot()
    pol01 = [p for p in snapshot.evidence_by_source.get("phase1:POL-01", [])]
    passages = [
        {
            "evidence_id": p.evidence_id,
            "source_id": p.source_id,
            "text": p.text,
            "locator": p.locator,
            "heading": getattr(p, "heading", None),
        }
        for p in pol01[:6]
    ]

    output = evaluate_evidence_fast(interpretation, claim, passages, as_of, provider)
    read_calls = provider.calls - after_interpret
    print(f"\nevaluate_evidence_fast: {read_calls} LLM call(s) for {len(passages)} passages")
    print(f"total LLM calls this claim: {provider.calls}")
    print(f"findings: {len(output['findings'])}")
    for finding in output["findings"][:6]:
        print(f"  - {finding['component_id']} :: {finding['relationship']} ({finding['evidence_id']})")


if __name__ == "__main__":
    main()
