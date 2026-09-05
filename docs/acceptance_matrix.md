# Acceptance and completion matrix

Date: 2026-09-03

| Acceptance criterion | Status | Evidence |
|---|---|---|
| Application starts | Pass | Streamlit headless startup smoke test |
| Supplied corpus ingests reproducibly | Pass | 68 sources, 980 units, stable SHA-256 dataset fingerprint |
| Sources and exclusions registered | Pass | 65 ingested, 3 documented exclusions, zero warnings |
| Claims can be created and reviewed | Pass | Claims, Human Review, and persistence tests |
| Lexical retrieval works | Pass | FTS5/BM25, match reasons, actual-corpus smoke retrieval |
| Semantic and hybrid work or are explicitly unavailable | Pass with environment limitation | Implemented/cache-tested with local fake embedder; actual model unavailable and clearly reported |
| Every evidence item has a locator | Pass | ingestion validation and real-corpus test |
| Independent reviewers remain separate | Pass | reviewer-keyed persistence and comparison tests |
| Four outcomes use explicit rules | Pass | all outcome-path tests and ordered rule traces |
| Confidence remains separate | Pass | separate enum, storage, UI, and explanation |
| Copies do not increase corroboration | Pass | checksum groups, dependence rule, CH-01 |
| Time and supersession are operational | Pass | lifecycle links/filter and CH-03/CH-08 |
| Missing evidence is a gap | Pass | missingness rule and CH-06 |
| Policy and practice remain distinguishable | Pass | evidence mode, divergence trace, CH-05/CH-09 |
| Claim explanation shows evidence and rules | Pass | deterministic renderer and citation test |
| Held-out cases are represented and protected from stated tuning workflow | Pass with procedural control | validated split and documented restriction; no tuning dataset exists yet |
| Evaluation and challenges run | Pass with data limitation | guarded evaluation; 10/10 synthetic behavior checks; no research metric without references |
| Exports work | Pass | 12 CSV/JSON registers plus available Markdown claim reports |
| Automated tests pass | Pass | 39 tests at audit time |
| Setup and usage verified | Pass | isolated locked environment: 39 tests passed; ingestion, evaluation, exports, compile, and app smoke test |

## Requirements awaiting genuine external input

- Research performance metrics require complete adjudicated evidence pools and final
  two-reviewer references. Current count is zero; metrics are correctly withheld.
- Actual semantic/hybrid corpus comparison requires an installed, locally cached embedding
  model. No recommendation of semantic benefit is currently justified.
- Reviewer-effort and maintenance-cost observations require real study sessions.
- Git commit capture remains `unknown:not-a-git-worktree` in this extracted directory.

These are not filled with fixtures. Synthetic fixtures are used only for automated software
behavior checks and are clearly separated from research results.
