# Retrieval Process Review

## Current retrieval flow

The current prototype supports three main retrieval methods:

1. Lexical retrieval using SQLite FTS5/BM25.
2. Semantic retrieval using Sentence Transformers and cosine similarity.
3. Hybrid retrieval using reciprocal-rank fusion to combine lexical and semantic results.

Retrieval uses the structured atomic claim as input and returns candidate evidence with source IDs and exact locators. Candidate evidence is then passed to later applicability and credibility assessment stages.

## Retrieval boundary

Retrieval should identify potentially relevant evidence but should not determine whether that evidence is credible or applicable.

For example, a superseded policy may still be relevant to a claim because it may explain historical practice or how outdated organisational knowledge developed. Its status should therefore remain available to the later reasoning stage rather than being removed during retrieval.

## Phase 2 retrieval tests

### Test 1 — Exact identifiers

Use a claim containing a known policy, process, deal or role reference.

Expected result: lexical retrieval should perform strongly because exact identifiers and terminology are present.

### Test 2 — Paraphrased evidence

Use a claim where an interview, meeting or communication expresses the same organisational rule using different wording.

Expected result: semantic retrieval should recover relevant evidence that lexical search may miss.

### Test 3 — Similar but inapplicable evidence

Use a claim where a semantically similar passage relates to a different time period, process or superseded rule.

Expected result: retrieval may return the passage, but the later applicability stage should identify that it does not directly apply to the claim.

## Proposed evaluation

Lexical, semantic and hybrid retrieval should be compared using:

- relevant evidence found;
- important evidence missed;
- irrelevant evidence returned;
- Recall@k where a reviewed evidence set is available.

The aim is to determine whether semantic or hybrid retrieval provides enough improvement over the lexical baseline to justify the additional complexity.

## Next step

Run lexical, semantic and hybrid retrieval against a small set of reviewed Phase 2 claims and document the main retrieval failure modes. Graph-enhanced retrieval can then be tested where evidence appears to be discoverable through provenance or organisational relationships rather than textual similarity alone.
