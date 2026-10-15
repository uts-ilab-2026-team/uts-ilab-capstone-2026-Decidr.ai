# uts-ilab-capstone-2026-Decidr.ai

Project delivery, technical development and assessment evidence for UTS Innovation Lab Capstone Project - Spring 2026.

## Repository layout

    data/          Datasets - not in git, create locally (see below)
    decidr/        Python source code
    docs/          Documentation, decision records, meeting notes
    framework/     Claim definition, credibility criteria, assessment methodology
    frontend/      React web app (Vite) that calls the API in decidr/api
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

## Local models (Ollama)

Assessment runs fully locally against [Ollama](https://ollama.com) — no paid API. Install it,
then pull the two models the pipeline uses **before running an assessment**:

    ollama pull qwen3.5:9b      # reads the evidence (required for assessment)
    ollama pull all-minilm      # embeds passages for semantic retrieval (recommended)

- `qwen3.5:9b` is the reader (`ASSESSMENT_MODEL`). Without it, a claim assessment cannot run.
- `all-minilm` is the embedder (`SEMANTIC_MODEL`). Without it, retrieval degrades gracefully to
  lexical-only (keyword/FTS) — nothing crashes, results are just less recall-complete.

Both are served by the same local Ollama server (`http://127.0.0.1:11434`). After the corpus is in
place, pre-index its embeddings once so each claim reuses the stored vectors instead of
re-embedding every passage:

    uv run python -m decidr.reading.preindex      # writes data/app/embedding_cache.sqlite

## Running the app

The web app is a React frontend over a FastAPI backend. Run each in its own terminal:

    # API on http://localhost:8000
    uv run uvicorn decidr.api.app:app --reload --port 8000

    # frontend on http://localhost:5173 (proxies /api to the API)
    cd frontend
    pnpm install
    pnpm dev

Create an account from the sign-in screen ("Request access"). Accounts are stored locally in
`data/app/users.db`, which is not committed. There is no email service, so "Forgot password?"
prints the reset link in the API terminal instead of sending it.

To serve both from one process, run `pnpm build` in `frontend/`; the API then serves the
built app at http://localhost:8000.

## Data

Datasets are not committed to this repository. Create the folder locally and add the
release files yourself:

    mkdir -p data/raw data/interim data/processed

Ask the team for the current phase release.

## Team

iLab 14-02 Project Group

- Apaar Agarwal
- Isanka Rashmitha Dissanayake Dissanayake Mudiyanselage
- Mohanned Habib
- Royston Camilo Reis
- Raymond Halim
- Saif Muzaffar Parkar
