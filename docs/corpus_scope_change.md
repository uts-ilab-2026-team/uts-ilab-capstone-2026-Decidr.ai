# Phase 2 modelling corpus correction

Phase 1 (`phase1_framework_development`) is framework-development-only. Its 23
configured raw files remain on disk unchanged. Phase 2 (`phase2_model_development`)
is the active modelling corpus. This is enforced by `decidr.corpus.RELEASE_PURPOSES`,
the ingestion boundary and Phase 2-only lexical, semantic and graph queries.
Employee assessment filters expanded evidence again; the deterministic reasoner
also rejects Phase 1 reviewed evidence before applicability or confidence rules.
Both Approach A and Approach B therefore use the same modelling release.

## Generated artefacts

Rebuilt through `uv run python -m decidr.dataset`, without editing generated records:

- Active ledger: `data/processed/evidence.sqlite3`.
- FTS5 index: rebuilt inside that ledger, 812 evidence units.
- Semantic cache: invalidated with the replaced ledger; empty until the optional
  locally available model is used. No embedding model was downloaded.
- Source/evidence registers and ingestion report: regenerated in `reports/ingestion/`.
- Graphs: derived on demand from the new ledger; cross-release provenance links
  cannot introduce Phase 1 nodes.
- Previous ledger: preserved using SQLite backup under `data/processed/archive/`.
  Historical review and assessment records are not carried into the new corpus.
  Re-registering an unchanged active corpus preserves its existing reviews.

The active register contains **45 Phase 2 sources**, including one excluded README:
**44 ingested sources and 812 evidence units**. Archived Phase 1 inventory appears
separately in the report and does not contribute to these counts or the fingerprint.

Previous combined-corpus fingerprint:
`22f34686f926a8364f2d31f66601cbba9198c4927762d5ed167974e012b35478`

Active Phase 2 fingerprint:
`766ca57488795f6e0d7e587f1bb1db36356112b9938c9e53efbed34510ba116e`

Ingestion configuration: `ingestion-v2-phase2-only`.

## Frozen dependency audit

Both existing manifests explicitly bind to the previous combined fingerprint and
`ingestion-v1`:

- `framework/portfolio_freeze_manifest_v1.1-final.json`
- `framework/portfolio_freeze_manifest_v1.2-final.json`

Their corresponding versioned study configurations are checksum-bound by the
manifests. `configs/human_study.json` still selects `1.2-final`. Neither the active
nor the versioned study configurations directly embeds a corpus fingerprint; the
dependency is through the selected manifest. These files and all frozen portfolio
files remain unchanged. Their existing historical checksums remain valid, but
**their authority for formal evaluation against the active corpus is invalidated**.
Comparison readiness and the evaluation entry point fail closed on this mismatch,
even if unrelated authorisation flags are enabled. Evaluation remains unrun.

A controlled new version, proposed **v1.3-final**, is required before formal evaluation:

1. Review the portfolio's applicability, evidence pools and coverage against Phase 2
   only, preserving the sealed split and avoiding held-out outcome inspection.
2. Explicitly approve any carried-forward or amended claim definitions, quantitative
   eligibility and operational definitions. Do not mutate either existing freeze.
3. Create a new versioned portfolio, design and study configuration with fresh hashes,
   approval provenance, the new fingerprint and `ingestion-v2-phase2-only`.
4. Explicitly select that version in the active study configuration after approval.
   Re-establish independent reviews/adjudication and ruleset freeze for the new corpus
   before any separately authorised formal evaluation or held-out access.

No new freeze, reviewer packet, reference outcome or formal evaluation was generated
as part of this correction.
