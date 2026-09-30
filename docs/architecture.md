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
