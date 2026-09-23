"""Traceable facts-register view derived from the evidence ledger."""

import pandas as pd
import streamlit as st

from decidr.config import DATABASE_PATH
from decidr.database import connect
from decidr.facts_register import FactsRegister
from decidr.ui import require_database

st.title("Facts Register")
require_database()
st.write(
    "Rows begin as claim candidates. A row becomes an assessed organisational finding only "
    "after independent review and resolved adjudication. Automated results are never promoted "
    "to final facts on their own."
)

include_excluded = st.checkbox("Include excluded claims")
with connect(DATABASE_PATH) as connection:
    register = FactsRegister(connection)
    records = register.list_records(include_excluded=include_excluded)
    csv_export = register.to_csv(include_excluded=include_excluded)
    json_export = register.to_json(include_excluded=include_excluded)

if not records:
    st.info("No claim candidates are registered yet.")
    st.stop()

statuses = sorted({record.status.value for record in records})
selected_statuses = st.multiselect("Status", statuses, default=statuses)
filtered = [record for record in records if record.status.value in selected_statuses]

display_rows = [
    {
        "Claim ID": record.claim.claim_id,
        "Atomic claim": record.claim.claim_text,
        "Status": record.status.value,
        "Final outcome": record.final_outcome.value if record.final_outcome else "",
        "Final confidence": record.final_confidence.value if record.final_confidence else "",
        "Human reviewers": len(record.independent_human_reviewers),
        "Evidence reviews": record.evidence_review_count,
        "Sources": record.source_count,
        "Recorded gaps": len(record.evidence_gaps),
    }
    for record in filtered
]
st.dataframe(pd.DataFrame(display_rows), width="stretch", hide_index=True)

if filtered:
    selected_claim_id = st.selectbox(
        "Inspect register row", [record.claim.claim_id for record in filtered]
    )
    selected = next(record for record in filtered if record.claim.claim_id == selected_claim_id)
    st.subheader(selected.claim.claim_text)
    st.caption(selected.status_reason)
    if selected.is_final_finding:
        outcome_column, confidence_column, finaliser_column = st.columns(3)
        outcome_column.metric("Final outcome", selected.final_outcome.value)
        confidence_column.metric("Final confidence", selected.final_confidence.value)
        finaliser_column.metric("Finalised by", selected.finalised_by)
    else:
        st.warning("This row is not yet a final organisational finding.")

    if selected.reviewer_findings:
        st.markdown("#### Separate reviewer findings")
        st.dataframe(
            pd.DataFrame(
                [finding.model_dump(mode="json") for finding in selected.reviewer_findings]
            ),
            width="stretch",
            hide_index=True,
        )
    if selected.evidence_gaps:
        st.markdown("#### Missing evidence")
        for gap in selected.evidence_gaps:
            st.write(f"- {gap}")

download_csv, download_json = st.columns(2)
download_csv.download_button(
    "Download facts register CSV",
    csv_export,
    "facts_register.csv",
    "text/csv",
)
download_json.download_button(
    "Download facts register JSON",
    json_export,
    "facts_register.json",
    "application/json",
)
