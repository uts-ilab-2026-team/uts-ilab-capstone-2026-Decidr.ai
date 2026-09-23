# Architecture

The proof-of-concept uses one common evidence pipeline so experimental components remain
comparable.

`read-only corpus -> registration/extraction -> SQLite evidence ledger -> retrieval ->
human applicability and credibility review -> deterministic rules -> explanation/export`

The relational ledger is authoritative for provenance and decisions. A NetworkX graph is
a derived view for dependency, version, and claim-centred inspection; it never determines
an outcome. Lexical, semantic, and hybrid retrieval consume the same claim and evidence
units. Human review records remain separate by reviewer until adjudication. Automated
outcomes remain separate from reviewed references.

## Boundaries

- Domain models validate source, evidence, claim, link, credibility, and outcome records.
- Ingestion owns checksums, locators, extraction provenance, versions, duplicates, and
  failures; it never mutates raw inputs.
- Retrieval proposes candidates and explains matches; it cannot bypass applicability.
- Reasoning filters applicability, adjusts dependence/version effects, separates formal
  rules from observed practice, records gaps, chooses one of four outcomes, and emits an
  ordered rule trace.
- Explanation renders only structured records and citations.
- Evaluation uses adjudicated references when available and otherwise reports descriptive
  counts with an explicit limitation.
- Streamlit is a thin interaction layer over tested services.

SQLite JSON payloads preserve the complete validated record while indexed columns enforce
identity, uniqueness, splits, relationships, and outcomes. Schema migrations are explicit
and idempotent. Configurations, dataset fingerprints, model versions, rule versions, and
code versions are captured with runs.

## Claim-first employee workflow

The default Streamlit entry point now uses `claim_intake.py` and `claim_workflow.py`.
`employee_claims` stores exact wording and intake/review state alongside the existing
claim register. `employee_review_runs` stores bounded retrieval packets, source-graph and
corpus snapshots, completion receipts and immutable results. `employee_review_notes`
retains additional applicability, provenance, gap, settlement and risk judgements. Human
links and credibility values still use the shared review ledger.

Employee search uses metadata-based Phase 2 eligibility, FTS5, optional local semantic
ranking and bounded rank fusion. Source graph expansion cannot create evidence relationships.
`claim_graph.py` supports independent source exploration and snapshot-based review graphs;
proposed and reviewed links remain distinct. `claim_export.py` provides the complete escaped
HTML report. The shared deterministic reasoner is used for both baseline and sensitivity.

Application assessment records do not populate formal research judgements. The employee
register does not enumerate study or held-out claims. Archived question interpretation and
scenario-specific Approach B relationship code are disconnected from the employee flow.
See [the claim-first contract](claim_first.md) for supported patterns, review gates,
client priorities, implementation choices and known limitations.
