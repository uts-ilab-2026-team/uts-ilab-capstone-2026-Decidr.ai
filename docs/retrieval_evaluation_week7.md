# Week 7 Retrieval Evaluation

## Purpose

This evaluation extends the initial CAND-01 retrieval smoke test by comparing lexical, semantic and hybrid retrieval on two additional claim types: CAND-03 and CAND-08.

The aim was not to calculate formal precision or recall, as a complete adjudicated relevance set is not yet available. Instead, the top 10 results were reviewed qualitatively for evidence relevance, evidence type, duplication and potential applicability issues.

## Claims tested

- CAND-01 — Discount approval requirement
- CAND-03 — Customer onboarding and implementation
- CAND-08 — Billing / engineering operational evidence

## CAND-03

### Lexical

Lexical retrieval strongly prioritised exact policy, process and interview terminology. The top results included POL-03, PROC-01 and INT-06.

A major issue was duplication between Phase 1 and Phase 2 versions of the same source and locator. Several positions in the top 10 therefore represented repeated evidence rather than independent evidence.

### Semantic

Semantic retrieval also ranked POL-03 highly but promoted INT-06 interview evidence and the "Required approvals" section of PROC-01.

This suggests semantic retrieval is useful where organisational evidence is expressed conversationally or with wording different from the claim. Some broader policy/context sections were also retrieved, showing that semantic similarity can widen the candidate set beyond directly matching evidence.

### Hybrid

Hybrid retrieval retained the main policy evidence while also including interview and process evidence.

The result set contained a useful mix of:
- formal policy,
- process documentation,
- interview evidence,
- responsibility/accountability information, and
- required approvals.

This was the most balanced result set for CAND-03.

## CAND-08

### Lexical

Lexical retrieval performed particularly well for operational evidence. The top results included:

- system audit records,
- billing incident review material,
- project/task records, and
- engineering role descriptions.

This indicates that lexical retrieval is effective where structured records contain distinctive event, role or process terminology.

### Semantic

Semantic retrieval placed greater emphasis on role descriptions, approval responsibilities and related organisational processes.

It still recovered key audit and incident evidence, but broadened the result set toward contextual evidence such as engineering responsibilities and process approvals.

### Hybrid

Hybrid retrieval combined the strongest characteristics of both approaches. Its top results included:

- the high-ranking system audit record,
- the billing incident review,
- project task evidence,
- engineering role information,
- additional audit records, and
- process approval evidence.

Across CAND-03 and CAND-08, hybrid retrieval provided the most balanced mixture of direct operational evidence and contextual organisational evidence.

## Phase-mirror duplication

Testing repeatedly showed that equivalent Phase 1 and Phase 2 copies of the same evidence could occupy multiple retrieval positions.

For example, the CAND-03 hybrid top 10 contained five repeated source/location pairs across corpus phases.

A retrieval UI improvement was implemented to detect these phase-mirror results. Repeated results are now labelled:

`⚠ phase mirror`

The interface also reports the number of repeated source/location results and warns reviewers that these records are retained for provenance but must not be treated as independent corroborating evidence.

The results are deliberately not deleted because the corpus phase remains relevant provenance information.

## Emerging findings

The three-claim review suggests:

1. Lexical retrieval is very fast and performs strongly where claims share exact terminology with policies, structured records, roles or identifiers.
2. Semantic retrieval adds value for paraphrased, conversational and contextual organisational evidence.
3. Hybrid retrieval generally provides the most balanced evidence set across formal, operational and conversational sources.
4. Textual relevance is not equivalent to credibility or applicability.
5. Superseded, duplicated or contextually inappropriate evidence must still be assessed downstream.
6. Phase-mirror evidence should not be counted as independent corroboration.

## Recommendation

Hybrid retrieval is currently the strongest candidate for the main evidence-discovery workflow because it combines exact lexical matching with semantic similarity.

However, retrieval should remain a candidate-generation stage only. Temporal validity, source status, evidence dependence, organisational scope and credibility should remain part of later assessment logic.

Further evaluation should test whether graph-based expansion adds useful evidence that hybrid text retrieval fails to recover.
