# Whole-Corpus Retrieval Engine — Week 8

## Purpose

The retrieval engine retrieves relevant organisational evidence across the complete corpus for either free-text questions or downstream claim assessment.

It is intentionally separate from:
- credibility scoring and verdicts;
- evidence support/contradiction classification;
- knowledge-graph traversal;
- final answer generation and UI presentation.

Retrieval supplies evidence and metadata. Other components decide what that evidence means.

## Retrieval flow

1. Accept a free-text query.
2. Search the full evidence corpus using:
   - FTS5/BM25 lexical retrieval;
   - local sentence-transformer semantic retrieval.
3. Fuse rankings using Reciprocal Rank Fusion (RRF).
4. Group exact duplicate evidence while retaining all provenance.
5. Diversify results across provenance groups.
6. Detect explicit temporal scope in queries.
7. Apply modest temporal reranking without deleting out-of-period evidence.
8. Surface structured-data completeness and retrieval gap signals.
9. Return a serialisable evidence package.

## Main API

```python
from decidr.corpus_search import search_corpus

package = search_corpus(
    connection,
    "What Finance approval is required for discounts above 15%?",
)
```

`CorpusSearchPackage` contains:
- original query;
- ranked evidence results;
- candidate count;
- unique sources;
- distinct provenance groups;
- collapsed duplicate count;
- source-type distribution;
- semantic retrieval status;
- inferred query period;
- retrieval gap signals.

Each `CorpusResult` contains:
- evidence and source IDs;
- human-readable source title;
- locator and evidence text;
- lexical, semantic, hybrid and adjusted ranking information;
- source type and lifecycle;
- effective and creation dates;
- temporal applicability status;
- provenance group and retained duplicate provenance;
- explicit possible-duplicate references;
- missing structured fields.

## Duplicate policy

Exact duplicate source copies are grouped so they do not fill the result set or falsely appear as independent corroboration.

All source provenance is retained.

Semantically similar but independently sourced evidence is not collapsed.

Records explicitly described as possible duplicates, such as TASK-073 referring to TASK-072, are surfaced as possible-duplicate relationships rather than automatically merged.

## Temporal behaviour

Explicit query periods such as:
- `before 2025`
- `after 2025`
- `in 2026`
- `between 2024 and 2025`
- `as at 2025-03-01`

are parsed into a query period.

Evidence may be labelled:
- `applicable_to_query_period`
- `outside_query_period`
- `recorded_in_query_period`
- `recorded_outside_query_period`
- `temporal_scope_unknown`
- `historical_or_stale`
- `current_or_unspecified`

Temporal fit adjusts ranking modestly but does not replace semantic/lexical relevance or remove potentially useful conflicting evidence.

## Retrieval gap signals

Retrieval may expose signals such as:
- `no_evidence_retrieved`
- `semantic_retrieval_unavailable`
- `limited_provenance_diversity`
- `structured_fields_missing`
- `no_explicitly_applicable_dated_source`
- `some_temporal_scope_unknown`
- `temporal_evidence_gap`

These are retrieval diagnostics, not credibility verdicts.

## Structured-data behaviour

CSV evidence retains its original record.

Blank fields are returned through `missing_fields`.

Retrieval deliberately does not infer whether a missing value is problematic. For example, a blank approval field may be expected for a deal below the approval threshold. That interpretation belongs to the credibility/framework layer.

## Client challenge cases validated

The engine has been exercised against:
- current discount approval policy;
- historical 10% -> 15% discount-policy evolution;
- conflicting employee beliefs about discount thresholds;
- emergency billing deployment without a linked sign-off;
- missing CRM fields;
- duplicate phase copies;
- explicitly suspected duplicate task records.

Notable dataset cases include:
- DEAL-014 — 18% discount approved outside the formal CRM field;
- DEAL-027 — 20% discount with no approval record found;
- DEAL-035 — discount field recorded as 150 with contextual evidence suggesting a data-quality issue;
- DEAL-072 — incomplete discount, approval and close-date data;
- TASK-072 / TASK-073 — possible duplicate onboarding records.

## Integration boundary

The retrieval engine should feed:
- the credibility framework;
- graph-based evidence expansion;
- the UI;
- any later RAG answer-generation layer.

It should not itself output `Supported`, `Contradicted`, `Contested` or `Insufficient evidence`.

Those decisions require the separate credibility methodology.
