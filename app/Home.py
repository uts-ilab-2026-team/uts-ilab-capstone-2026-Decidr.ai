"""Decidr claim-first employee application, with separate research navigation."""

from app.employee import (
    assess_page,
    explorer_page,
    register_page,
    review_page,
    risks_page,
    source_page,
)
import streamlit as st

from decidr.claim_workflow import corpus_state, initialise_workflow
from decidr.config import DATABASE_PATH
from decidr.database import connect

st.set_page_config(page_title="Decidr · Claim assessment", page_icon="🔎", layout="wide")
if not DATABASE_PATH.exists():
    st.title("Decidr")
    st.info("Create the Phase 2 evidence ledger first: uv run python -m decidr.dataset")
    st.stop()
with connect(DATABASE_PATH) as connection:
    initialise_workflow(connection)
    state = corpus_state(connection)
st.sidebar.title("Decidr")
st.sidebar.caption("Organisational claims, evidence and knowledge risks")
st.sidebar.caption(
    f"Corpus snapshot convention: {state['snapshot_date'] or 'Set date during review'}"
)
st.sidebar.caption("System assessment · Optional subsequent human review · Qualitative confidence")
nav = st.navigation(
    {
        "Employee": [
            st.Page(assess_page, title="Assess a Claim", default=True),
            st.Page(register_page, title="Claim Register"),
            st.Page(risks_page, title="Knowledge Risks"),
            st.Page(explorer_page, title="Evidence Explorer"),
        ],
        "Research / admin": [
            st.Page(review_page, title="Claim evidence review"),
            st.Page("pages/1_Source_Register.py", title="Source register"),
            st.Page("pages/2_Claims_and_Retrieval.py", title="Study claims and retrieval"),
            st.Page("pages/3_Human_Review.py", title="Blind study review"),
            st.Page("pages/4_Claim_Assessment.py", title="Approach A baseline"),
            st.Page("pages/5_Evidence_Graph.py", title="Research evidence graph"),
            st.Page("pages/6_Reviewer_Comparison.py", title="Reviewer comparison"),
            st.Page("pages/7_Evaluation.py", title="Evaluation gates"),
            st.Page("pages/8_Configuration_and_Audit.py", title="Configuration and audit"),
            st.Page("pages/9_Study_Setup.py", title="Study setup"),
            st.Page(
                "pages/10_Approach_B_Graph_and_LLM_Assistant.py",
                title="Archived question experiments",
            ),
            st.Page("pages/11_Approach_Comparison.py", title="Approach comparison"),
        ],
    }
)
if nav.title == "Archived question experiments":
    st.warning(
        "Research artifact: question interpretation and automatic relationship suggestions are experimental and are not used by the employee claim-first workflow."
    )
if source_id := st.query_params.get("source"):
    source_page(source_id)
else:
    nav.run()
