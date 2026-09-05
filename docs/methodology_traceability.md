# Methodology-to-implementation traceability

| Requirement | Planned component | Verification |
|---|---|---|
| Atomic scoped claims | `AtomicClaim`, `decidr.claims`, Claims UI | `test_models`, `test_claims` |
| Traceable evidence | source/evidence ledger and stable locators | locator/idempotency tests |
| Five evidence relationships | `ClaimEvidenceLink` | validation and review tests |
| Explicit credibility dimensions | `CredibilityAssessment` | bounds and persistence tests |
| Policy/practice distinction | `EvidenceMode`, separated reasoning | divergence challenge test |
| Copied/dependent evidence | checksums, groups, graph edges | duplicate/dependence tests |
| Versions and time | source lifecycle and applicability rules | supersession/time tests |
| Missingness is not contradiction | coverage/gap rule | missing-record challenge test |
| Four outcomes | deterministic reasoning engine | one test per outcome |
| Separate confidence | `ClaimAssessment.confidence` | schema/explanation tests |
| Reconstructable explanation | structured rule trace and citations | faithfulness checklist test |
| Comparable retrieval | `decidr.retrieval` over common evidence units | `test_retrieval` (semantic/hybrid pending) |
| Independent reviewers | reviewer-keyed ledger and Human Review UI | reviewer-isolation database test; adjudication pending |
| Held-out protection | immutable evaluation split during tuning | split guard tests |
| Auditable changes | append-only audit events | mutation audit tests |
| Reproducibility | run metadata and dataset fingerprint | clean rebuild test |
| Local semantic retrieval | `decidr.semantic`, SQLite embedding cache | fake-local embedder/cache test; real model availability reported separately |
| Hybrid retrieval | `decidr.hybrid` reciprocal-rank fusion | component-rank and deduplication test |
| Graph-enhanced provenance | `decidr.graph`, Evidence Graph page | bounded claim-graph test |
| Reviewer adjudication | `Adjudication`, comparison page | preserve/resolve validation tests |
| Guarded retrieval metrics | `decidr.evaluation.retrieval_metrics` | complete/incomplete pool tests |
| Outcome comparison | `outcome_metrics`, guarded evaluation CLI | confusion/disagreement and empty-reference tests |
| Ten challenge principles | `decidr.challenges` | all-ten behavioral test |
| Explanation traceability | `traceability_check` | missing-field reconstruction test |
| Per-claim error taxonomy | `EvaluationError`, Evaluation page | persistence test |

This is a living matrix. Each row must name its concrete module and test identifier as
implementation progresses; documentation alone is not completion evidence.
