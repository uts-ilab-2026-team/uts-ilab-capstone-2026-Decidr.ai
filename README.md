# uts-ilab-capstone-2026-Decidr.ai

Project delivery, technical development and assessment evidence for UTS Innovation Lab Capstone Project - Spring 2026.

## Repository layout

    data/          Datasets - not in git, create locally (see below)
    decidr/        Python source code
    docs/          Documentation, decision records, meeting notes
    framework/     Claim definition, credibility criteria, assessment methodology
    notebooks/     Jupyter notebooks for exploration
    references/    Assignment brief, rubric, background reading
    reports/       Written deliverables
    tests/         Test suite

## Setup

Requires [uv](https://docs.astral.sh/uv/).

    # install uv (once)
    curl -LsSf https://astral.sh/uv/install.sh | sh

    # set up the project
    git clone git@github.com:uts-ilab-2026-team/uts-ilab-capstone-2026-Decidr.ai.git
    cd uts-ilab-capstone-2026-Decidr.ai
    uv sync

## Data

Datasets are not committed to this repository. Create the folder locally and add the
release files yourself:

    mkdir -p data/raw data/interim data/processed

Ask the team for the current phase release.

The ingestion pipeline reads releases in place; it does not copy or modify raw evidence.
By default it looks for the two release directories under
`../Decidr Capstone Project/04 Data/01 Raw`. Copy `.env.example` to `.env` and override
the paths when your local layout differs.

## Ingestion

Build or refresh the evidence ledger and export the source/evidence registers:

    uv run python -m decidr.dataset

Default outputs are:

- `data/processed/evidence.sqlite3` — local SQLite evidence ledger;
- `reports/ingestion/source_register.csv` and `.json`;
- `reports/ingestion/evidence_register.json`;
- `reports/ingestion/ingestion_report.md`.

The command is idempotent. Every file is registered with a SHA-256 checksum; Markdown
blocks use heading-and-block locators and CSV records retain their row number and source
identifier. Release documentation and the illustrative labelled-claim sample are
registered but excluded from organisational evidence.

Exact copies receive a shared checksum group. Highly similar non-identical documents are
only flagged as review candidates and are not automatically treated as dependent.

## Quality checks

    uv run ruff format --check .
    uv run ruff check .
    uv run pytest

The real-corpus smoke test skips automatically when the external releases are unavailable.

## Baseline application

Start the local interface after ingestion:

    uv run streamlit run app/Home.py

The baseline workflow is deliberately reviewer-led:

1. Create a structured claim and inspect its atomicity warning.
2. Run FTS5/BM25 lexical retrieval and inspect the terms responsible for every match.
3. Enter evidence applicability, relationship, credibility dimensions, and a blind
   claim-level judgement under a reviewer identifier.
4. Open Claim Assessment only after completing the blind review, run the deterministic
   rules, and download the cited Markdown explanation.

Different reviewer identifiers retain separate records. The application warns that the
reference remains incomplete until at least two independent reviewers finish; it never
creates a second reviewer automatically.

## Experimental retrieval and graph

Lexical retrieval works in the core installation. Semantic retrieval is optional and is
disabled unless both the package and model already exist locally:

    uv sync --extra semantic

The application never downloads an embedding model silently. The default model identifier
is `sentence-transformers/all-MiniLM-L6-v2`; embeddings are cached in SQLite with the model
name, package version, content checksum, and creation time. Hybrid retrieval combines the
lexical and semantic rankings using reciprocal-rank fusion with `k=60`, retaining both
component ranks.

The Evidence Graph page derives a bounded graph for one selected claim. It shows reviewed
claim-evidence relationships, source provenance, exact duplicate groups, and version links.
The graph is an inspection aid and never determines the assessment outcome.

Once two humans complete a blind review, Reviewer Comparison shows their evidence-level and
claim-level differences. An adjudicator can resolve them or explicitly preserve genuine
disagreement; the application does not infer consensus.

## Evaluation

Run the guarded evaluation and synthetic behavioral challenges with:

    uv run python -m decidr.evaluate

Outputs are written under `reports/evaluation/`. Outcome agreement is calculated only for
claims having both a resolved two-reviewer adjudication and an automated assessment.
Precision, recall, and F1 are available only when the adjudicated evidence pool is marked
complete. Otherwise the system reports descriptive found/irrelevant/missed counts and the
reason metrics were withheld.

The ten challenge cases use synthetic fixtures isolated from the Northfield corpus. Their
pass/fail results establish software behavior only and must not be reported as model or
research performance. The Evaluation page also supports per-claim qualitative errors using
the documented taxonomy and shows component comparisons with unobserved benefits left blank.

## Complete exports

Export all relational registers, retrieval runs/results, reviews, adjudications, automated
assessments, rule traces, errors, audit events, and available claim reports:

    uv run python -m decidr.exports

Generated data and reports are ignored by Git. Do not commit derived evidence without the
same client-data approval required for raw evidence.

## Documentation

- `docs/repository_data_audit.md` — corpus and repository audit
- `docs/architecture.md` — component boundaries and data flow
- `docs/data_dictionary.md` — field meanings
- `docs/methodology_traceability.md` — requirement-to-code/test mapping
- `docs/four_outcomes.md` — outcome semantics
- `docs/system_card.md` — intended use, risks, and evaluation status
- `docs/ethical_considerations.md` — limitations and prohibited use
- `docs/guides/` — adding claims and retrieval methods
- `docs/decisions/` — implementation decisions

## Troubleshooting

- **No ledger:** run `uv run python -m decidr.dataset`.
- **Missing release:** set `DECIDR_PHASE1_DATA_DIR` and `DECIDR_PHASE2_DATA_DIR` in `.env`.
- **Semantic unavailable:** install the optional extra and make the configured model available
  locally; lexical retrieval remains supported.
- **No evaluation score:** complete two independent human reviews, adjudicate them, and run an
  automated assessment for the same claim. An absent score is expected before that point.
- **Git status unavailable:** this extracted directory was not a Git working tree during the
  initial audit; code-version recording therefore remains `unknown` until used in a checkout.

## Human-study preparation

Use the **Human Study Setup** page after the team has selected genuine claims. It checks for
six-to-ten included claims, at least two held-out cases, at least one development case, and
completed atomicity review. It does not select claims automatically.

Enter two distinct real reviewer identifiers to generate separate blind JSON packets under
`reports/study_materials/`. Packets contain claim definitions and review instructions only;
they exclude automated outcomes and the other reviewer's judgements. Reviewers then work in
the Human Review page, followed by Reviewer Comparison and Adjudication.

## Team

iLab 14-02 Project Group

- Apaar Agarwal
- Isanka Rashmitha Dissanayake Dissanayake Mudiyanselage
- Mohanned Habib
- Royston Camilo Reis
- Raymond Halim
- Saif Muzaffar Parkar
