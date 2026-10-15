"""Claim splitting with a clear, explicit proposer prompt + graceful fallback.

Splits a claim into atomic components (one LLM call), then verifies the split (one LLM call)
with a single repair. If the verifier still disagrees after that repair, it does NOT crash —
it flags the offending component(s) as ``label_status="undecisive"`` and proceeds (accepted
tradeoff), so one label disagreement can never abort a whole claim.

`claim_interpreter.py` is left untouched; the schema builders, verifier model, number check
and span check are imported from it / `claim_spans`.

    uv run python -m decidr.claims.split            # live split of a sample claim (needs Ollama)
"""

from __future__ import annotations

from datetime import date

from decidr.claim_interpreter import (
    VALIDATION_METHOD,
    Provider,
    ProviderError,
    _claim_verifier_model,
    _complete,
    _interpretation_model,
    _validate_claim_numbers,
)
from decidr.claims.spans import exact_claim_span
from decidr.constants import DEFAULT_AS_OF

# --------------------------------------------------------------------------- #
# Prompts                                                                      #
# --------------------------------------------------------------------------- #

# Explicit, stepwise, example-driven so a small local model can follow it.
PROPOSER_INSTRUCTION = """
You break ONE claim into its atomic parts. You do NOT decide if it is true. You do NOT look at any
evidence. Return only the structured interpretation.

HOW TO WORK
1. Read the whole claim.
2. Choose ONE target for the claim (see TARGET).
3. Split the claim into components — one per independently asserted thing. Preserve every part:
   keep each distinct quantity, threshold, scope and timing assertion. A before/after timing
   assertion is its own component. A conditional ("if P then X") stays as ONE component with its
   condition inside it; never assert the condition separately. Keep "all/every/each" statements as
   one component with all their parts.
4. Fill every field for each component (see FIELDS). Copy numbers, scope, timing and negation exactly.
5. Write short search_queries and list any genuine ambiguities.

FIELDS (per component)
- id: a short unique id, e.g. "c1", "c2".
- text: a short restatement of THIS part only. It may explain the quote but must add no new facts.
- claim_quote: copy the EXACT words from the claim for this part — character-for-character substring.
  Do not reword, shorten oddly, or paraphrase. It must appear verbatim in the claim.
- predicate: the MAIN VERB of this part — what it asserts. NOT the object.
    * "Discounts above 15% require Head of Finance approval" -> predicate = "require".
      "Head of Finance approval" is the OBJECT; it is NOT the predicate.
    * Keep a RULE verb (require / must / permit / prohibit) separate from an EVENT verb
      (an approval that occurred -> "approve"). "require approval" (a rule) is not "approved" (an event).
- polarity: "positive", or "negative" if the claim negates this part (not / never / no).
- entities: the named roles, people, records or things in this part, e.g. ["Head of Finance", "discount"].
- quantities: each number as {value, unit, comparator}. value = digits only (convert words, drop commas).
  comparator:
    * "gt"  = above / greater than / more than (strict, boundary excluded)   e.g. "above 15%" -> gt
    * "gte" = at least / N or greater / N and above (boundary included)
    * "lt"  = below / less than
    * "lte" = at most / up to / within N (upper bound)                        e.g. "within 7 days" -> lte
    * "eq"  = exactly / the threshold is N
  Use the comparator the claim states. Do NOT invent an inclusive/exclusive range the claim did not state.
- scope: conditions that limit this part, e.g. ["new-business deals"]. Keep start-point conditions.
- temporal: the time wording for this part as stated ("current", "before X", or a date). ALWAYS
  capture any date mentioned in the claim here — INCLUDING a "dated ..." framing date (e.g. a claim
  starting "In the recorded email dated 19 May 2025, ..." puts "19 May 2025" in the temporal of the
  component it describes). Use "" only when the claim states no time for this part.
- modality: obligation/permission wording ("required", "must", "may") or "" if none.

TARGET (choose exactly ONE for the whole claim)
- formal_requirement: the claim is about WHAT a rule/policy says — a requirement, deadline or threshold.
- formal_authority: the claim is about WHO has the right/role to approve, delegate or decide. If the
  claim names an approver or authorised decision-maker, use this — even if it also mentions a threshold.
  A threshold qualifier does NOT turn a "who holds the right" claim into a "what a policy requires" claim.
- event: the claim is that a specific thing HAPPENED once (an approval occurred, a deploy shipped).
- observed_practice: the claim is about how things are ACTUALLY done in general.
- reported_statement: the claim is about what someone SAID or recorded.
- value_accuracy: the claim explicitly says a stored value is CORRECT. (If the claim only says a value
  was recorded, that is NOT value_accuracy — do not add accuracy.)
- current_state / historical_state: the claim is about the actual operational state now / in the past,
  not the text of a rule.
Notes: a formal_requirement or formal_authority claim can be about the present OR the past — put that
time in temporal; do NOT reclassify it as observed_practice. The word "current" alone never decides the
target. A generic statement assigning a decision to a role can be formal_authority even without the word
"formal". If both a role-assignment reading and an actual-practice reading are genuinely plausible, record
that in ambiguities instead of silently choosing.

DO NOT
- Do not treat a recorded value as accurate, a report as an event, an approval action as authority,
  a proposed change as adopted, a review date as an expiry, or a current state as historical.
- Do not add implications. "Consultation" does not assert agreement, success, or an exception-free process.
- Do not invent names, document IDs, quantities, or answers.

AMBIGUITIES
Only list genuine competing readings or material missing meaning (e.g. unspecified currency or scope).
Return [] for plain wording. Explaining a normalization (e.g. "above" -> gt) is NOT an ambiguity, and a
lack of evidence is NOT an ambiguity.

SEARCH_QUERIES
Short, varied retrieval phrases drawn from the claim. Keep exact record identifiers (e.g. DEAL-014) intact.

WORKED EXAMPLES (invented — learn the SHAPE, do not copy this wording)

A) RULE with a threshold and a timing part -> target formal_requirement
Claim: "Refunds over $500 must be logged within 3 business days."
  c1: predicate "log"        quote "Refunds over $500 must be logged"
      entities ["refund"]    quantities [{value "500", unit "$", comparator "gt"}]  modality "must"
  c2: predicate "log"        quote "within 3 business days"      (timing is its own component)
      quantities [{value "3", unit "business days", comparator "lte"}]  temporal "within 3 business days"

B) WHO holds a right -> target formal_authority (even though it says "may"/"must")
Claim: "Only the Regional Manager may authorise overtime."
  c1: predicate "authorise"  quote "Only the Regional Manager may authorise overtime"
      entities ["Regional Manager", "overtime"]  modality "may"

C) A specific thing HAPPENED once -> target event (predicate is the action that occurred)
Claim: "Server SRV-12 was rebooted by the on-call engineer on 2026-03-09."
  c1: predicate "reboot"     quote "Server SRV-12 was rebooted by the on-call engineer"
      entities ["SRV-12", "on-call engineer"]  temporal "on 2026-03-09"

D) HOW things are generally done -> target observed_practice
Claim: "Invoices are sent to clients by email through the billing portal."
  c1: predicate "send"       quote "Invoices are sent to clients by email through the billing portal"
      entities ["invoice", "client"]  scope ["by email through the billing portal"]
      (A manner/channel phrase like "by email" describes the one send action; a predicate is a verb
       such as "send", never a connective like "by" or "through".)

E) A "dated ..." framing date goes in temporal of the ONE action -> target reported_statement
Claim: "In the memo dated 4 March 2024, the CFO told staff to freeze new spending."
  c1: predicate "told"       quote "the CFO told staff to freeze new spending"
      entities ["CFO", "staff"]  temporal "4 March 2024"
      (The framing date "4 March 2024" is the temporal of the telling. It is NOT its own component,
       and "dated" is a verb for nothing here — there is one action: "told".)
"""

VERIFIER_INSTRUCTION = """Independently verify the proposed interpretation against the ORIGINAL claim.
This stage checks asserted meaning, not truth or evidential support. If the original claim explicitly
says a stored value is accurate, value_accuracy is the correct target even though accuracy has not
yet been established. Reject an added accuracy assertion only when the original merely reports a
stored value. Preserve ordinary bounds: 'within N units of time' means lte, not exact duration eq.
Check EVERY component and every original clause. Assess each structured component JOINTLY across
text, entities, predicate, polarity, quantities, scope, temporal and modality. A qualifier need not be
repeated in text if it is faithfully represented in its dedicated field. In particular, 'current' in
temporal preserves a current-time assertion even if the component text summarizes only the predicate.
Exact quotes alone do not establish semantic fidelity; check the meaning represented by the fields.
Check the TARGET against the semantic object: a current or past formal obligation/threshold remains
formal_requirement, and a documented approval/delegation right remains formal_authority. Assertions
identifying a formal approver or authorised decision-maker concern formal_authority,
even if they include a threshold qualifier. Do not replace WHO holds a right with WHAT is required.
Current and historical timing belongs in temporal; current_state/historical_state are actual operational states.
Do not reclassify a normative rule as observed practice just because it says current or past.
Reject invented scope/entities, missing conjuncts, polarity changes, quantity/unit/boundary changes,
missing timing, lost exceptions, changing requirement into practice, approval action into authority,
recorded value into value accuracy, reported statement into actual occurrence, proposed into adopted,
or current into historical state. A scalar 'threshold is N' asserts equality of a threshold value,
not a particular inclusive or exclusive range: reject invented gt/gte/lt/lte there. Quantities may
normalize number words but cannot change values.
Return component_checks as an object keyed by each and only each exact component ID, with valid and
reason for every key. Set that check's valid=false
only for a real error in that component. For a material assertion missing from all current components,
add omitted_claim_spans with an EXACT original-claim substring and the missing meaning. Otherwise use [].
Uncertainty explicitly retained in ambiguities is allowed; it must not be asserted as resolved.
Check ambiguity entries too: they need competing plausible readings or material missing meaning.
Mark the relevant component check invalid if an ordinary unambiguous comparator normalization is
mislabelled ambiguity; explanatory notes and evidence gaps are not ambiguous claim meanings.
Do not discard genuine unresolved currency, scope or referent details.
Generic role responsibility may be formal_authority even without the word formal. A present-tense
verb alone does not settle formal assignment versus actual practice; retain that ambiguity when material.
Consultation does not promise agreement or successful completion. Reject those added implications.
Conditions of a permission or obligation must remain attached to its proposition, not be split into
assertions that the condition occurs and the permission is unconditional.
Universal statements must preserve all conjuncts under the same quantifier, scope and timing.
Receiving approval is an action; being subject to a rule does not preserve that asserted action.
The assessment joins components as logical AND. Component-ID references in scope do not encode
implication. Reject a separately asserted premise or condition even if another component refers to it.
Judge only the CURRENT proposed interpretation against the original claim. No earlier candidate
or generation-repair feedback is part of this independent audit; do not speculate about prior defects.
There is no global verdict or issues field. Put positive explanations in the relevant check's reason.
Do not create an omission entry to say that nothing is missing; omission entries identify actual gaps.
"""


# --------------------------------------------------------------------------- #
# Split flow: propose -> verify -> one repair -> graceful undecisive fallback  #
# --------------------------------------------------------------------------- #


def _propose(claim: str, as_of: date | str, provider: Provider, feedback: str):
    data = {
        "original_claim": claim,
        "assessment_date": str(as_of),
        "validation_feedback": feedback,
    }
    output = _complete(provider, _interpretation_model(claim), PROPOSER_INSTRUCTION, data)
    ids = [component["id"] for component in output["components"]]
    if len(ids) != len(set(ids)):
        raise ProviderError("invalid_model_output", "Component identifiers are not unique.")
    return output, ids, data


def _number_error(claim: str, output: dict) -> str | None:
    """Run the deterministic number/identifier check WITHOUT crashing; return its reason or None.

    (It also normalises each component's claim_quote to its exact span as a side effect.)
    """
    try:
        _validate_claim_numbers(claim, output)
    except ProviderError as error:
        return str(error)
    return None


def _verify(claim: str, output: dict, ids: list[str], data: dict, provider: Provider):
    verification = _complete(
        provider,
        _claim_verifier_model(ids),
        VERIFIER_INSTRUCTION,
        {
            **{k: v for k, v in data.items() if k != "validation_feedback"},
            "proposed_interpretation": output,
        },
    )
    checks = [
        {"component_id": cid, **check} for cid, check in verification["component_checks"].items()
    ]
    if sorted(c["component_id"] for c in checks) != sorted(ids):
        raise ProviderError("invalid_model_output", "Verifier did not check every component once.")
    invalid = [c for c in checks if not c["valid"]]
    # Only keep omissions whose quote is a verbatim claim span; paraphrased ones are dropped
    # (the verifier's fault, not an actionable gap).
    real_omissions = []
    for omission in verification["omitted_claim_spans"]:
        span = exact_claim_span(claim, omission["claim_quote"])
        if span is not None:
            real_omissions.append({**omission, "claim_quote": span})
    return checks, invalid, real_omissions


def split_claim(claim: str, as_of: date | str, provider: Provider) -> dict:
    """Split a claim; one repair; then degrade to 'undecisive' instead of aborting."""
    if not isinstance(claim, str) or not claim.strip():
        raise ProviderError("interpretation_failure", "A non-empty claim is required.")

    feedback = ""
    last: tuple | None = None
    for _attempt in (1, 2):  # initial + one repair (no extra calls beyond the original design)
        try:
            output, ids, data = _propose(claim, as_of, provider, feedback)
        except ProviderError as error:
            # Malformed model output (unparseable / duplicate ids): retry; if it was the last
            # attempt there is nothing to degrade, so re-raise below via `last is None`.
            feedback = str(error)
            continue
        number_error = _number_error(claim, output)  # deterministic; does NOT crash
        checks, invalid, omissions = _verify(claim, output, ids, data, provider)
        if not number_error and not invalid and not omissions:
            output["semantic_validation"] = {
                "method": VALIDATION_METHOD,
                "status": "validated",
                "component_checks": checks,
            }
            return output
        feedback = "; ".join(
            ([number_error] if number_error else [])
            + [c["reason"] for c in invalid]
            + [o.get("missing_meaning", "missing") for o in omissions]
        )
        last = (output, checks, invalid, omissions, number_error)

    # Still unresolved after one repair -> TRADEOFF: flag, don't crash.
    if last is None:
        raise ProviderError("invalid_model_output", f"Could not parse a claim split: {feedback}")
    output, checks, invalid, omissions, number_error = last
    flagged = {c["component_id"] for c in invalid}
    for component in output["components"]:
        if component["id"] in flagged:
            component["label_status"] = "undecisive"
    output["semantic_validation"] = {
        "method": VALIDATION_METHOD,
        "status": "degraded_undecisive",
        "component_checks": checks,
        "unresolved_components": sorted(flagged),
        "unresolved_omissions": omissions,
        "number_warning": number_error,
        "note": (
            "Unresolved after one repair. Retained (components flagged undecisive / number gap "
            "recorded) rather than aborting the whole claim; downstream should treat flagged facets "
            "and any number_warning as uncertain."
        ),
    }
    return output


# --------------------------------------------------------------------------- #
# Demo / self-test                                                            #
# --------------------------------------------------------------------------- #


def main() -> None:
    from decidr.claim_interpreter import get_provider

    claim = "Discounts above 15% require Head of Finance approval before the deal is closed."
    try:
        provider = get_provider()
    except ProviderError as error:
        print(f"no local provider available: {error}")
        return
    result = split_claim(claim, DEFAULT_AS_OF, provider)
    print(f"claim: {claim}")
    print(f"split status: {result['semantic_validation']['status']}")
    for component in result["components"]:
        flag = component.get("label_status", "ok")
        print(f"  - {component['id']}: predicate={component.get('predicate')!r}  [{flag}]")


if __name__ == "__main__":
    main()
