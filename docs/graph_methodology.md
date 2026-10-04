# Graph credibility methodology

This is the independent graph-based credibility framework and graph facts register. Its files
are distributed across the repository according to their purpose rather than stored as a
second repository inside `framework`.

## Repository locations

- `framework/` contains the framework as focused modules: `constants.py`, `errors.py`,
  `models.py`, `config.py`, `graph.py` (validation, retrieval, visualisation),
  `credibility.py` (reasoning) and `register.py`. The public API is exposed by
  `framework/__init__.py` (`from framework import ...`).
- `framework/data/` holds the credibility configuration (`credibility.json`) and the
  demonstration graph (`prototype_graph.json`).
- `decidr/graph_app/` contains the Streamlit user interface.
- `tests/test_graph_prototype.py` contains the graph-specific automated tests.
- `requirements-graph.txt` contains the additional runtime and test dependencies.
- `setup_graph_and_run.ps1` and `setup_graph_and_run.sh` launch the prototype locally.
- `.github/workflows/graph-quality.yml` checks only the graph files.

No existing ledger code, repository configuration, report or previous archive is modified by
this layout.

## Method

- Person, Role, Function, Process and System form the organisational backbone.
- Document and Fact nodes represent evidence sources and searchable topics.
- Asserted values are stored on `FORMAL` and `OBSERVED` Document-to-Fact relationships.
- Local deterministic TF-IDF retrieval finds candidate Facts.
- Deterministic rules consider source authority, approval status, version and recency,
  directness, specificity, corroboration, independence and completeness.
- Formal and observed outcomes remain separate before a combined outcome is produced.
- Outcome and confidence remain separate, and missing evidence is recorded as a gap.

## Windows setup

From the repository root, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup_graph_and_run.ps1
```

Then open <http://localhost:8501> if the browser does not open automatically.

## Manual setup

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-graph.txt
.\.venv\Scripts\python.exe -m streamlit run decidr\graph_app\Home.py
```

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_graph_prototype.py -q
```

The bundled graph is synthetic demonstration data. Replace
`framework/data/prototype_graph.json` only with an approved graph that follows the same
documented node-and-edge structure.
