"""Human-study readiness and blind packet preparation."""

import json

import pandas as pd
import streamlit as st

from decidr.config import DATABASE_PATH, PROJ_ROOT, REPORTS_DIR
from decidr.database import connect
from decidr.study import load_claims, validate_portfolio, write_study_materials


st.title("Human Study Setup")
st.caption("This page prepares real reviewers; it never creates claims, labels, or reviewers.")
study_configuration = json.loads(
    (PROJ_ROOT / "configs" / "human_study.json").read_text(encoding="utf-8")
)
configured_reviewers = study_configuration["reviewers"]
packet_authorised = study_configuration["packet_generation_authorised"]
if not packet_authorised:
    st.warning(
        "Blind packet generation is locked pending final human approval of candidate portfolio v1.0."
    )
with connect(DATABASE_PATH) as connection:
    claims = load_claims(connection)
    completed_rows = connection.execute(
        """
        SELECT claim_id, reviewer, outcome, confidence
        FROM claim_assessments
        WHERE review_status='complete' AND reviewer NOT LIKE 'automated:%'
        ORDER BY claim_id, reviewer
        """
    ).fetchall()
readiness = validate_portfolio(claims)
columns = st.columns(3)
columns[0].metric("Included claims", readiness.included_claims)
columns[1].metric("Development", readiness.development_claims)
columns[2].metric("Held-out", readiness.held_out_claims)
if readiness.ready:
    st.success("The claim portfolio meets the configured structural readiness checks.")
else:
    for blocker in readiness.blockers:
        st.error(blocker)
for warning in readiness.warnings:
    st.warning(warning)

st.subheader("Current claim portfolio")
st.dataframe(
    pd.DataFrame(
        [
            {
                "claim_id": claim.claim_id,
                "text": claim.claim_text,
                "split": claim.evaluation_split,
                "atomicity": claim.atomicity_status,
                "inclusion": claim.inclusion_status,
            }
            for claim in claims
        ]
    ),
    width="stretch",
)
st.subheader("Completed human assessments")
st.dataframe(
    pd.DataFrame(completed_rows, columns=["claim_id", "reviewer", "outcome", "confidence"]),
    width="stretch",
)

with st.form("reviewers"):
    reviewer_a = st.text_input(
        "reviewer-a", value=configured_reviewers["reviewer-a"], disabled=True
    )
    reviewer_b = st.text_input(
        "reviewer-b", value=configured_reviewers["reviewer-b"], disabled=True
    )
    generate = st.form_submit_button(
        "Generate two blind reviewer packets", disabled=not packet_authorised
    )
if generate:
    manifest = write_study_materials(
        claims, reviewer_a, reviewer_b, REPORTS_DIR / "study_materials"
    )
    st.success("Two separate blind packets generated under reports/study_materials.")
    st.json(manifest)
    for reviewer in (reviewer_a, reviewer_b):
        safe = "".join(
            character if character.isalnum() or character in "-_" else "-"
            for character in reviewer
        )
        packet_path = REPORTS_DIR / "study_materials" / f"blind-review-{safe}.json"
        st.download_button(
            f"Download packet for {reviewer}",
            packet_path.read_text(encoding="utf-8"),
            packet_path.name,
            "application/json",
        )
