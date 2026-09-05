# Approach B experimental configuration

Approach B is an experimental configuration in the same application and ledger as Approach A.
It does not alter frozen claims, human references, or evidence identifiers.

| Layer | Approach A | Approach B |
|---|---|---|
| Interface | Structured Streamlit forms | Conversational Streamlit page with confirmation |
| Claim parsing | Frozen/manual claims | Conservative local parser; ambiguous fields require clarification |
| Retrieval | SQLite FTS5/BM25 | FTS5 plus optional local bi-encoder, RRF and optional local cross-encoder |
| Graph | Claim-centred reviewed graph | Shared ledger graph plus bounded depth-1 explicit-provenance expansion |
| Relationships | Human validated | Human validated when available; otherwise labelled model suggestions only |
| Outcome | Deterministic rules | Same deterministic rules; suggestions cannot override them |
| Explanation | Structured deterministic | Grounded conversational form with strict citation-package validation |
| Output | Shared `AssessmentResult` adapter | Shared `AssessmentResult` directly |

## Commands

```bash
uv run python -m decidr.dataset
uv run pytest
uv run streamlit run app/Home.py
```

Optional local semantic models:

```bash
uv sync --extra semantic
```

The core pipeline works without an LLM and without semantic model files: constrained parsing,
FTS5 retrieval, RRF fallback, explicit-metadata graph expansion, local heuristic suggestions,
deterministic outcomes, structured explanations and citation validation remain available.

Sentence-transformer retrieval and cross-encoder reranking require the optional dependency and
models already cached locally. No automatic download occurs. No external LLM integration is
enabled in version `0.1-experimental`; the interfaces and separate research-only result boundary
are present, but any future provider must record model/version and cannot write reference tables.

## Known limitations

- The constrained parser currently handles common discount rule/practice questions and deliberately
  asks for clarification outside that narrow grammar.
- Relationship suggestions are conservative lexical heuristics, not NLI judgements and never
  human validated by default.
- Graph expansion currently follows explicit source lineage and duplicate metadata at depth one;
  it does not infer unsupported edges.
- Citation validation verifies package membership, IDs, locators and outcome consistency. Direct
  quotation matching is enforced when quotations are introduced by a future generator; the current
  safe generator does not quote source text.
- Formal comparison remains blocked until both human reviews and development references exist.
  Held-out results will be reported descriptively because there are only two held-out claims.

## Manual evaluation sequence

1. Complete independent blinded reviews for all claims.
2. Compare/adjudicate development claims only.
3. Evaluate and refine both configurations on the development split.
4. Freeze the reasoning ruleset and record its checksum.
5. Explicitly unlock held-out access, adjudicate held-out references, and run one original held-out
   comparison without retrospective threshold changes.
