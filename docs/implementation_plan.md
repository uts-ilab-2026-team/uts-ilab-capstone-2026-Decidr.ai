> **Status: archived instructions / research history.** Archived initial implementation plan. Its status and environment statements describe the original checkpoint.
> Use [current employee guidance](claim_first.md), [architecture](architecture.md) and the
> [documentation inventory](documentation_inventory.md). The original body below is retained.

# Implementation plan

## Phase A — discovery and design

1. Audit repository and both releases. **Complete.**
2. Establish validated domain schemas and the versioned SQLite ledger. **In progress.**
3. Record architecture, risks, decisions, and methodology traceability. **In progress.**

## Phase B — common foundation

Implement release-aware registration, Markdown/CSV extraction, stable locators, metadata
provenance, exact and cautious near-duplicate detection, version relationships, exports,
and audit events. Verify idempotency against the actual corpus without changing it.

## Phase C — baseline

Implement FTS5 lexical retrieval and match explanations, independent blind review,
adjudication, deterministic applicability/credibility/outcome rules, cited explanations,
and the minimum Streamlit workflow.

## Phase D — experiments

Add cached local semantic retrieval with explicit availability status, reciprocal-rank
hybrid retrieval, graph-derived dependence/provenance features, and only justified
alternative reasoning or bounded wording assistance.

## Phase E — evaluation

Protect held-out claims, evaluate pooled retrieval only after adjudication, compare
reviewers/outcomes, run challenge and sensitivity tests, and produce per-claim error
analysis. Never generate performance claims from fixtures.

## Phase F — finalisation

Finish all pages/exports/docs, run lint/tests/application smoke test from a clean `uv`
environment, and produce reports only from genuine annotations.

## Principal risks

- No adjudicated reviews: blocks inferential evaluation, not application construction.
- Small purposive claim set: limits generalisation and aggregate metrics.
- Cross-release copies: can inflate evidence unless grouped by checksum/provenance.
- Metadata inferred from filenames/content: must be labelled as inferred.
- Local model availability: semantic retrieval must not make the core depend on downloads.
- Scope/time mismatch: semantically close evidence can still be inapplicable.
- The current directory lacks Git metadata: code-version capture must allow `unknown`.
