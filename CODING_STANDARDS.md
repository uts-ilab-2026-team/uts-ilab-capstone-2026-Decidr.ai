# Coding Standards

## Tools

- Python 3.11
- `uv` for dependencies
- `ruff` for formatting and linting
- `pytest` for tests

Run before pushing:

    uv run ruff format .
    uv run ruff check . --fix
    uv run pytest

## Naming

- Files and functions: `snake_case` - `load_claims()`
- Classes: `PascalCase` - `ClaimRegister`
- Constants: `UPPER_SNAKE_CASE` - `RAW_DATA_DIR`
- Notebooks: `NN-initials-topic.ipynb` - `01-id-explore-corpus.ipynb`

## Python

- Type hints on functions
- Docstrings on anything another person will call
- Comments explain why, not what
- No hard-coded paths or shared constants - import them from `decidr/constants.py`

## Notebooks

- Clear all outputs before committing
- Restart and run all should work top to bottom
- Do not import from a notebook - move reusable code into `decidr/`

## Writing

- Markdown for all written work
- Be clear about whether something is what a document says, what a person said, or what you concluded
