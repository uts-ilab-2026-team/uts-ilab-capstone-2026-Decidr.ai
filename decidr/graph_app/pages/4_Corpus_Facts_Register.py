"""Human-review register for graph assessments built from Saif retrieval."""

import pandas as pd
import streamlit as st

from decidr.corpus_assessment import (
    OUTCOMES,
    AssessmentStore,
    evaluation_summary,
)

CONFIDENCE = ("Higher confidence", "Moderate confidence", "Lower confidence")

st.set_page_config(page_title="Corpus Facts Register", layout="wide")
st.title("Corpus Facts Register")
st.write(
    "Automated candidates remain provisional. A row becomes a human-reviewed finding only "
    "when two distinct reviewers agree, or when a disagreement is adjudicated."
)


@st.cache_resource
def store() -> AssessmentStore:
    return AssessmentStore()


database = store()
rows = database.register_rows()
if not rows:
    st.info("No assessments yet. Run a claim on the End-to-End Claim Assessment page.")
    st.stop()

statuses = sorted({row["status"] for row in rows})
selected_statuses = st.multiselect("Status", statuses, default=statuses)
filtered = [row for row in rows if row["status"] in selected_statuses]
st.table(
    pd.DataFrame(
        [
            {
                "Assessment ID": row["assessment_id"],
                "Claim": row["claim_text"],
                "Status": row["status"],
                "Automated": row["automated_outcome"],
                "Final": row["final_outcome"],
                "Reviewers": row["human_reviewers"],
                "As at": row["as_of"],
            }
            for row in filtered
        ]
    )
)

if filtered:
    selected_id = st.selectbox(
        "Inspect register row",
        [row["assessment_id"] for row in filtered],
        format_func=lambda value: next(
            f"{row['assessment_id']} — {row['claim_text'][:90]}"
            for row in filtered
            if row["assessment_id"] == value
        ),
    )
    selected = next(row for row in filtered if row["assessment_id"] == selected_id)
    st.subheader(selected["claim_text"])
    first, second, third = st.columns(3)
    first.metric("Register status", selected["status"])
    second.metric("Automated outcome", selected["automated_outcome"])
    third.metric("Final outcome", selected["final_outcome"] or "Not final")

    st.markdown("#### Independent reviews")
    if selected["reviews"]:
        st.table(pd.DataFrame(selected["reviews"]))
    else:
        st.info("No independent human review has been recorded.")

    with st.form("independent-review", clear_on_submit=True):
        reviewer = st.text_input("Reviewer name")
        verdict = st.selectbox("Reviewer verdict", OUTCOMES)
        confidence = st.selectbox("Reviewer confidence", CONFIDENCE)
        notes = st.text_area("Evidence-based explanation")
        save_review = st.form_submit_button("Save independent review")
    if save_review:
        try:
            database.save_review(selected_id, reviewer, verdict, confidence, notes)
            st.success("Review saved. Rerun the page to refresh the register status.")
        except ValueError as error:
            st.error(str(error))

    if selected["status"] == "Needs adjudication":
        st.markdown("#### Resolve reviewer disagreement")
        with st.form("adjudication", clear_on_submit=True):
            adjudicator = st.text_input("Adjudicator name")
            final_outcome = st.selectbox("Final outcome", OUTCOMES)
            final_confidence = st.selectbox("Final confidence", CONFIDENCE)
            adjudication_notes = st.text_area("Adjudication rationale")
            adjudicate = st.form_submit_button("Record adjudicated finding")
        if adjudicate:
            try:
                database.save_adjudication(
                    selected_id,
                    adjudicator,
                    final_outcome,
                    final_confidence,
                    adjudication_notes,
                )
                st.success("Adjudication saved. Rerun the page to refresh the final finding.")
            except ValueError as error:
                st.error(str(error))

    with st.expander("Complete provenance and rule trace"):
        st.json(selected["payload"])

st.subheader("Evaluation readiness")
evaluation = evaluation_summary(rows)
left, right = st.columns(2)
left.metric("Final human findings", evaluation["final_findings"])
right.metric(
    "Automated/human agreement",
    (
        f"{evaluation['automated_human_agreement']:.1%}"
        if evaluation["automated_human_agreement"] is not None
        else "Not available"
    ),
)
if evaluation["limitation"]:
    st.warning(evaluation["limitation"])
