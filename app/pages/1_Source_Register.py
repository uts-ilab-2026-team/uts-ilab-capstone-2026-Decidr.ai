"""Searchable source register."""

import json

import pandas as pd
import streamlit as st

from decidr.config import DATABASE_PATH
from decidr.database import connect


st.title("Source Register")
query = st.text_input("Search title, type, path, or source ID")
with connect(DATABASE_PATH) as connection:
    rows = connection.execute("SELECT payload_json FROM sources ORDER BY source_id").fetchall()
sources = [json.loads(row[0]) for row in rows]
if query:
    sources = [source for source in sources if query.casefold() in json.dumps(source).casefold()]
fields = [
    "source_id",
    "title",
    "source_type",
    "lifecycle_status",
    "version",
    "approval_status",
    "duplicate_group",
    "predecessor_source_id",
    "successor_source_id",
    "ingestion_status",
    "exclusion_reason",
]
st.dataframe(pd.DataFrame([{key: item.get(key) for key in fields} for item in sources]), width="stretch")
if sources:
    selected = st.selectbox("Inspect source", [item["source_id"] for item in sources])
    source = next(item for item in sources if item["source_id"] == selected)
    st.json(source)
    with connect(DATABASE_PATH) as connection:
        evidence = connection.execute(
            "SELECT locator, text_content FROM evidence WHERE source_id=? ORDER BY locator", (selected,)
        ).fetchall()
    st.write(f"Evidence units: {len(evidence)}")
    for locator, text in evidence:
        with st.expander(locator):
            st.text(text)
