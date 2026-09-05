"""Post-review deterministic assessment and traceable explanation."""

import hashlib
import json

import streamlit as st

from decidr.config import DATABASE_PATH, PROJ_ROOT
from decidr.database import connect, save_claim_assessment
from decidr.explanation import render_explanation
from decidr.models import (
    AtomicClaim,
    ClaimAssessment,
    ClaimEvidenceLink,
    CredibilityAssessment,
    Source,
)
from decidr.reasoning import ReviewedEvidence, assess_claim, load_reasoning_config


st.title("Claim Assessment")
with connect(DATABASE_PATH) as connection:
    completed = connection.execute(
        """
        SELECT claim_id, reviewer FROM claim_assessments
        WHERE review_status='complete' AND reviewer NOT LIKE 'automated:%'
        ORDER BY claim_id, reviewer
        """
    ).fetchall()
if not completed:
    st.info("Complete a blind human assessment before revealing an automated outcome.")
    st.stop()

selection = st.selectbox("Completed review", [f"{row[0]} — {row[1]}" for row in completed])
claim_id, reviewer = selection.split(" — ", 1)
with connect(DATABASE_PATH) as connection:
    claim = AtomicClaim.model_validate_json(
        connection.execute("SELECT payload_json FROM claims WHERE claim_id=?", (claim_id,)).fetchone()[0]
    )
    rows = connection.execute(
        """
        SELECT l.payload_json, c.payload_json, s.payload_json
        FROM claim_evidence_links l
        JOIN credibility_assessments c ON c.link_id=l.link_id
        JOIN evidence e ON e.evidence_id=l.evidence_id
        JOIN sources s ON s.source_id=e.source_id
        WHERE l.claim_id=? AND l.reviewer=?
        """,
        (claim_id, reviewer),
    ).fetchall()
reviewed = []
for link_json, credibility_json, source_json in rows:
    link = ClaimEvidenceLink.model_validate_json(link_json)
    credibility = CredibilityAssessment.model_validate_json(credibility_json)
    source = Source.model_validate_json(source_json)
    with connect(DATABASE_PATH) as connection:
        evidence_row = connection.execute(
            "SELECT source_id, locator FROM evidence WHERE evidence_id=?", (link.evidence_id,)
        ).fetchone()
    reviewed.append(
        ReviewedEvidence(
            evidence_id=link.evidence_id,
            source_id=evidence_row[0],
            locator=evidence_row[1],
            relationship=link.relationship,
            target_match=link.target_match,
            scope_match=link.scope_match,
            condition_match=link.condition_match,
            temporal_match=link.temporal_match,
            credibility=credibility,
            duplicate_group=source.duplicate_group,
            lifecycle_status=source.lifecycle_status,
        )
    )
gaps_text = st.text_area("Expected evidence gaps (one per line)")
if st.button("Run deterministic assessment"):
    config = load_reasoning_config(PROJ_ROOT / "configs" / "reasoning.json")
    result = assess_claim(
        reviewed,
        [line.strip() for line in gaps_text.splitlines() if line.strip()],
        config,
        claim.evidence_target,
    )
    explanation = render_explanation(claim, result)
    assessment_id = "AUTO-" + hashlib.sha256(f"{claim_id}\0{reviewer}".encode()).hexdigest()[:16]
    assessment = ClaimAssessment(
        assessment_id=assessment_id,
        claim_id=claim_id,
        reviewer=f"automated:{reviewer}",
        outcome=result.outcome,
        confidence=result.confidence,
        uncertainty_explanation="Confidence follows decisive independent evidence and recorded gaps.",
        explanation=explanation,
        review_status="complete",
    )
    with connect(DATABASE_PATH) as connection:
        save_claim_assessment(connection, assessment, list(result.traces))
    st.metric("Outcome", result.outcome.value)
    st.metric("Separate confidence", result.confidence.value)
    st.markdown(explanation)
    st.download_button("Download assessment Markdown", explanation, f"{claim_id}-assessment.md")

reviewer_counts = {}
for row in completed:
    reviewer_counts[row[0]] = reviewer_counts.get(row[0], 0) + 1
if reviewer_counts.get(claim_id, 0) < 2:
    st.warning("Reference assessment incomplete: fewer than two independent reviewers are complete.")
