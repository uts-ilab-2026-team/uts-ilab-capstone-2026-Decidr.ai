> **Status: archived instructions / research history.** Archived interpretation-1.0 instructions. The employee flow no longer calls this interpreter.
> Use [current employee guidance](claim_first.md), [architecture](architecture.md) and the
> [documentation inventory](documentation_inventory.md). The original body below is retained.

# Controlled local interpretation for Approach B

The employee page calls the replaceable `Interpreter` interface before confirmation.
`OllamaInterpreter` uses local HTTP `/api/chat`, JSON Schema in `format`, non-streaming
responses, and Pydantic validation of `message.content`. Prompt and schema versions are
both `interpretation-1.0`. The default model is `llama3.2:latest`, temperature is zero,
timeout is 60 seconds, context capacity is 8192 tokens and generation is bounded to
2048 tokens. Configure the `interpreter` object in `configs/approach_b_graph_llm.yaml`.
The separate existing `llm_enabled` option does not enable this interpreter or give an
LLM authority in any assessment stage.

The generic schema represents a question as atomic items with complete predicate/object,
intent, assessment target, requested field, constraints, modality, polarity and exact
source spans. Decision-rights documents describe prescribed rules; operational behaviour
describes actual practice; database, CRM and audit-log contents describe recorded state.
The requested answer (such as an unknown role) is not a missing interpretation input.
No candidate portfolio is read by the successful local interpretation path. No corpus
is sent. Optional conversation context is limited to four entries of 2000 characters;
the employee page incorporates the employee's clarification into the question.

All schema fields are required, nullable where appropriate; extra keys and null-placeholder
strings are rejected. Validation checks numeric/date grounding, common numeric operators
and temporal expressions, action completeness, source-span containment, explicit modality
and negation, and target/intent consistency. These are conservative safeguards, not a
proof of arbitrary natural-language equivalence; employee confirmation remains mandatory.
Verbatim temporal constraints pass into claim conditions; dates can also be explicitly
set during confirmation. The interpreter does not invent effective organisational dates.

A failed structured response gets at most one repair request. Its message contains only
validation errors and the previous structured response; the schema remains in `format`.
Transport failures fall back immediately. The default fallback calls the existing
`ConstrainedClaimParser`; unresolved novel questions remain editable. Configure fallback
as `error` to fail closed instead. Failed repair never becomes a validated interpretation.
Repeated clarification wording or the same unresolved material fields moves to editing;
the employee must explicitly attest that missing fields were resolved before assessment.
Each atomic item can be edited, confirmed and assessed separately; the session retains
completed item results and displays the completion count.

Only the confirmed claim enters the existing retrieval, graph and deterministic reasoning
pipeline. Ollama cannot supply evidence relationships, credibility, verdict, confidence or
organisational answers. No new assessment or review table writes occur. Model, versions,
latency, repair and fallback status are session-level technical provenance. The adapter
logs neither prompts nor hidden reasoning, credentials or local paths. The previous global
workspace-path startup log has been removed. The API requires no key and accepts only a
loopback HTTP base URL. No hosted integration is provided.

Automated tests use a mocked API and disable real model reachability/generation globally.
Coverage includes schema/repair/fallback, timeouts, multiple atomic questions, explicit
threshold/date preservation, independence from portfolio values, prohibited answer fields,
action completeness, target semantics, repeated clarification, Phase 1 exclusion, empty
corpus insufficiency, and the Streamlit confirmation gate. The dataset command rebuilds
only the active Phase 2 ledger and ordinary ingestion exports; it is not formal evaluation.

## Implementation verification

`uv run ruff check .` passes. `uv run pytest -q` passes 161 tests, including
23 interpretation/confirmation regressions. `uv run python -m decidr.dataset`
registers 45 sources (44 ingested, one excluded), 812 evidence units and zero warnings.
The active Phase 2 fingerprint is
`766ca57488795f6e0d7e587f1bb1db36356112b9938c9e53efbed34510ba116e`.

The live smoke question did **not** meet semantic acceptance. The last completed run
returned `predicate: has`, a truncated atomic question (`Who`), a null process, and an
object containing the authority wording rather than the extracted business object.
It did correctly produce `prescribed_rule`, `authorised_role`, and a null clarification.
Validation rejected this output and its single repair; deterministic fallback was used.
Total interpretation latency, including repair, was 6801.56 ms. Earlier diagnostic runs
also encountered malformed output and a timeout. No failed output was accepted as a
validated interpretation. This first layer therefore establishes a controlled failure
boundary; reliable live interpretation with this model remains an open limitation.

Existing uncommitted work was retained. No API key, hosted API, commit, push, merge,
history rewrite, freeze-manifest change, formal/held-out evaluation or persistent
Streamlit server was used.
