"""Interactive inspection of the standalone graph credibility framework."""

from datetime import date

from framework import (
    CONFIG_PATH,
    CREDIBILITY_DIMENSIONS,
    CREDIBILITY_QUESTIONS,
    GRAPH_PATH,
    GraphCredibilityFramework,
)
import pandas as pd
import streamlit as st

framework = GraphCredibilityFramework.load(
    GRAPH_PATH,
    CONFIG_PATH,
)

st.title("Graph Credibility Framework")
st.caption(
    "Standalone graph method: Facts contain topics; Document edges contain asserted values. "
    "Materiality is not a probability of truth."
)

with st.expander("Configured credibility dimensions"):
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Dimension": dimension.replace("_", " ").title(),
                    "Reviewer question": CREDIBILITY_QUESTIONS[dimension],
                    "Weight": framework.config.dimension_weights[dimension],
                }
                for dimension in CREDIBILITY_DIMENSIONS
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )
    st.write(
        "Applicable evidence is scored as: weighted dimensions × lifecycle multiplier × "
        "source-authority multiplier."
    )

query = st.text_input(
    "Claim or organisational question",
    value="Discounts above 15% require Head of Finance approval before closing",
)
matches = framework.graph.retrieve_facts(query)
if matches:
    st.markdown("#### Retrieved candidate Facts")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Fact ID": fact.node_id,
                    "Fact": fact.label,
                    "Similarity": round(score, 4),
                }
                for fact, score in matches
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )

fact_ids = [fact.node_id for fact in framework.graph.fact_nodes()]
default_id = matches[0][0].node_id if matches else fact_ids[0]
selected_id = st.selectbox(
    "Fact to assess",
    fact_ids,
    index=fact_ids.index(default_id),
    format_func=lambda value: f"{value} — {framework.graph.nodes[value].label}",
)
as_of = st.date_input("Assess sources as at", value=date(2026, 7, 31))
assessment = framework.evaluate_fact(selected_id, as_of=as_of)

st.graphviz_chart(framework.graph.fact_dot(selected_id), use_container_width=True)

formal_column, observed_column, overall_column, confidence_column = st.columns(4)
formal_column.metric("Formal outcome", assessment.formal_outcome)
observed_column.metric("Observed outcome", assessment.observed_outcome)
overall_column.metric("Combined outcome", assessment.overall_outcome)
confidence_column.metric("Separate confidence", assessment.confidence)
st.write(assessment.summary)

st.markdown("#### Document attestations")
if assessment.evidence:
    evidence_rows = [
        {
            "Document": item.document_id,
            "Mode": item.mode,
            "Attests value": item.attests_value,
            "Stance": item.stance,
            "Source class": item.source_class,
            "Status": item.lifecycle_status,
            "Applicable": item.applicable,
            "Materiality": (
                round(item.materiality_score, 3) if item.materiality_score is not None else None
            ),
            "Material": item.material,
        }
        for item in assessment.evidence
    ]
    st.dataframe(pd.DataFrame(evidence_rows), use_container_width=True, hide_index=True)
    selected_edge_id = st.selectbox(
        "Inspect an attestation",
        [item.edge_id for item in assessment.evidence],
    )
    selected_edge = next(item for item in assessment.evidence if item.edge_id == selected_edge_id)
    if selected_edge.dimensions:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Dimension": name.replace("_", " ").title(),
                        "Value": value,
                        "Weight": framework.config.dimension_weights[name],
                    }
                    for name, value in selected_edge.dimensions.items()
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )
    with st.expander("Ordered derivation trace", expanded=True):
        for step in selected_edge.trace:
            st.write(f"- {step}")
        if selected_edge.limitations:
            st.markdown("**Limitations**")
            for limitation in selected_edge.limitations:
                st.write(f"- {limitation}")
else:
    st.info("No Document attests to this Fact.")

if assessment.related_qualifiers:
    st.markdown("#### One-hop related-Fact qualifications")
    for qualifier in assessment.related_qualifiers:
        st.write(f"- {qualifier}")

if assessment.gaps:
    st.markdown("#### Evidence gaps")
    for gap in assessment.gaps:
        st.write(f"- {gap}")

with st.expander("Rules applied"):
    for rule in assessment.rules_applied:
        st.code(rule)
