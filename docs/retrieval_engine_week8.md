# Whole-Corpus Retrieval Engine — Week 8

## Purpose

The retrieval engine retrieves relevant organisational evidence across the complete corpus from a free-text query. Structured claims can be converted to query text and passed through the same corpus-search layer.

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

## Implementation status

**Status:** feature-complete retrieval backend as at Week 8.

**Branch:** `feat/mo-retrieval-engine`

**Primary implementation:**
- `decidr/corpus_search.py` — whole-corpus retrieval orchestration;
- `decidr/retrieval.py` — lexical / BM25 retrieval;
- `decidr/semantic.py` — semantic retrieval and embedding cache;
- `decidr/hybrid.py` — Reciprocal Rank Fusion.

**Validation:**
- 89 automated tests passing;
- Ruff checks passing;
- client challenge cases exported to `reports/retrieval_engine_client_cases.json`.

## Quick start

~~~python
from decidr.config import DATABASE_PATH
from decidr.corpus_search import search_corpus
from decidr.database import connect

with connect(DATABASE_PATH) as connection:
    package = search_corpus(
        connection,
        "What Finance approval is required for discounts above 15%?",
        limit=10,
        candidate_limit=30,
        semantic=True,
        max_per_source=2,
    )

for result in package.results:
    print(result.rank, result.source_title, result.locator)
    print(result.text)
~~~

For transport to another component:

~~~python
from decidr.corpus_search import package_to_dict, package_to_json

payload = package_to_dict(package)
json_payload = package_to_json(package)
~~~

## Integration guidance

### Credibility / assessment framework

Use retrieved evidence together with:
- `source_type`;
- `lifecycle_status`;
- `approval_status`;
- effective and creation dates;
- `temporal_status`;
- `provenance_group`;
- `provenance_sources`;
- `missing_fields`;
- retrieval `gap_signals`.

The retrieval rank indicates relevance, not credibility.

`provenance_group` should not be interpreted as proof that different groups are epistemically independent. It primarily prevents known duplicate source copies from being counted repeatedly.

### Knowledge graph

The retrieval package can be used as the initial evidence set for graph expansion.

Graph traversal, relationship inference and loop/cycle control remain outside `search_corpus()` so graph reasoning does not silently alter the base retrieval result.

### UI

The UI can consume `package_to_dict()` or `package_to_json()`.

Useful fields to display include:
- source title and type;
- evidence text;
- source locator;
- provenance sources;
- lifecycle and temporal status;
- missing-field warnings;
- possible-duplicate references.

Both raw `hybrid_score` and adjusted `ranking_score` are exposed for transparency.

## Known limitations

- Temporal parsing handles simple explicit expressions such as years and ISO dates; it is not a general natural-language date parser.
- Creation date is not treated as equivalent to an effective date.
- Evidence without explicit effective dates may therefore have uncertain temporal applicability.
- Exact duplicate source copies are grouped; similar wording from different sources is retained rather than assumed dependent.
- Explicit possible-duplicate references are surfaced but are not automatically merged.
- `missing_fields` reports blank structured values but does not determine whether those blanks constitute a business-control failure.
- Retrieval gap signals describe retrieval coverage and data limitations; they are not credibility or truth judgements.
- Semantic retrieval depends on the local sentence-transformer model being available. Lexical retrieval remains available if semantic retrieval cannot run.

## Ownership boundary

The retrieval component is responsible for:

**Query -> relevant evidence + retrieval metadata**

It is not responsible for:

**Evidence -> credibility verdict / truth judgement**

This separation keeps retrieval relevance, graph relationships and credibility assessment auditable as distinct stages.

