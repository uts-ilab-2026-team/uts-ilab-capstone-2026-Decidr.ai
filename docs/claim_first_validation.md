# Claim-first implementation validation — 9 September 2026

## Repository checkpoint and integration diagnosis

- Branch: `feat/claim-first-assessment`.
- HEAD: `444bfe01ea423fb3b114047d2979fc6857a6e6cb` (unchanged).
- Checkpoint stash: `stash@{0}`, `pre-claim-first checkpoint before integrating 444bfe0`;
  it was already applied before this task and was not applied again or dropped.
- Restored checkpoint: 30 tracked changed paths and all 31 untracked checkpoint files
  were verified. HEAD's five baseline additions/changes were preserved.
- No repository or ancestor `AGENTS.md` was found. `CODING_STANDARDS.md` was read.
- No reset, clean, switch, commit, push, merge, history rewrite or staging operation was run.

The failing `test_baseline_uses_human_reviews_and_never_an_llm` was reproduced. Its source
ID was `S1`, while `lexical_search` filtered with `source_id LIKE 'phase2:%'`. Retrieval
therefore returned no evidence even though E1's human link and credibility assessment were
complete and its claim-level review gate was satisfied. The reasoner received an empty
list. This was established from fixture, retrieval, review-loader and reasoner code, not
assumed from the observed outcome.

The fixture was given explicit Phase 2 ingestion/release metadata and the expected outcome
remained Supported. Retrieval and completed-link assertions were added. This established
an integrated **270-pass baseline before the new workflow**. Subsequently, claim lexical
and semantic retrieval were routed through the metadata-based eligibility implementations;
older Approach B/corpus fixtures were given their missing release metadata without changing
semantic expectations. Eligibility now requires successful ingestion and consistent active
release metadata; a misleading ID prefix is insufficient.

## End-to-end verification

Final full suite: **321 passed**, with no skipped or failed tests, no Ollama requirement
and no external network requirement. This includes 51 new claim-first cases (parameterised
cases included), alongside the existing 270 tests.

The new Streamlit AppTest path submits an actual development claim, starts a review against
a real temporary SQLite/FTS ledger, fills applicability and credibility judgements, completes
the receipt, and verifies the resulting Supported verdict, Moderate confidence and E-S1
citation. It then changes a temporary sensitivity scenario and checks that the baseline
snapshot remains unchanged. The assessment service and reasoner are not mocked.

Other regressions cover:

- protected quantities, units, comparisons, dates, negation, scope and exclusions;
- compound completeness, lowercase second sentences and noun-list `and` handling;
- missing meaning, short clarification, manual fallback and unsupported input pending;
- novel topics without invented evidence or answers;
- Phase 1, failed, excluded, registered-only and conflicting-release sources;
- successful local semantic status and semantic failure isolation;
- proposed versus reviewed links and missing-review completion gates;
- transitive origins, intermediate graph nodes and conflict within a single origin;
- policy/practice separation, old-but-applicable sources, supersession at event dates,
  unknown temporal basis and evidence created after an as-of snapshot;
- noisy records, uncertain corrections and required corroborating references;
- gaps versus missing reviews; missing records not proving events never occurred;
- evidence-linked dashboard flags, coverage denominators and pending work;
- exact reviewed reuse, protected-value changes and ambiguity hidden by prior clarification;
- source inspection without claim creation, bounded graphs and no ineligible source nodes;
- source-grounded responsible roles, escaped complete export and long-excerpt retention;
- sensitivity through the same reasoner, immutable baseline records and snapshot replay;
- held-out items remaining outside employee register enumeration/reuse.

Checks run successfully:

```sh
.venv/bin/ruff check . app/Home.py app/employee.py tests/test_claim_first.py tests/test_claim_first_ui.py tests/test_approach_a.py
.venv/bin/pytest -q
git diff --check
git diff --cached --check
```

Ruff formatted the new implementation/UI/tests and touched shared Python modules. No
repository-wide formatting sweep was applied to unrelated restored work.

A local Streamlit server successfully started on `127.0.0.1:8503` using a disposable copy
of the corpus ledger. The browser plugin reported no available/connected browser, including
after its documented discovery check. AppTest verified interactions; a real browser visual
or print-pagination inspection could not be performed in this session. The HTML export's
complete long excerpt and final marker, escaping, and unrestricted print-flow CSS are
regression-tested. Visual pagination remains a presentation-machine review requirement.

## Corpus and generated outputs

The dataset command's rebuild/archive and export side effects were inspected before use.
Validation used:

```sh
.venv/bin/python -m decidr.dataset \
  --database /tmp/decidr-validation-ingestion.sqlite3 \
  --output /tmp/decidr-validation-ingestion
```

It generated only a temporary ledger and temporary ingestion register/report exports.
The UI check used `/tmp/decidr-claim-first-demo.sqlite3`; tests used pytest temporary
ledgers. No synthetic reviewer records were installed in the repository's real ledger.

The rebuilt corpus matched the existing ledger:

- Registered source records: **45** (registration count, not a claim that all are eligible).
- Extracted evidence units: **812**.
- Corpus fingerprint:
  `766ca57488795f6e0d7e587f1bb1db36356112b9938c9e53efbed34510ba116e`.
- Latest dated eligible source: **2026-07-20**, used as a visible, adjustable as-of convention.

A before/after SHA-256 inventory of **116 files under `framework/`, `reports/` and `data/`**
found no changed or missing file. This includes frozen research artifacts, historical
reports and the repository ledger. No prior workspace file was removed. The prior staged
changes remain staged; this task's edits are unstaged/new files. The colleague's Approach A
implementation and combined baseline configuration are preserved.

## Files changed specifically for this task

| Area | Files |
| --- | --- |
| Employee UI/navigation | `app/Home.py`, `app/employee.py` |
| New application services | `decidr/claim_intake.py`, `decidr/claim_workflow.py`, `decidr/claim_graph.py`, `decidr/claim_export.py` |
| Shared eligibility/retrieval/reasoning/graph fixes | `decidr/corpus.py`, `decidr/retrieval.py`, `decidr/semantic.py`, `decidr/reasoning.py`, `decidr/graph.py` |
| Integration/development fixtures | `tests/test_approach_a.py`, `tests/test_approach_b.py`, `tests/test_corpus_scope.py` |
| New regressions and AppTest workflows | `tests/test_claim_first.py`, `tests/test_claim_first_ui.py` |
| Startup, architecture, usage and handoff | `README.md`, `docs/architecture.md`, `docs/system_card.md`, `docs/claim_first.md`, `docs/claim_first_validation.md` |

Other modified/untracked files in `git status` belong to the restored checkpoint and have
been preserved. No frozen manifest, reference label or historical evaluation record was
modified. No formal held-out evaluation or Phase 3 ingestion was performed.

## Remaining limits and demo requirements

Language intake is deliberately bounded, and manual meaning/evidence review remains
necessary. No automatic relationship classifier is promoted. Unknown dependence and source
metadata incompleteness remain visible limitations. Risk counts describe reviewed claim
coverage, not operational breach rates. Local reviewer names are not authentication.
Browser pagination must still be checked on the presentation machine. Passing these tests
does not establish universal claim understanding, empirical accuracy or production readiness.

Launch and the verified source-grounded client demo are documented in
[claim_first.md](claim_first.md). Prepare the genuine human review before demonstrating a
completed real-corpus verdict; no pretend human review was created to populate the dashboard.
