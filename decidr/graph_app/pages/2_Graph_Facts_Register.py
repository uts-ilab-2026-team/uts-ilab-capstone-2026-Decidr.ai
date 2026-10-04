"""Standalone facts register derived only from the graph prototype."""

from datetime import date

from framework import (
    CONFIG_PATH,
    GRAPH_PATH,
    GraphCredibilityFramework,
    GraphFactsRegister,
)
import pandas as pd
import streamlit as st

framework = GraphCredibilityFramework.load(
    GRAPH_PATH,
    CONFIG_PATH,
)

st.title("Graph Facts Register")
st.write(
    "This register is derived from graph nodes and edges only. Formal rules and observed "
    "practice remain separate, superseded sources stay visible, and missing evidence does "
    "not become contradiction."
)

as_of = st.date_input("Register assessment date", value=date(2026, 7, 31))
register = GraphFactsRegister(framework, as_of=as_of)
records = register.list_records()

statuses = sorted({item.status for item in records})
selected_statuses = st.multiselect("Status", statuses, default=statuses)
filtered = [item for item in records if item.status in selected_statuses]

st.dataframe(
    pd.DataFrame(
        [
            {
                "Fact ID": item.fact_id,
                "Statement": item.statement,
                "Category": item.category,
                "Status": item.status,
                "Formal": item.formal_outcome,
                "Observed": item.observed_outcome,
                "Combined": item.overall_outcome,
                "Confidence": item.confidence,
                "Documents": len(item.documents),
                "Gaps": len(item.gaps),
            }
            for item in filtered
        ]
    ),
    use_container_width=True,
    hide_index=True,
)

if filtered:
    selected_id = st.selectbox("Inspect register row", [item.fact_id for item in filtered])
    record = next(item for item in filtered if item.fact_id == selected_id)
    st.subheader(record.statement)
    status_column, outcome_column, confidence_column = st.columns(3)
    status_column.metric("Status", record.status)
    outcome_column.metric("Combined outcome", record.overall_outcome)
    confidence_column.metric("Confidence", record.confidence)
    st.write(record.derivation_summary)

    formal_column, observed_column = st.columns(2)
    with formal_column:
        st.markdown("#### Formal values")
        if record.formal_values:
            for value in record.formal_values:
                st.write(f"- {value}")
        else:
            st.write("No formal value recorded.")
    with observed_column:
        st.markdown("#### Observed values")
        if record.observed_values:
            for value in record.observed_values:
                st.write(f"- {value}")
        else:
            st.write("No observed value recorded.")

    if record.related_qualifiers:
        st.markdown("#### Related-Fact qualifications")
        for item in record.related_qualifiers:
            st.write(f"- {item}")
    if record.gaps:
        st.markdown("#### Missing evidence")
        for item in record.gaps:
            st.write(f"- {item}")
    with st.expander("Provenance documents"):
        for document in record.documents:
            st.code(document)

csv_column, json_column = st.columns(2)
csv_column.download_button(
    "Download graph facts register CSV",
    register.to_csv(),
    "graph_facts_register.csv",
    "text/csv",
)
json_column.download_button(
    "Download graph facts register JSON",
    register.to_json(),
    "graph_facts_register.json",
    "application/json",
)
