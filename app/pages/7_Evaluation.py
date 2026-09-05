"""Guarded research evaluation and synthetic challenge inspection."""

import pandas as pd
import streamlit as st

from decidr.challenges import run_challenges
import hashlib
import json

from decidr.config import DATABASE_PATH, PROJ_ROOT
from decidr.database import connect, save_evaluation_error
from decidr.evaluate import build_evaluation
from decidr.evaluation import ErrorCategory
from decidr.models import EvaluationError


st.title("Evaluation")
study_configuration = json.loads(
    (PROJ_ROOT / "configs" / "human_study.json").read_text(encoding="utf-8")
)
if not study_configuration["final_evaluation_authorised"]:
    st.warning(
        "Final and held-out evaluation are locked until independent reviews, adjudication, "
        "and development-rule freezing are complete."
    )
    st.stop()

report = build_evaluation(DATABASE_PATH)
research = report["research_results"]
columns = st.columns(3)
columns[0].metric("Adjudicated references", research["adjudicated_reference_count"])
columns[1].metric("Automated assessments", research["automated_assessment_count"])
columns[2].metric(
    "Comparable claims", research["outcome_evaluation"]["evaluated_claims"]
)
if research["limitation"]:
    st.warning(research["limitation"])
outcomes = research["outcome_evaluation"]
if outcomes["agreement_rate"] is not None:
    st.metric("Outcome agreement", f"{outcomes['agreement_rate']:.1%}")
    st.subheader("Confusion matrix")
    st.dataframe(pd.DataFrame(outcomes["confusion_matrix"]).T, use_container_width=True)
    st.write("Disagreement claims:", outcomes["disagreements"] or "None")
else:
    st.info("No outcome metric is shown until resolved adjudicated references can be compared.")

st.subheader("Synthetic behavioral challenges")
st.error("These fixtures test software behavior. They are not corpus evaluation results.")
challenges = run_challenges()
st.dataframe(
    pd.DataFrame(
        [
            {
                "id": item.challenge_id,
                "challenge": item.name,
                "passed": item.passed,
                "observed": item.observed,
                "expected principle": item.expected_principle,
            }
            for item in challenges
        ]
    ),
    use_container_width=True,
)
st.subheader("Error taxonomy")
with connect(DATABASE_PATH) as connection:
    claims = [row[0] for row in connection.execute("SELECT claim_id FROM claims ORDER BY claim_id")]
    errors = [
        json.loads(row[0])
        for row in connection.execute(
            "SELECT payload_json FROM evaluation_errors ORDER BY claim_id, created_at"
        )
    ]
if errors:
    st.dataframe(pd.DataFrame(errors), use_container_width=True)
elif claims:
    st.info("No qualitative errors have been recorded yet.")
else:
    st.info("Create claims before recording per-claim errors.")
if claims:
    with st.form("error_record"):
        error_claim = st.selectbox("Claim", claims)
        category = st.selectbox("Error category", [item.value for item in ErrorCategory])
        component = st.text_input("Component")
        description = st.text_area("Error description")
        reviewer = st.text_input("Reviewer")
        save_error = st.form_submit_button("Record qualitative error")
    if save_error:
        digest = hashlib.sha256(
            f"{error_claim}\0{category}\0{component}\0{description}".encode()
        ).hexdigest()[:16]
        item = EvaluationError(
            error_id=f"ERR-{digest}",
            claim_id=error_claim,
            category=category,
            component=component,
            description=description,
            reviewer=reviewer,
        )
        with connect(DATABASE_PATH) as connection:
            save_evaluation_error(connection, item)
        st.success("Per-claim error recorded.")

st.subheader("Controlled component comparison")
st.dataframe(pd.DataFrame(report["component_comparison"]), use_container_width=True)
st.caption("Blank observed-benefit/error fields mean no adjudicated comparison has been run.")
