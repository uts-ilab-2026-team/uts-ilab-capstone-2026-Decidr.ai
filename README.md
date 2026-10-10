# Decidr.ai Employee Knowledge Assistant

UTS Innovation Lab Capstone Project — Spring 2026.

This repository contains the team's research, prototype code and assessment material for
evaluating organisational claims against documented rules and observed practice. The current
prototype uses a provenance-aware organisational graph and produces a credibility assessment
and a facts register from the same evidence model.

## Prototype overview

The graph contains seven node types:

- **Person, Role, Function, Process and System** form the organisational backbone.
- **Document** nodes represent evidence sources and retain their type, approval status and
  effective period.
- **Fact** nodes represent searchable topics. The asserted value is stored on a `FORMAL` or
  `OBSERVED` relationship rather than inside the Fact node.

The prototype now supports both the original prebuilt graph flow and an exact-claim corpus flow:

```text
Exact claim
  -> Saif FTS5/BM25 retrieval and optional local semantic RRF
  -> temporal, duplicate, section-grouping and explicit-record-ID handling
  -> unresolved evidence packet with exact passages and provenance
  -> numeric threshold comparison as a diagnostic only
  -> explicitly judged formal and observed evidence relationships
  -> source, status, date and materiality checks
  -> provisional framework assessment
  -> two independent reviews or adjudication
  -> final facts-register finding
```

The prototype applies deterministic rules. It considers source authority, approval status,
version and recency, directness, specificity, corroboration, independence and completeness.
Missing evidence is recorded as a gap and is not automatically treated as contradictory
evidence. Formal rules and observed practice remain separate until the combined result is
reported.

## Repository layout

```text
decidr/graph_app/                 Streamlit user interface
decidr/corpus_search.py           Saif whole-corpus retrieval orchestration
decidr/retrieval.py               FTS5/BM25 lexical retrieval
decidr/semantic.py                Optional local semantic retrieval
decidr/hybrid.py                  Reciprocal-rank fusion
decidr/ingestion.py               Structured Markdown and CSV ingestion
decidr/corpus_assessment.py       Interpretation, graph assessment and review
decidr/interpretation_models.py   Exact quotation and citation validation
decidr/assessment_adapter.py      Supplied-judgement facet assessment contract
framework/graph_prototype/        Graph model and credibility logic
tests/                            Automated tests
```

The demonstration graph is synthetic. Client corpus files and generated databases remain
outside Git and are configured through environment variables.

## Setup

Python 3.11 and [uv](https://docs.astral.sh/uv/) are required.

```powershell
git clone https://github.com/uts-ilab-2026-team/uts-ilab-capstone-2026-Decidr.ai.git
cd uts-ilab-capstone-2026-Decidr.ai
uv sync --frozen
```

All dependencies are declared in `pyproject.toml` and resolved in `uv.lock`; no separate
requirements file is needed.

## Run the graph prototype

```powershell
uv run streamlit run decidr/graph_app/Home.py
```

Open <http://localhost:8501> if the application does not open automatically.

The application has four working pages:

- **Graph Credibility Framework** retrieves a Fact and displays its evidence and credibility
  trace.
- **Graph Facts Register** derives reviewable and exportable records from the graph's Facts.
- **End-to-End Claim Assessment** uses Saif's structured retrieval package and exposes numeric
  comparisons as diagnostics. It deliberately leaves support/contradiction unresolved for
  explicit human judgement.
- **Corpus Facts Register** stores immutable assessment packets and independent human reviews,
  and promotes a row only after reviewer agreement or immutable adjudication.

Copy `.env.example` to `.env` and set the local Phase 2 corpus directory.
The End-to-End Claim Assessment page can ingest or refresh that configured directory into
`data/processed/evidence.sqlite3`. The database is ignored by Git and evidence is not sent to
an external service. Refreshes are published as complete source snapshots: an extraction
failure leaves the previous searchable snapshot unchanged. Markdown search hits from one
section are shown together as context but count as one provenance origin. Exact record IDs
can add linked records outside the ranking cutoff without automatically treating those links
as supporting or contradicting evidence.

### Windows PowerShell

If `uv` is not available but the local virtual environment already exists, run:

```powershell
.\.venv\Scripts\python.exe -m streamlit run decidr\graph_app\Home.py
```

Use quoted or literal paths when the project path contains spaces. Do not copy the macOS
`.venv/bin/python` commands; Windows uses `.venv\Scripts\python.exe`.

## Quality checks

```powershell
uv run ruff format --check .
uv run ruff check .
uv run pytest
```

The same commands run automatically for pull requests and pushes to `main`.

## Interpretation and limitations

The prototype supports research and reviewer judgement; it does not establish objective
organisational truth. It must not be used to make automated employment, disciplinary, legal,
compliance or personnel decisions.

The bundled graph is a synthetic demonstration. Retrieval and graph outcomes show that the
implemented rules behave as designed; they do not establish validated research performance.
Automated outcomes remain candidates. The register exposes an agreement metric only after
independently reviewed final findings exist.

## Team

iLab 14-02 Project Group

- Apaar Agarwal
- Isanka Rashmitha Dissanayake Dissanayake Mudiyanselage
- Mohanned Habib
- Royston Camilo Reis
- Raymond Halim
- Saif Muzaffar Parkar
