"""Shared Streamlit startup checks."""

from pathlib import Path

import streamlit as st

from decidr.config import DATABASE_PATH
from decidr.database import database_readiness


def require_database(path: Path = DATABASE_PATH) -> None:
    """Stop a page cleanly when the local evidence ledger is unavailable."""
    ready, message = database_readiness(path)
    if not ready:
        st.error(message)
        st.stop()
