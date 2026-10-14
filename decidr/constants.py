"""Shared, globally-used constants for the ``decidr`` package.

Single home for values that were previously duplicated across modules: the
repository root, the built graph path, the corpus "as of" cutoff date, the
source-code regex, and the local assessment-model (Ollama) connection defaults.

Deliberately dependency-light — standard library only — so any module can import
it without pulling in heavy or side-effecting dependencies.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
import re

# --------------------------------------------------------------------------- #
# Paths                                                                        #
# --------------------------------------------------------------------------- #

# Repository root (``decidr/`` sits one level below it).
REPO_ROOT = Path(__file__).resolve().parents[1]

# The read-only corpus and the built organisational graph snapshot.
DATA_DIR = REPO_ROOT / "data"
CORPUS_GRAPH_PATH = REPO_ROOT / "framework" / "data" / "corpus_graph.json"

# --------------------------------------------------------------------------- #
# Corpus evaluation date                                                       #
# --------------------------------------------------------------------------- #

# The synthetic corpus is read "as at 31 July 2026".
DEFAULT_AS_OF = date(2026, 7, 31)

# --------------------------------------------------------------------------- #
# Source identifiers                                                           #
# --------------------------------------------------------------------------- #

# Corpus source codes, e.g. POL-01, PROC-02, INT-05, MTG-03.
SOURCE_CODE_PATTERN = re.compile(r"\b(?:POL|PROC|INT|MTG)-\d+\b")

# --------------------------------------------------------------------------- #
# Local assessment model (Ollama) connection + sampling defaults              #
# --------------------------------------------------------------------------- #

# The local model is configured here, not via environment variables: provider,
# model tag, loopback endpoint, and request timeout (seconds).
ASSESSMENT_PROVIDER = "ollama"
ASSESSMENT_MODEL = "qwen3.5:9b"
ASSESSMENT_URL = "http://127.0.0.1:11434"
ASSESSMENT_TIMEOUT = 180.0

# Deterministic sampling options sent with every generation request.
ASSESSMENT_SAMPLING = {"temperature": 0, "num_ctx": 32768, "num_predict": 8192}
