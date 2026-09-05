"""Experimental Approach B conversational assessment interface."""

import json

import pandas as pd
import streamlit as st

from decidr.approach_b import ConstrainedClaimParser, load_profile, run_approach_b
from decidr.config import DATABASE_PATH, PROJ_ROOT
from decidr.database import connect
from decidr.models import AtomicClaim, EvidenceTarget


st.title("Approach B — Graph and LLM Assistant")
st.error("TEST MODE — experimental outputs are not human reference assessments.")
st.caption(
    "This page is separate from blind Human Review. Model suggestions are never written to "
    "human reference tables and the deterministic outcome cannot be overridden by an LLM."
)

profile = load_profile(PROJ_ROOT / "configs" / "approach_b_graph_llm.yaml")
ingestion = (PROJ_ROOT / "reports" / "ingestion" / "ingestion_report.md").read_text()
fingerprint = ingestion.split("Dataset fingerprint: `", 1)[1].split("`", 1)[0]

query = st.chat_input("Ask an organisational knowledge question")
if query:
    st.session_state.approach_b_query = query
    st.session_state.approach_b_proposal = ConstrainedClaimParser().parse_proposal(query)

proposal = st.session_state.get("approach_b_proposal")
if proposal:
    st.subheader("Proposed interpretation")
    if len(proposal.claims) > 1:
        st.warning(f"The question contains {len(proposal.claims)} propositions and was split.")
    if proposal.ambiguities:
        st.warning("Ambiguities: " + "; ".join(proposal.ambiguities))
        st.info(proposal.clarification)
    claim_number = st.selectbox(
        "Atomic proposition", range(len(proposal.claims)),
        format_func=lambda index: proposal.claims[index].claim_text,
    )
    proposed = proposal.claims[claim_number]
    with st.form("confirm_claim"):
        claim_text = st.text_area("Claim wording", proposed.claim_text)
        subject = st.text_input("Subject", proposed.subject)
        predicate = st.text_input("Predicate", proposed.predicate)
        target = st.text_input("Target/object", proposed.object)
        scope = st.text_input("Scope", proposed.scope or "")
        conditions = st.text_area("Conditions, one per line", "\n".join(proposed.conditions))
        start = st.text_input("Applicable start (YYYY-MM-DD; blank if unknown)")
        end = st.text_input("Applicable end (YYYY-MM-DD; blank if ongoing/unknown)")
        evidence_target = st.selectbox(
            "Evidence target", [item.value for item in EvidenceTarget],
            index=list(EvidenceTarget).index(proposed.evidence_target) if proposed.evidence_target else 0,
        )
        confirmed = st.form_submit_button("Confirm interpretation and assess")
    if confirmed:
        claim = AtomicClaim(
            claim_id=proposed.claim_id, subject=subject, predicate=predicate, object=target,
            process=proposed.process, scope=scope or None,
            conditions=[line.strip() for line in conditions.splitlines() if line.strip()],
            applicable_start_date=start or None, applicable_end_date=end or None,
            claim_type=proposed.claim_type, evidence_target=evidence_target,
            claim_text=claim_text, atomicity_status="user_confirmed",
        )
        with connect(DATABASE_PATH) as connection:
            result = run_approach_b(
                connection, st.session_state.approach_b_query, claim, profile, fingerprint
            )
        st.session_state.approach_b_result = result

result = st.session_state.get("approach_b_result")
if result:
    st.chat_message("assistant").markdown(result.explanation)
    st.subheader("Interpreted atomic claim")
    st.json(result.structured_claim.model_dump(mode="json"))
    left, right = st.columns(2)
    left.metric("Deterministic outcome", result.outcome.value)
    right.metric("Confidence", result.confidence.value)
    st.subheader("Material gaps")
    st.write(result.evidence_gaps)
    st.subheader("Applied rules")
    st.dataframe(pd.DataFrame(result.rules_applied), hide_index=True)
    st.subheader("Citations with exact locators")
    st.dataframe(pd.DataFrame(result.citations), hide_index=True)
    with st.expander("Model suggestions — not human validated"):
        suggestions = result.qualifying_evidence + result.contextual_evidence
        st.dataframe(pd.DataFrame(suggestions), hide_index=True)
    with st.expander("Retrieval-method details"):
        st.json(result.runtime_metadata)
    with st.expander("Evidence graph"):
        st.info("Bounded depth-1 expansion reasons are retained in the assessment package.")
