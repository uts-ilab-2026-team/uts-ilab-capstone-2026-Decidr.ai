> **Status: archived instructions / research history.** Legacy Research/admin experiment only. This is not the current employee assessment architecture.
> Use [current employee guidance](claim_first.md), [architecture](architecture.md) and the
> [documentation inventory](documentation_inventory.md). The original body below is retained.

# Approach B — employee knowledge assistant

## Business purpose

Approach B helps an employee resolve a question about an organisational policy, process,
observed practice, or specific event using only the supplied evidence corpus. It is decision
support, not a policy-making, employment, legal, or disciplinary system. Missing knowledge is
reported as a gap and is never invented.

## Architecture and responsibility boundaries

The SQLite evidence ledger remains the source of truth. The employee question passes through:

1. A deterministic interpreter normalises common spelling errors, detects domain terms, roles,
   actions, thresholds and dates, and ranks candidates using frozen-portfolio and corpus
   terminology. Material ambiguity produces a focused clarification question.
2. The employee selects, edits, and explicitly confirms one atomic claim. No assessment runs
   before confirmation, and conversation state stays in Streamlit session state.
3. FTS5/BM25 lexical retrieval always runs. A sentence-transformer encoder runs only when
   `semantic_enabled` is explicitly true and its model is already cached locally. Reciprocal-rank
   fusion records both component ranks. The optional local cross-encoder has the same explicit,
   no-download boundary.
4. A bounded depth-one graph expansion follows only explicit lineage, derivation, duplicate and
   supersession metadata. It supplies provenance and extra evidence; it does not decide
   credibility. Duplicate/dependent sources are counted once.
5. Conservative deterministic mapping creates applicability, relationship, evidence-mode and
   credibility records. The existing deterministic reasoner applies temporal, dependence,
   policy–practice, materiality and four-way verdict rules.
6. The employee response is rendered only from validated `AssessmentResult` data. It contains the
   answer, grouped cited evidence and reasoning, gaps, and a verdict-specific next action.

An optional LLM adapter is reserved for suggesting interpretations and rewriting a limited,
structured result into readable prose. It may receive only retrieved evidence and necessary
metadata. It cannot see the whole corpus, determine confidence, change the verdict, write review
records, or override the rule trace. Version 0.2 does not configure an external LLM; the UI states
that the deterministic fallback was used.

## Employee workflow

The employee asks a question or selects an example, answers focused clarification, reviews the
readable and structured interpretation, then confirms or edits it. The result has three primary
sections: Answer, Evidence and reasoning, and Recommended next action. Graph/provenance, component
availability, latency and rules are available only in advanced expanders.

## Difference from Approach A

| Layer | Approach A | Approach B |
|---|---|---|
| Primary user | Research reviewer | Employee seeking safe guidance |
| Input | Manually structured portfolio claim | Conversational question plus confirmation |
| Retrieval | SQLite lexical baseline | Lexical, optional local semantic, fusion/reranking, graph expansion |
| Relationships | Human-reviewed research records | Conservative deterministic query-time mapping, clearly labelled |
| Verdict | Deterministic reasoner | The same deterministic reasoner |
| Persistence | Review and assessment workflow | Chat session only; no review/evaluation-table writes |

Approach B does not alter Approach A, frozen portfolio files, freeze manifests, formal evaluation
tables, human adjudications, reviewer packets, expected outcomes, or held-out allocations.

## Safety boundaries and limitations

- Source authority is contextual rather than universal truth.
- Policy–practice divergence remains visible; observed violations do not automatically contradict
  a prescribed rule.
- Superseded material is excluded unless the confirmed period justifies it.
- Exact duplicates and derived sources are not independent corroboration.
- Novel processes may require the employee to edit the interpretation or ask the responsible owner.
- Textual relationship mapping is not human adjudication. Low-overlap evidence stays contextual;
  absent decisive evidence produces `Insufficient evidence`.
- Optional models are local-only and disabled by default. Nothing is downloaded or called silently.

## Run and test

```bash
uv run python -m decidr.dataset
uv run ruff check .
uv run pytest -q
uv run streamlit run app/Home.py
```

Open **Employee knowledge assistant** in the Streamlit navigation. To opt into semantic retrieval,
install the optional dependency/model yourself, ensure the model is cached locally, and set
`semantic_enabled` to `true` in `configs/approach_b_graph_llm.yaml`. Unavailability is reported
explicitly and lexical retrieval continues.

### Client-demo evidence refinement

Approach B now gates retrieved evidence before assigning a relationship. Its local
eligibility adapter records source status, target, process, organisation/business
scope, conditions, percentage boundaries, deal outcome and dates. Superseded rules
require a confirmed historical interval contained within the rule period; an
explicit successor's effective date can establish the predecessor's end date.
Current questions use the current date for policy applicability. Retrieval remains
bounded (100 fused candidates plus depth-one explicit provenance links), so absence
from retrieval is not proof of absence from the corpus.

Eligible evidence is ordered by directness, time, lifecycle, authority and
independence before retrieval relevance. Equivalent dependent copies prefer the
configured `preferred_corpus_release` (phase2), with stable identifiers for ties.
Excluded copies remain in provenance and cannot appear in support or citations.

The reasoner accepts an explicit practice-violation flag, defaulting to false so
existing Approach A inputs retain their behaviour. This enables qualifying practice
evidence to trigger divergence without entering formal-rule contradiction or
support. Explicit outside-CRM recording is evidence of a recording deviation;
blank or “None found” approval fields are coverage limitations, not proof that
approval never occurred. CRM lacks a consistent deal-type field: absent explicit
renewal context, scope is inferred and this limitation is disclosed. This inference
requires human confirmation for consequential use; records do not establish
population-level compliance rates.

Supported approval-rule answers are assembled from extracted source propositions,
approver, timing and recording fields. Unsupported language stays conservative;
the parser is a bounded deterministic adapter, not general natural-language
entailment. The initial evidence list has at most three items. Additional eligible
evidence, exclusions, source metadata, graph links, traces, component status,
latency, fingerprint and configuration are collapsed. CRM cards use selected fields;
document excerpts end at word boundaries. No formal evaluation is needed or invoked
by these checks, and employee conversations remain session-only.


### Release-purpose correction

The active corpus is now **Phase 2 only**. Phase 1 is archived framework-development
material and is excluded before ingestion, retrieval, graph expansion and employee
assessment. The earlier cross-release duplicate policy above is historical: only
within-Phase-2 dependencies can now corroborate or qualify modelling claims.
`decidr.corpus.RELEASE_PURPOSES` defines this distinction, and both approach profiles
declare the active release. See `docs/corpus_scope_change.md` for rebuild and frozen
portfolio implications. No frozen portfolio or study configuration was amended.
