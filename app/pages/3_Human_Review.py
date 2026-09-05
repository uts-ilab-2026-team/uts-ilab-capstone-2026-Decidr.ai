"""Blind, reviewer-specific evidence and claim assessment workflow."""

import hashlib
import json

import streamlit as st

from decidr.config import DATABASE_PATH, PROJ_ROOT
from decidr.database import (
    connect,
    save_claim_assessment,
    save_credibility,
    save_link,
)
from decidr.models import (
    AtomicClaim,
    ClaimAssessment,
    ClaimEvidenceLink,
    ClaimOutcome,
    ConfidenceLevel,
    CredibilityAssessment,
    EvidenceMode,
    EvidenceRelationship,
)
from decidr.retrieval import lexical_search


def _identifier(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\0".join(parts).encode()).hexdigest()[:16]
    return f"{prefix}-{digest}"


st.title("Independent Human Review")
st.info("Automated outcomes are hidden on this page. Use a distinct reviewer name for each person.")
configuration = json.loads(
    (PROJ_ROOT / "configs" / "human_study.json").read_text(encoding="utf-8")
)
if configuration["portfolio_status"] != "approved_and_frozen":
    st.warning("Human review is locked until candidate portfolio v1.2 receives final approval.")
    st.stop()
reviewers = configuration["reviewers"]
if "active_reviewer_id" not in st.session_state:
    selected_reviewer_id = st.selectbox("Reviewer workspace", list(reviewers))
    if st.button("Enter isolated reviewer workspace"):
        st.session_state.active_reviewer_id = selected_reviewer_id
        st.rerun()
    st.stop()
reviewer_id = st.session_state.active_reviewer_id
reviewer = reviewers[reviewer_id]
st.caption(f"Active isolated workspace: {reviewer_id} — {reviewer}")
with connect(DATABASE_PATH) as connection:
    rows = connection.execute("SELECT payload_json FROM claims ORDER BY claim_id").fetchall()
claims = [AtomicClaim.model_validate_json(row[0]) for row in rows]
if not claims:
    st.stop()

claim_id = st.selectbox("Claim", [claim.claim_id for claim in claims])
claim = next(item for item in claims if item.claim_id == claim_id)
st.subheader("Claim being assessed")
st.write(claim.claim_text)
st.caption(f"Evidence target: {claim.evidence_target.value if claim.evidence_target else 'not set'}")
with connect(DATABASE_PATH) as connection:
    candidates = lexical_search(connection, claim, limit=30)
candidate_map = {item.evidence_id: item for item in candidates}
evidence_id = st.selectbox(
    "Retrieved evidence to review",
    list(candidate_map),
    format_func=lambda value: f"{candidate_map[value].source_id} — {candidate_map[value].locator}",
)
candidate = candidate_map[evidence_id]
st.subheader("Evidence being reviewed")
st.caption(candidate.match_explanation)
st.text(candidate.text)

with st.form("evidence_review"):
    relationship = st.selectbox("Relationship", [item.value for item in EvidenceRelationship])
    target = st.checkbox("Target matches", value=True)
    scope = st.checkbox("Scope matches", value=True)
    condition = st.checkbox("Conditions match", value=True)
    temporal = st.checkbox("Period matches", value=True)
    applicability_reason = st.text_area("Applicability reason")
    mode = st.selectbox("Evidence mode", [item.value for item in EvidenceMode])
    st.caption("Credibility dimensions are contextual judgements from 0 to 1.")
    dimensions = {
        name: st.slider(name.replace("_", " ").title(), 0.0, 1.0, 0.5, 0.05)
        for name in (
            "relevance",
            "institutional_authority",
            "directness",
            "temporal_validity",
            "independence",
            "completeness",
            "organisational_applicability",
        )
    }
    justification = st.text_area("Credibility justification")
    save_evidence = st.form_submit_button("Save evidence review")
if save_evidence:
    link_id = _identifier("LINK", reviewer, claim_id, evidence_id)
    link = ClaimEvidenceLink(
        link_id=link_id,
        claim_id=claim_id,
        evidence_id=evidence_id,
        relationship=relationship,
        applicability_reason=applicability_reason,
        target_match=target,
        scope_match=scope,
        condition_match=condition,
        temporal_match=temporal,
        reviewer=reviewer,
        review_status="complete",
    )
    credibility = CredibilityAssessment(
        assessment_id=_identifier("CRED", link_id),
        link_id=link_id,
        evidence_mode=mode,
        reviewer_justification=justification,
        **dimensions,
    )
    with connect(DATABASE_PATH) as connection:
        save_link(connection, link)
        save_credibility(connection, credibility)
    st.success("Independent evidence review saved.")

st.subheader("Reviewer's claim-level judgement")
with st.form("human_outcome"):
    outcome = st.selectbox("Four-way outcome", [item.value for item in ClaimOutcome])
    confidence = st.selectbox("Uncertainty / confidence", [item.value for item in ConfidenceLevel])
    uncertainty = st.text_area("Uncertainty explanation")
    explanation = st.text_area("Reviewer explanation")
    complete = st.form_submit_button("Complete blind human assessment")
if complete:
    assessment = ClaimAssessment(
        assessment_id=_identifier("HUMAN", reviewer, claim_id),
        claim_id=claim_id,
        reviewer=reviewer,
        outcome=outcome,
        confidence=confidence,
        uncertainty_explanation=uncertainty,
        explanation=explanation,
        review_status="complete",
    )
    with connect(DATABASE_PATH) as connection:
        save_claim_assessment(connection, assessment, [])
    st.success("Blind claim assessment complete. Automated results remain hidden here.")
