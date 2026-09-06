"""Approach A post-review deterministic baseline assessment."""

import hashlib

import streamlit as st

from decidr.approach_a import load_profile, run_approach_a
from decidr.config import DATABASE_PATH, PROJ_ROOT
from decidr.database import connect, save_claim_assessment
from decidr.models import AtomicClaim, ClaimAssessment
from decidr.reasoning import load_reasoning_config


def _corpus_fingerprint() -> str:
    """Read the ingestion fingerprint without making the baseline depend on the report."""
    report_path = PROJ_ROOT / "reports" / "ingestion" / "ingestion_report.md"
    if not report_path.is_file():
        return "unknown:no-ingestion-report"
    report = report_path.read_text(encoding="utf-8")
    marker = "Dataset fingerprint: `"
    if marker not in report:
        return "unknown:not-recorded"
    return report.split(marker, 1)[1].split("`", 1)[0]


st.title("Approach A — Deterministic Baseline Assessment")
st.info(
    "No LLM, embedding model, graph expansion, reranking, or automatic relationship "
    "classification is used. The baseline combines FTS5/BM25 retrieval, completed human "
    "reviews, and transparent deterministic rules."
)
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
        connection.execute(
            "SELECT payload_json FROM claims WHERE claim_id=?", (claim_id,)
        ).fetchone()[0]
    )

st.caption(f"Using completed human relationship judgements from: {reviewer}")
gaps_text = st.text_area("Expected evidence gaps (one per line)")
if st.button("Run Approach A baseline"):
    profile = load_profile(PROJ_ROOT / "configs" / "approach_a_baseline.yaml")
    reasoning_config = load_reasoning_config(PROJ_ROOT / "configs" / "reasoning.json")
    with connect(DATABASE_PATH) as connection:
        result = run_approach_a(
            connection,
            claim.claim_text,
            claim,
            reviewer,
            profile,
            _corpus_fingerprint(),
            reasoning_config=reasoning_config,
            expected_evidence_gaps=[
                line.strip() for line in gaps_text.splitlines() if line.strip()
            ],
        )
        assessment_id = "AUTO-A-" + hashlib.sha256(
            f"{claim_id}\0{reviewer}".encode()
        ).hexdigest()[:16]
        assessment = ClaimAssessment(
            assessment_id=assessment_id,
            claim_id=claim_id,
            reviewer=f"automated:approach-a:{reviewer}",
            outcome=result.outcome,
            confidence=result.confidence,
            uncertainty_explanation=(
                "Confidence follows decisive independent evidence and recorded gaps."
            ),
            explanation=result.explanation,
            review_status="complete",
        )
        save_claim_assessment(connection, assessment, result.rules_applied)

    left, right = st.columns(2)
    left.metric("Outcome", result.outcome.value)
    right.metric("Separate confidence", result.confidence.value)
    st.markdown(result.explanation)
    st.download_button(
        "Download assessment Markdown",
        result.explanation,
        f"{claim_id}-approach-a-assessment.md",
    )
    with st.expander("Baseline retrieval and reproducibility details"):
        st.json(result.runtime_metadata)

reviewer_counts: dict[str, int] = {}
for row in completed:
    reviewer_counts[row[0]] = reviewer_counts.get(row[0], 0) + 1
if reviewer_counts.get(claim_id, 0) < 2:
    st.warning(
        "Reference assessment incomplete: fewer than two independent reviewers are complete."
    )
