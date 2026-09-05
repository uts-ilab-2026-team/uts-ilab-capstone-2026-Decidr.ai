"""Decidr credibility-assessment prototype overview."""

import sqlite3

import streamlit as st

from decidr.config import DATABASE_PATH


st.set_page_config(page_title="Decidr", page_icon="🔎", layout="wide")
st.title("Decidr evidence credibility prototype")
st.error("TEST MODE — experimental and test-namespaced records are excluded from formal evaluation.")
st.warning(
    "Decision-support research prototype only. It assesses evidential support for scoped "
    "claims; it does not establish organisational truth and must not be used for automated "
    "employment, disciplinary, or legal decisions."
)

if not DATABASE_PATH.exists():
    st.error("No evidence ledger found. Run `uv run python -m decidr.dataset` first.")
    st.stop()

with sqlite3.connect(DATABASE_PATH) as connection:
    source_count = connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
    evidence_count = connection.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]
    claim_count = connection.execute("SELECT COUNT(*) FROM claims").fetchone()[0]
    excluded_count = connection.execute(
        "SELECT COUNT(*) FROM sources WHERE ingestion_status='excluded'"
    ).fetchone()[0]

columns = st.columns(4)
columns[0].metric("Registered sources", source_count)
columns[1].metric("Evidence units", evidence_count)
columns[2].metric("Claims", claim_count)
columns[3].metric("Source exclusions", excluded_count)

st.subheader("Baseline workflow")
st.markdown(
    "1. Inspect the approved frozen portfolio in **Claims and Retrieval**.\n"
    "2. Royston and Isanka work independently in isolated reviewer workspaces.\n"
    "3. Compare and adjudicate development claims only after both reviews are complete.\n"
    "4. Keep held-out comparison and evaluation sealed until the reasoning ruleset is frozen."
)
st.caption(
    "The corpus is synthetic/anonymised, the claim portfolio is purposive, source authority "
    "is contextual, and absence of evidence is not evidence of absence."
)
