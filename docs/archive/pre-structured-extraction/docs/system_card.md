# Decidr prototype system card

## Intended use

Research and reviewer decision support for assessing evidential support for atomic,
scope-and-time-bounded organisational claims in the synthetic/anonymised Northfield corpus.

## Prohibited use

It must not make automated employment, disciplinary, legal, compliance, or personnel
decisions; rank employees; or be represented as establishing objective organisational truth.

## Components

The core is local and deterministic: read-only ingestion, SQLite ledger, FTS5 retrieval,
human applicability/credibility review, explicit rules, cited explanations, and audit/export.
Optional local embeddings recover paraphrases. A NetworkX graph supports provenance and
dependence inspection but never decides outcomes. No paid API or LLM is required.

## Data and evaluation

The corpus is synthetic/anonymised and the claim portfolio is purposive. Human adjudication
is a research judgement rather than unquestionable ground truth. Current research outcome
performance is unavailable because no two-reviewer adjudicated references exist. Synthetic
challenge passes are software behavior checks only.

## Principal risks and mitigations

- Context mismatch: reviewers explicitly assess target, scope, conditions, and period.
- Authority bias: source authority is a contextual dimension, never a universal hierarchy.
- Copy inflation: checksum groups count once; near copies are flagged for review.
- Stale evidence: superseded sources require period justification.
- Policy/practice collapse: formal and observed evidence remain separated in traces.
- False certainty: four-way outcome and confidence are separate; gaps lower confidence.
- Semantic false positives: embeddings cannot bypass applicability.
- Explanation hallucination: deterministic text renders structured evidence and rules only.

## Reproducibility

The ledger records checksums, dataset fingerprint, model identifiers, configurations,
reviewers, timestamps, splits, retrieval runs, rule traces, and audit events. Randomness is
not used by the deterministic baseline.

## Claim-first interface and review requirement

The employee flow accepts bounded declarative claims with exact original-wording provenance.
Unsupported interpretation and incomplete evidence review have explicit pending states and
receive no verdict. A named reviewer must verify meaning and every candidate relationship
before deterministic completion. Free-text extraction is limited; passing a schema is not
an assessment. Reviewed reusable claims require an explicit meaning review and exact wording
match. Experimental question interpretation is not promoted.

Knowledge-risk counts cover only application claims and completed reviews, and each flag
links to its claim and evidence. Unreviewed items are separate. Sensitivity is a temporary
replay of a completed snapshot, with no percentages or baseline mutation. New application
reviews are not formal evaluation references. See [claim_first.md](claim_first.md) for the
complete source, time, credibility and evaluation boundaries.
