"""Active configuration, reproducibility state, audit history, and exports."""

import hashlib
import json

import pandas as pd
import streamlit as st

from decidr.config import DATABASE_PATH, PROJ_ROOT, REPORTS_DIR
from decidr.database import connect, reset_test_records
from decidr.exports import export_ledger


st.title("Configuration and Audit")
config_path = PROJ_ROOT / "configs" / "reasoning.json"
st.subheader("Active reasoning configuration")
configuration = json.loads(config_path.read_text(encoding="utf-8"))
st.json(configuration)
st.caption(
    "The materiality value is an experimental filter, not truth probability. "
    "No source type has permanent authority."
)

with connect(DATABASE_PATH) as connection:
    sources = connection.execute("SELECT source_id, checksum FROM sources ORDER BY source_id").fetchall()
    retrieval_runs = connection.execute(
        """
        SELECT run_id, claim_id, method, model_name, model_version, latency_ms, created_at
        FROM retrieval_runs ORDER BY created_at DESC
        """
    ).fetchall()
    audit_rows = connection.execute(
        """
        SELECT audit_id, actor, action, entity_type, entity_id,
               changed_fields_json, occurred_at
        FROM audit_events ORDER BY audit_id DESC
        """
    ).fetchall()
fingerprint = hashlib.sha256()
for source_id, checksum in sources:
    fingerprint.update(f"{source_id}\0{checksum}\n".encode())
st.subheader("Reproducibility state")
st.code(f"Dataset fingerprint: {fingerprint.hexdigest()}\nDatabase: {DATABASE_PATH}")

st.subheader("Retrieval runs")
st.dataframe(
    pd.DataFrame(
        retrieval_runs,
        columns=["run_id", "claim_id", "method", "model", "version", "latency_ms", "created_at"],
    ),
    use_container_width=True,
)

st.subheader("Audit history")
st.dataframe(
    pd.DataFrame(
        audit_rows,
        columns=["id", "actor", "action", "entity_type", "entity_id", "changed_fields", "time"],
    ),
    use_container_width=True,
)

if st.button("Export all registers and available reports"):
    manifest = export_ledger(DATABASE_PATH, REPORTS_DIR / "exports")
    st.success(f"Exported {len(manifest['counts'])} registers to reports/exports.")
    st.json(manifest)

st.subheader("Safe TEST MODE reset")
st.warning("This removes only records whose reviewer identifier starts with `test:`.")
confirmation = st.text_input("Type RESET TEST DATA to continue")
if st.button("Reset test records", disabled=confirmation != "RESET TEST DATA"):
    with connect(DATABASE_PATH) as connection:
        removed = reset_test_records(connection)
    st.success(f"Removed test-namespaced records only: {removed}")
