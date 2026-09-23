# Interpretation 2.0 Stage 2A — retrieval-first intent spike

Stage 2A is an additive, experimental and unpromoted replacement experiment for the
raw-question-to-complete-QueryFrame approach. It responds to the failed llama3.1 and Qwen
interpretation-1.3 development gates. It is not evidence of improved model accuracy: no Stage 2A
live-model check has been run.

Interpretation 1.3 remains available as an experimental record. Stage 2A is not connected to the
employee Streamlit page and cannot construct an `AtomicClaim`, evidence relationship, credibility
assessment, verdict, confidence value or recommended action.

## Retrieval-first boundary

The execution order is:

1. Run FTS5 lexical retrieval directly against the complete employee question.
2. Filter evidence using ingested release metadata, configured release purpose and ingestion
   eligibility. Source-ID naming is not used by the Stage 2A path.
3. Optionally run locally available semantic retrieval. Any semantic failure is recorded and
   produces an empty semantic ranking without removing lexical results.
4. Fuse the rankings and build an allowlisted context package.
5. Extract protected question values deterministically.
6. Make at most one local model call for the complete question.
7. Validate or immediately use the generic deterministic intent fallback. There is no model
   repair call.

The default context limits are five passages, 800 characters per passage and 4,000 passage
characters overall. Text is clipped at a sentence boundary where possible. Model-visible passage
metadata is restricted to evidence ID, source ID, title or locator, source type, lifecycle and
effective dates, retrieval ranks and bounded text. Filesystem paths, arbitrary metadata and full
documents are excluded. Passage text is explicitly marked as untrusted retrieved context.

## Schema

`QueryIntentSet` contains:

- `version`: `interpretation-2.0-stage-2a`;
- `provenance`: method, model name, retrieval-first marker and recorded representation corrections;
- ordered `intents`.

Each `QueryIntent` contains only:

- exact subquestion text and question offsets;
- generic query operator;
- requested fields, using `claim_assessment` rather than `truth_status`;
- optional knowledge target (`prescribed_rule`, `actual_practice`, `recorded_state`, or
  `unspecified`);
- grounded search phrases;
- exact question-span conditions;
- deterministic protected values;
- unresolved referents;
- clarification flag and optional clarification question.

A search phrase identifies either the question or one retrieved passage as its origin. It has
exact offsets into that origin and, for retrieved context, the evidence and source IDs.

Dates, quantities, identifiers, modality, negation, exclusions and explicit named entities are
extracted before the model call and compared exactly after parsing. Identifiers and quantities
remain distinct types. Calendar uses of “May” are distinguished from modal uses.

Strict schemas reject factual answers, answer values, AtomicClaim fields, approver or threshold
answer fields, evidence relationships, support or contradiction labels, credibility, verdict,
confidence and recommended actions. A query operator does not itself force a knowledge target;
non-unspecified targets require explicit question wording.

## Validation and fallback

Only exact offset completion, harmless null-string recovery and deterministic ordering are
normalised. Every such correction is recorded. A compound response must contain every verbatim
subquestion exactly once. Missing, duplicated or merged subquestions fail; a uniquely reorderable
response is restored to question order with an explicit correction record.

Invalid transport, JSON, schema, grounding, protected-value or compound output immediately uses a
generic deterministic fallback. The fallback preserves question spans and protected values,
recognises only generic interrogative operators, leaves the knowledge target unspecified and
requires clarification for unresolved standalone pronouns. It does not consult the claim
portfolio, answer the question, construct a claim or infer an outcome.

## Promotion status

Stage 2A is not promoted. Its tests use mocked transports only. A separately authorised controlled
local development check is required before any claim about model accuracy or any UI promotion can
be considered.
