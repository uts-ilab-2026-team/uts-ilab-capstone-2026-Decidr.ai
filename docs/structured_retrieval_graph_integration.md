# Structured retrieval and graph integration

## Purpose

The client corpus contains CRM deals, project tasks, and system audit events as CSV
records. Ingestion already preserved every original row, but did not populate the shared
`Evidence` context fields consumed by the ledger graph. This change maps explicit CSV
columns into those existing fields and exposes the same context in whole-corpus retrieval.

## Deterministic mappings

| Source type | Evidence mappings |
|---|---|
| Project tasks | `process_or_capability -> process`, `owner_name -> actor`, `owner_role -> role`, inferred `Project System -> system` |
| Audit events | `actor_name -> actor`, `actor_role -> role`, `system -> system` |
| CRM records | `ae_owner -> actor`, `approval_role -> role`, inferred `CRM -> system` |

The complete source row remains unchanged in `structured_metadata.record`. Each populated
field records a direct or inferred mapping in `structured_metadata.field_mapping`.

## Retrieval contract

`search_claim_corpus()` accepts the repository's validated `AtomicClaim`, uses its explicit
applicability dates, and returns the existing `CorpusSearchPackage`. Each result now carries
the row identifier, process, actor, role, and system where those values are available.

Retrieval still proposes candidate evidence only. It does not classify support or
contradiction, assign credibility, or determine an outcome.

## Study and data boundaries

- Raw client files remain external and read-only.
- Automated tests use synthetic rows rather than client records.
- The change does not alter the frozen candidate portfolio or study configuration.
- Sealed held-out claims are not used for tuning or performance claims.
- Formal retrieval metrics remain guarded until complete adjudicated evidence pools exist.
