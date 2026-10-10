# Bounded interpretation proposals

Adapted from Apaar's unpushed interpretation-layer ZIP supplied for review,
on team baseline `49b6c1f62e940f3053071fc64f9d9d53993fe908`.
The endpoint and proposal contract retain his retrieval-to-review workflow.
The overlap-based relationship and quality heuristics have been replaced.
The controlled 100-case results and private provisional answers are not imported.

## Request and response

Authenticated `POST /api/corpus/interpret` accepts:

```json
{
  "claim": "Written approval is required.",
  "facet": "Written approval is required.",
  "assessment_target": "formal_rule",
  "as_of": "2026-06-17",
  "ranked_group_limit": 8,
  "max_inputs": 12
}
```

The original claim is preserved. The facet defaults to that exact claim, controls
retrieval, and is the proposition compared. Its relationship to the whole claim
still requires review. If the target is omitted it is proposed from the facet
and disclosed as inferred. Inputs must use complete propositions, not labels
such as "approval timing". No general natural-language entailment is implemented.

Each proposal includes an exact citation, the original passage, source context,
retrieval provenance, comparison method and review reasons. Current-index source
context is not an immutable assessment snapshot or a verified quotation of a role.
The source-context object omits the original file path and metadata notes.

The response always reports `assessment_ready: false`, `review_status: unreviewed`,
`persisted: false`, and `quality_status: not_assessed`. Its assessment request is
an editable draft. No matches or unresolved parent-origin packet consistency
produce `assessment_request: null` plus `draft_blockers`; proposals remain visible.

## Comparison boundaries

- Ordered wording is compared after limited typography normalisation. Inclusive
  percentage wording "at least X%", "X% or more" and "X% or greater" is canonicalised.
- Only identical propositions and complete "X is/are required" versus "X is/are
  not required" pairs can propose decisive relationships. Changed actors, timing,
  quantifiers, other numerical bounds, paraphrases and other negation abstain.
- A matching identifier cannot override an explicit scope conflict. All requested
  identifiers must match when the citation supplies identifiers.
- Reported statements take precedence over normative vocabulary. Interviews,
  communications and meetings propose recorded statements rather than effective
  formal rules. This intentionally leaves some meeting decisions for review.
- Conflicting exact positive and negative propositions retain the full passage
  as unresolved. Other qualifications still require inspection of full context.
- Historical approval is preserved separately from superseded lifecycle. Explicit
  intervals and the unresolved supersession boundary follow existing conventions.
- Matching date strings, interview dates or arbitrary structured date fields do
  not verify event timing. Invalid date strings remain reviewable.

These restrictions reduce false decisive proposals at the cost of recall. They
are not a validated replacement for an automatic semantic interpreter. No source
IDs, claim IDs, expected benchmark outcomes or reference labels drive decisions.

## Assessment boundary

Authority remains `null`; independence remains unverified. Directness, specificity
and completeness are zero placeholders labelled unassessed, not measured scores.
A reviewer must supply justified eligibility and quality judgements before using
`/api/corpus/assess-supplied`. Untouched drafts cannot produce admitted decisive
edges because authority remains unresolved. Changing a flag is not proof of human
review; the existing assessment assurance explicitly retains that limitation.

Type-to-source-class and approval suggestions are provisional and use existing
configured vocabulary. An approved-policy type does not verify organisational
authority. These mappings need independent review, especially outside this corpus.
The existing assessment endpoint still validates configured keys and citations.

The endpoint reads SQLite in read-only/query-only mode. It calls no language
model, writes no graph or history, and performs no assessment automatically.
No frontend, credibility weights or existing assessment response fields change.

## Verification

The isolated baseline plus this adaptation passed 553 tests and 8 subtests,
including 51 new proposal tests. Existing FastAPI/Starlette deprecation warning
remains. Formatting and lint checks passed. Verification here used Python 3.12;
the project's declared Python 3.11 environment must rerun tests before commit.

New tests reproduce reversed actors, facet/claim confusion, identifier/scope
conflicts, threshold differences, historical intervals, missingness, reported-rule
separation, invalid dates, long Unicode citations, API authentication, rejected
requests, empty retrieval, missing parent provenance, unchanged database bytes and
preserved assessment assurance. Passing these tests demonstrates these boundaries,
not independently measured classification accuracy or Phase 3 readiness.

```bash
python -m pytest tests/test_interpretation_engine.py tests/test_interpretation_proposal_api.py -q
python -m pytest -q --tb=short
python -m ruff format --check .
python -m ruff check .
```

The next separate integration step is a review UI using the current frontend
components after reviewers inspect proposal coverage and unresolved cases.
