"""Saif retrieval -> interpretation -> graph credibility assessment."""

from datetime import date

import pandas as pd
import streamlit as st

from decidr.config import PHASE1_DATA_DIR, PHASE2_DATA_DIR
from decidr.corpus_assessment import AssessmentStore, assess_claim

st.set_page_config(page_title="End-to-End Claim Assessment", layout="wide")
st.title("End-to-End Claim Assessment")
st.caption(
    "Saif's structured retrieval engine proposes relevant evidence. Numeric comparison, "
    "authority checking and graph credibility assessment run afterwards as separate stages."
)
st.warning(
    "Retrieval rank is not credibility. Automated outcomes are candidates and require two "
    "independent reviews or adjudication before becoming final findings."
)


@st.cache_resource
def store() -> AssessmentStore:
    return AssessmentStore()


database = store()
counts = database.counts()
metric_columns = st.columns(4)
metric_columns[0].metric("Corpus sources", counts["sources"])
metric_columns[1].metric("Evidence units", counts["evidence"])
metric_columns[2].metric("Saved assessments", counts["assessments"])
metric_columns[3].metric("Human reviews", counts["reviews"])

with st.expander("Configured corpus", expanded=not counts["evidence"]):
    st.code(f"Phase 1: {PHASE1_DATA_DIR}\nPhase 2: {PHASE2_DATA_DIR}")
    st.write(
        "The client corpus remains outside the repository and is read locally. Ingestion "
        "preserves source provenance, structured row metadata and evidence locators."
    )
    if st.button(
        "Ingest or refresh configured corpus",
        type="primary" if not counts["evidence"] else "secondary",
    ):
        with st.spinner("Reading the configured corpus and refreshing the evidence ledger..."):
            ingestion = database.ingest_configured_corpus()
        st.success(
            f"Ingested {len(ingestion.sources)} sources and "
            f"{len(ingestion.evidence)} evidence units."
        )
        if ingestion.warnings:
            for warning in ingestion.warnings:
                st.warning(warning)
        st.rerun()

if not counts["evidence"]:
    st.info("Ingest the configured corpus before running a claim assessment.")
    st.stop()

st.subheader("Assess an atomic claim")
claim = st.text_area(
    "Exact claim",
    value=(
        "New-business discounts of 15 percent or greater require written approval from "
        "the Head of Finance and People Ops before Closed Won."
    ),
    height=100,
)
left, middle, right, action = st.columns([1, 1, 1.2, 2])
as_of = left.date_input("Assessment date", value=date(2026, 7, 31))
limit = middle.slider("Evidence limit", min_value=3, max_value=20, value=8)
semantic = right.checkbox(
    "Use local semantic retrieval",
    value=False,
    help="If the local sentence-transformer model is unavailable, retrieval safely falls back.",
)
run = action.button("Retrieve, interpret and assess", type="primary", use_container_width=True)

if run:
    st.session_state["corpus_assessment"] = assess_claim(
        database,
        claim,
        as_of=as_of,
        limit=limit,
        semantic=semantic,
        persist=True,
    )

result = st.session_state.get("corpus_assessment")
if result:
    st.divider()
    st.subheader("Automated candidate result")
    outcome, confidence, formal, observed = st.columns(4)
    outcome.metric("Combined outcome", result["automated_outcome"])
    confidence.metric("Confidence", result["automated_confidence"])
    formal.metric("Formal lane", result["formal_outcome"])
    observed.metric("Observed lane", result["observed_outcome"])
    st.info(result["summary"])
    st.caption(f"Assessment ID: {result['assessment_id']}")

    retrieval = result["retrieval"]
    retrieval_metrics = st.columns(4)
    retrieval_metrics[0].metric("Candidates searched", retrieval["candidate_count"])
    retrieval_metrics[1].metric("Unique sources", retrieval["unique_sources"])
    retrieval_metrics[2].metric(
        "Provenance groups",
        retrieval["distinct_provenance_groups"],
    )
    retrieval_metrics[3].metric(
        "Duplicates collapsed",
        retrieval["duplicate_results_collapsed"],
    )
    if retrieval["gap_signals"]:
        st.warning("Retrieval diagnostics: " + ", ".join(retrieval["gap_signals"]))
    st.caption(f"Semantic retrieval status: {retrieval['semantic_status']}")

    interpretation_tab, credibility_tab, citations_tab, audit_tab = st.tabs(
        ["Interpretations", "Credibility trace", "Citations", "Audit package"]
    )
    with interpretation_tab:
        rows = []
        for item in result["interpretations"]:
            claim_condition = item.get("claim_condition") or {}
            evidence_condition = item.get("evidence_condition") or {}
            rows.append(
                {
                    "relationship": item["relationship"],
                    "mode": item["mode"],
                    "confidence": item["confidence"],
                    "claim threshold": (
                        f"{claim_condition.get('operator', '')} "
                        f"{claim_condition.get('value', '')}%"
                        if claim_condition
                        else ""
                    ),
                    "evidence value": (
                        f"{evidence_condition.get('value', '')}%" if evidence_condition else ""
                    ),
                    "comparison": item.get("comparison_result"),
                    "rationale": item["rationale"],
                }
            )
        st.table(pd.DataFrame(rows))

    with credibility_tab:
        credibility_rows = [
            {
                "source": item["document_title"],
                "mode": item["mode"],
                "stance": item["stance"],
                "applicable": item["applicable"],
                "material": item["material"],
                "materiality score": item["materiality_score"],
                **item["dimensions"],
            }
            for item in result["credibility"]["evidence"]
        ]
        st.table(pd.DataFrame(credibility_rows))
        with st.expander("Rules and limitations", expanded=True):
            st.markdown("**Rules applied**")
            for rule in result["rules_applied"]:
                st.code(rule)
            st.markdown("**Limitations**")
            for limitation in result["limitations"]:
                st.write(f"- {limitation}")

    with citations_tab:
        for index, (candidate, interpretation) in enumerate(
            zip(retrieval["results"], result["interpretations"], strict=True),
            start=1,
        ):
            with st.expander(
                f"#{index} {candidate['source_title']} — {interpretation['relationship'].upper()}",
                expanded=index <= 3,
            ):
                st.code(
                    f"{candidate['source_id']} | {candidate['locator']} | "
                    f"{candidate['row_identifier'] or 'no row identifier'}"
                )
                st.write(candidate["text"])
                st.caption(
                    f"Lexical rank: {candidate['lexical_rank']} | "
                    f"Semantic rank: {candidate['semantic_rank']} | "
                    f"Temporal status: {candidate['temporal_status']} | "
                    f"Provenance group: {candidate['provenance_group']}"
                )
                if candidate["missing_fields"]:
                    st.warning(
                        "Missing structured fields: " + ", ".join(candidate["missing_fields"])
                    )

    with audit_tab:
        st.json(result)
