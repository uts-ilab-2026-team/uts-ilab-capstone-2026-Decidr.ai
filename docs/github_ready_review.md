# GitHub-ready review

Review date: 6 September 2026

## Methodology preserved

The repository keeps the methodology supplied in the source archive. The SQLite relational
evidence ledger remains authoritative. Claims are assessed through human applicability and
credibility review followed by deterministic, traceable rules. The NetworkX graph remains a
bounded inspection aid and does not decide outcomes. Experimental semantic, hybrid, graph and
assistant components cannot modify frozen claims or human reference assessments.

## Corrections made

- Corpus-dependent tests now skip with a clear reason when private releases or generated
  ingestion registers are absent.
- Environment paths are resolved from the repository root, so commands behave consistently when
  launched from another directory.
- Every Streamlit page checks that the evidence ledger exists and has the core schema before
  querying it.
- The Approach B page reconstructs the corpus fingerprint from the ledger instead of assuming a
  generated Markdown report exists.
- Ruff checks now include application pages and tests, not only the core package.
- Make targets use the locked `uv` environment consistently.
- GitHub Actions runs formatting, linting and tests on pull requests and pushes to `main`.
- Additional secret-file patterns are ignored.
- Package import no longer triggers configuration logging; the package exposes its version
  without loading machine-specific paths.

## Known limitations retained honestly

- Raw client releases and generated ingestion/evaluation outputs are not included.
- Real-corpus assertions cannot run without the configured releases.
- Semantic retrieval requires an optional locally available model.
- No research-performance claim is justified until independent reviews and adjudicated
  references exist.
- The narrow experimental query parser is not a general natural-language understanding system.
