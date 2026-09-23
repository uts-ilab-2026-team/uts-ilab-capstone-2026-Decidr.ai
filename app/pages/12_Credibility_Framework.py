"""Read-only inspection of the transparent credibility framework."""

import pandas as pd
import streamlit as st

from decidr.config import DATABASE_PATH, PROJ_ROOT
from decidr.credibility import (
    CREDIBILITY_DIMENSIONS,
    CREDIBILITY_QUESTIONS,
    CredibilityFramework,
)
from decidr.database import connect
from decidr.models import ClaimEvidenceLink, CredibilityAssessment
from decidr.ui import require_database

st.title("Credibility Framework")
require_database()

framework = CredibilityFramework.from_json(PROJ_ROOT / "configs" / "reasoning.json")
st.write(
    "The framework first checks applicability, then evaluates seven credibility dimensions. "
    "The result is a materiality score for an evidence item, not a probability that a claim "
    "is true."
)
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
    width="stretch",
    hide_index=True,
)
st.caption(
    f"Materiality threshold: {framework.config.materiality_threshold:.2f}. "
    "Outcome and confidence are calculated separately at claim level."
)

with connect(DATABASE_PATH) as connection:
    rows = connection.execute(
        """
        SELECT l.payload_json, c.payload_json, e.text_content, e.locator
        FROM claim_evidence_links l
        JOIN credibility_assessments c ON c.link_id=l.link_id
        JOIN evidence e ON e.evidence_id=l.evidence_id
        ORDER BY l.claim_id, l.reviewer, l.evidence_id
        """
    ).fetchall()

if not rows:
    st.info("No completed evidence credibility reviews are available yet.")
    st.stop()

reviews = []
for link_json, credibility_json, text, locator in rows:
    link = ClaimEvidenceLink.model_validate_json(link_json)
    credibility = CredibilityAssessment.model_validate_json(credibility_json)
    reviews.append((link, credibility, text, locator))

selected_index = st.selectbox(
    "Reviewed evidence item",
    range(len(reviews)),
    format_func=lambda index: (
        f"{reviews[index][0].claim_id} - {reviews[index][0].evidence_id} - "
        f"{reviews[index][0].reviewer}"
    ),
)
link, credibility, evidence_text, locator = reviews[selected_index]
decision = framework.evaluate_evidence(link, credibility)

applicability_column, materiality_column, threshold_column = st.columns(3)
applicability_column.metric("Applicable", "Yes" if decision["applicable"] else "No")
materiality_column.metric(
    "Materiality score",
    (
        f"{decision['materiality_score']:.3f}"
        if decision["materiality_score"] is not None
        else "Not scored"
    ),
)
threshold_column.metric("Material", "Yes" if decision["material"] else "No")

st.write(decision["explanation"])
if decision["failed_applicability_checks"]:
    st.warning(
        "Failed checks: "
        + ", ".join(name.replace("_", " ") for name in decision["failed_applicability_checks"])
    )
if decision["dimension_breakdown"]:
    st.dataframe(
        pd.DataFrame(decision["dimension_breakdown"]),
        width="stretch",
        hide_index=True,
    )

with st.expander("Evidence and reviewer reasoning"):
    st.caption(locator)
    st.text(evidence_text)
    st.write(credibility.reviewer_justification)
