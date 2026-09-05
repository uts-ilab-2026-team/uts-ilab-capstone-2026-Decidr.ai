"""Guarded Approach A/B comparison readiness page."""

import json

import streamlit as st

from decidr.comparison import comparison_readiness
from decidr.config import DATABASE_PATH, PROJ_ROOT
from decidr.database import connect


st.title("Approach A versus Approach B")
st.error("TEST MODE — no formal comparison runs until human references are complete.")
configuration = json.loads(
    (PROJ_ROOT / "configs" / "human_study.json").read_text(encoding="utf-8")
)
with connect(DATABASE_PATH) as connection:
    reviewers = connection.execute(
        """SELECT COUNT(DISTINCT reviewer) FROM claim_assessments
           WHERE review_status='complete' AND reviewer NOT LIKE 'automated:%'
             AND reviewer NOT LIKE 'test:%'"""
    ).fetchone()[0]
    development_references = connection.execute(
        """SELECT COUNT(*) FROM adjudications a JOIN claims c ON c.claim_id=a.claim_id
           WHERE c.evaluation_split='development'"""
    ).fetchone()[0]
readiness = comparison_readiness(configuration, reviewers, development_references)
for blocker in readiness.blockers:
    st.warning(blocker)
st.metric("Development comparison ready", "Yes" if readiness.development_ready else "No")
st.metric("Held-out comparison ready", "Yes" if readiness.held_out_ready else "No — sealed")
st.caption(
    "When unlocked, both approaches use the same frozen claims, evidence IDs, corpus fingerprint, "
    "human references, and evaluation schema. Two held-out claims support descriptive reporting only."
)
