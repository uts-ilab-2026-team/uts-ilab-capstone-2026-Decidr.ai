# Approach A baseline-readiness audit

Approach A remains the relational lexical baseline. No application fork or database fork was
created. It shares portfolio `1.2-final`, corpus fingerprint
`22f34686f926a8364f2d31f66601cbba9198c4927762d5ed167974e012b35478`, evidence IDs, ledger,
human references, and evaluation framework with Approach B.

| Requirement | Status |
|---|---|
| Stable claim/source/evidence/relationship schemas | Ready; strict Pydantic models reject extras |
| Versioned approved portfolio | Ready; immutable 1.1-final and active 1.2-final histories |
| Test/formal record separation | Ready; `test:` namespace excluded from formal evaluation |
| Relationship provenance | Ready; reviewer, method, created/modified timestamps retained |
| Deterministic rule trace | Ready; ordered rule IDs and affected evidence persisted |
| Retrieval trace | Ready; method, ranks, component scores, model metadata and latency persisted |
| Common response schema | Ready; `AssessmentResult` adapter added |
| Held-out sealing | Ready; comparison/adjudication/evaluation gates remain closed |
| TEST MODE and reset | Ready; visible indicators and namespace-limited reset operation |

Test records must use reviewer identifiers beginning `test:`. The reset deletes only that namespace
and cannot remove genuine study assessments.
