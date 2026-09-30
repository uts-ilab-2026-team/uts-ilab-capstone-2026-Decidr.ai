#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

python3.11 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-graph.txt
.venv/bin/python -m streamlit run decidr/graph_app/Home.py
