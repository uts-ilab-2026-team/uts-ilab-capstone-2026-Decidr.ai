"""Two-reviewer comparison and explicit adjudication."""

import hashlib
import json

import pandas as pd
import streamlit as st

from decidr.config import DATABASE_PATH, PROJ_ROOT
from decidr.database import connect, save_adjudication
from decidr.models import Adjudication, AtomicClaim, ClaimAssessment, ClaimOutcome, ConfidenceLevel
from decidr.study import comparison_claims


st.title("Reviewer Comparison and Adjudication")
configuration = json.loads(
    (PROJ_ROOT / "configs" / "human_study.json").read_text(encoding="utf-8")
)
with connect(DATABASE_PATH) as connection:
    rows = connection.execute(
        """
        SELECT payload_json FROM claim_assessments
        WHERE review_status='complete' AND reviewer NOT LIKE 'automated:%'
        ORDER BY claim_id, reviewer
        """
    ).fetchall()
    claim_rows = connection.execute("SELECT payload_json FROM claims ORDER BY claim_id").fetchall()
assessments = [ClaimAssessment.model_validate_json(row[0]) for row in rows]
claims = [AtomicClaim.model_validate_json(row[0]) for row in claim_rows]
visible_ids = {claim.claim_id for claim in comparison_claims(claims, configuration)}
claim_ids = sorted(
    claim_id
    for claim_id in {item.claim_id for item in assessments}
    if claim_id in visible_ids and sum(item.claim_id == claim_id for item in assessments) >= 2
)
if configuration["held_out_access_status"] == "sealed":
    st.warning("Held-out reviewer comparison and adjudication remain sealed.")
if not claim_ids:
    st.info("At least two distinct completed human reviews are required. No reviewer is fabricated.")
    st.stop()
claim_id = st.selectbox("Claim", claim_ids)
available = [item for item in assessments if item.claim_id == claim_id]
reviewer_a = st.selectbox("Reviewer A", [item.reviewer for item in available])
reviewer_b = st.selectbox(
    "Reviewer B", [item.reviewer for item in available if item.reviewer != reviewer_a]
)
selected = [item for item in available if item.reviewer in {reviewer_a, reviewer_b}]
st.dataframe(
    pd.DataFrame(
        [
            {
                "reviewer": item.reviewer,
                "outcome": item.outcome.value,
                "confidence": item.confidence.value,
                "uncertainty": item.uncertainty_explanation,
                "explanation": item.explanation,
            }
            for item in selected
        ]
    ),
    use_container_width=True,
)
with connect(DATABASE_PATH) as connection:
    links = connection.execute(
        """
        SELECT reviewer, evidence_id, relationship, payload_json
        FROM claim_evidence_links
        WHERE claim_id=? AND reviewer IN (?, ?)
        ORDER BY evidence_id, reviewer
        """,
        (claim_id, reviewer_a, reviewer_b),
    ).fetchall()
st.subheader("Evidence-level judgements")
st.dataframe(
    pd.DataFrame(
        [
            {
                "reviewer": row[0],
                "evidence_id": row[1],
                "relationship": row[2],
                "applicability_reason": json.loads(row[3])["applicability_reason"],
            }
            for row in links
        ]
    ),
    use_container_width=True,
)

with st.form("adjudication"):
    adjudicator = st.text_input("Adjudicator identifier")
    preserve = st.checkbox("Preserve genuine disagreement without a final outcome")
    final_outcome = st.selectbox("Final reviewed outcome", [item.value for item in ClaimOutcome])
    final_confidence = st.selectbox(
        "Final reviewed confidence", [item.value for item in ConfidenceLevel]
    )
    rationale = st.text_area("Adjudication rationale")
    submitted = st.form_submit_button("Save adjudication")
if submitted:
    ordered_reviewers = sorted((reviewer_a, reviewer_b))
    digest = hashlib.sha256(f"{claim_id}\0{'|'.join(ordered_reviewers)}".encode()).hexdigest()[:16]
    item = Adjudication(
        adjudication_id=f"ADJ-{digest}",
        claim_id=claim_id,
        reviewer_a=ordered_reviewers[0],
        reviewer_b=ordered_reviewers[1],
        adjudicator=adjudicator,
        preserve_disagreement=preserve,
        final_outcome=None if preserve else final_outcome,
        final_confidence=None if preserve else final_confidence,
        rationale=rationale,
    )
    with connect(DATABASE_PATH) as connection:
        save_adjudication(connection, item)
    st.success("Disagreement preserved." if preserve else "Reviewed reference adjudication saved.")
