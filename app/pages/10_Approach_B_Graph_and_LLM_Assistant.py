"""Self-contained employee knowledge assistant."""

from datetime import date

import streamlit as st

from decidr.approach_b import (
    load_profile, proposition_polarity, run_approach_b,
)
from decidr.config import DATABASE_PATH, PROJ_ROOT
from decidr.database import connect
from decidr.evidence_b import employee_evidence, excluded_summary, gap_summary
from decidr.models import AtomicClaim, EvidenceTarget
from decidr.interpretation_v1 import InterpretationItem, InterpreterConfig, OllamaInterpreter, clarification_once
from decidr.employee_print import PRINT_CSS, employee_print_html

st.html("<style>" + PRINT_CSS + "</style>")
st.title("Employee knowledge assistant")
st.caption(
    "Ask about a company policy, process or observed practice. Answers use only the supplied corpus."
)
st.warning(
    "Experimental decision support — verify consequential actions with the cited process owner."
)

profile = load_profile(PROJ_ROOT / "configs" / "approach_b_graph_llm.yaml")
# Preserve the previous confirmation UI during development; it must not convert
# interpretation-1.3 query frames into pre-retrieval factual claims.
legacy_settings = {**profile.get("interpreter", {}), "enabled": False,
                   "prompt_version": "interpretation-1.0", "schema_version": "interpretation-1.0"}
legacy_settings.pop("alignment_threshold", None)
interpreter_config = InterpreterConfig.model_validate(legacy_settings)
st.info("Query-frame interpretation 1.3 is in development and has not been promoted to this UI. Deterministic interpretation remains available.")
interpreter = OllamaInterpreter(interpreter_config)


@st.cache_data(ttl=30)
def local_available(config_json: str) -> bool:
    return OllamaInterpreter(InterpreterConfig.model_validate_json(config_json)).available()


if local_available(interpreter_config.model_dump_json()):
    st.success("Local Llama 3.2 interpretation available")
else:
    st.info("Local interpretation unavailable or disabled — deterministic fallback available.")

report = PROJ_ROOT / "reports" / "ingestion" / "ingestion_report.md"
fingerprint = "unavailable"
if report.exists():
    text = report.read_text(encoding="utf-8")
    if "Dataset fingerprint: `" in text:
        fingerprint = text.split("Dataset fingerprint: `", 1)[1].split("`", 1)[0]

state = st.session_state
state.setdefault("approach_b_messages", [])
state.setdefault("approach_b_stage", "question")


def interpret(question: str) -> None:
    result = clarification_once(
        interpreter.interpret(question), state.setdefault("approach_b_asked_clarifications", set())
    )
    state.approach_b_proposal = result.proposal
    state.approach_b_interpretation = result.interpretation
    state.approach_b_technical_provenance = result.provenance
    state.approach_b_stage = "clarify" if result.proposal.clarification else "confirm"


def ask(question: str) -> None:
    state.approach_b_messages.append({"role": "user", "content": question})
    state.approach_b_query = question
    state.approach_b_asked_clarifications = set()
    state.approach_b_confirmed_items = {}
    interpret(question)
    state.pop("approach_b_result", None)


def evidence_group(heading: str, items: list[dict], empty: str) -> None:
    st.markdown(f"#### {heading}")
    if not items:
        st.caption(empty)
    for item in items:
        with st.container(border=True):
            st.markdown(
                f"**{item['source_title']}** — `{item['evidence_id']}` / `{item['source_id']}`"
            )
            st.markdown(f"**{item['excerpt']}**")
            if item.get("practice_status") == "divergence":
                st.caption(
                    "Possible policy-practice divergence; does not contradict the formal rule."
                )
            with st.expander("View source details"):
                st.write(f"Location: {item['locator']}")
                st.write(f"Relationship: {item['relationship']}")
                st.write(item["assessment_influence"])


for message in state.approach_b_messages:
    with st.chat_message(message["role"]):
        st.write(message["content"])

if state.approach_b_stage == "question":
    st.write("Try an example:")
    examples = [
        "Do I need approval for a 15% new-business discount?",
        "Can sales employees approve a 20% new-business discount without a manager?",
        "Was the emergency billing deployment approved before release?",
    ]
    columns = st.columns(3)
    for column, example in zip(columns, examples, strict=True):
        if column.button(example, width="stretch"):
            ask(example)
            st.rerun()

question = st.chat_input("Ask a question about a company policy, process or observed practice")
if question:
    if state.approach_b_stage == "clarify":
        combined = f"{state.approach_b_query} Clarification: {question}"
        state.approach_b_messages.append({"role": "user", "content": question})
        state.approach_b_query = combined
        interpret(combined)
    else:
        ask(question)
    st.rerun()

proposal = state.get("approach_b_proposal")
if proposal and state.approach_b_stage in {"clarify", "confirm"}:
    with st.chat_message("assistant"):
        if proposal.clarification:
            st.write(proposal.clarification)
            st.caption(
                "I will not assess until the material ambiguity is resolved and you confirm the claim."
            )
        elif proposal.claims:
            st.write(f"I propose: **{proposal.claims[0].claim_text}**")

    if proposal.claims:
        st.subheader("Proposed interpretation")
        technical = state.get("approach_b_technical_provenance", {})
        st.caption(f"Interpretation source: {proposal.interpretation_source}. {technical.get('status', '')}")
        structured = state.get("approach_b_interpretation")
        if structured:
            with st.expander("All atomic items and extracted constraints"):
                st.json(structured.model_dump())
        st.caption("Confirm and assess each atomic item separately. Edit unresolved fields below.")

        selected = st.selectbox(
            "Atomic item to confirm",
            range(len(proposal.claims)),
            format_func=lambda index: proposal.claims[index].claim_text,
        )
        proposed = proposal.claims[selected]
        if proposal.candidates:
            matching = next(
                (item for item in proposal.candidates if item.claim.claim_id == proposed.claim_id),
                None,
            )
            if matching:
                st.caption("Match reasons: " + "; ".join(matching.match_reasons))
        with (
            st.expander("Structured interpretation", expanded=True),
            st.form("confirm_claim"),
        ):
            interpreted_item = structured.items[selected] if structured else None
            if interpreted_item:
                properties = InterpretationItem.model_json_schema()["properties"]
                intents = properties["intent"]["enum"]
                fields = properties["requested_field"]["enum"]
                intent = st.selectbox("Question intent", intents, index=intents.index(interpreted_item.intent))
                requested_field = st.selectbox("Requested field", fields, index=fields.index(interpreted_item.requested_field))
                modality = st.text_input("Modality", interpreted_item.modality or "")
                polarity = st.selectbox("Polarity", ["positive", "negative", "unknown"],
                                       index=["positive", "negative", "unknown"].index(interpreted_item.polarity))
                st.caption("Numeric and temporal constraints are included in Conditions below; preserve them when editing.")
            claim_text = st.text_area("Claim wording", proposed.claim_text)
            subject = st.text_input("Subject", proposed.subject)
            predicate = st.text_input("Predicate", proposed.predicate)
            target = st.text_input("Target/object", proposed.object)
            process = st.text_input("Process", proposed.process or "")
            scope = st.text_input("Organisational scope", proposed.scope or "")
            conditions = st.text_area("Conditions (one per line)", "\n".join(proposed.conditions))
            left, right = st.columns(2)
            start = left.date_input(
                "Applicable start",
                value=proposed.applicable_start_date,
                min_value=date(2000, 1, 1),
            )
            end = right.date_input(
                "Applicable end", value=proposed.applicable_end_date, min_value=date(2000, 1, 1)
            )
            target_options = list(EvidenceTarget)
            evidence_target = st.selectbox(
                "Evidence target",
                target_options,
                index=target_options.index(proposed.evidence_target)
                if proposed.evidence_target
                else 0,
                format_func=lambda value: value.value,
            )
            st.caption(f"Interpretation source: {proposal.interpretation_source}")
            resolved = st.checkbox(
                "I have resolved the missing fields in my edits",
                value=not proposal.requires_clarification,
            )
            confirmed = st.form_submit_button("Confirm and assess", type="primary")
        cancel = st.button("Cancel and ask another question")
        if cancel:
            state.approach_b_stage = "question"
            state.pop("approach_b_proposal", None)
            st.rerun()
        if confirmed and not resolved:
            st.error("Resolve the missing material fields and confirm your edits before assessment.")
        if confirmed and resolved:
            claim = AtomicClaim(
                claim_id=proposed.claim_id,
                subject=subject,
                predicate=predicate,
                object=target,
                process=process or None,
                scope=scope or None,
                conditions=[line.strip() for line in conditions.splitlines() if line.strip()],
                applicable_start_date=start,
                applicable_end_date=end,
                claim_type=intent if interpreted_item else proposed.claim_type,
                evidence_target=evidence_target,
                claim_text=claim_text,
                proposition_polarity="negative" if interpreted_item and polarity == "negative" else proposition_polarity(claim_text),
                atomicity_status="user_confirmed",
                original_claim_text=state.approach_b_query,
            )
            if interpreted_item:
                state.approach_b_confirmed_interpretation = {
                    **interpreted_item.model_dump(), "intent": intent,
                    "requested_field": requested_field, "modality": modality or None,
                    "polarity": polarity, "subject": subject, "predicate": predicate,
                    "object": target, "process": process or None, "scope": scope or None,
                    "conditions": claim.conditions, "assessment_target": evidence_target.value,
                    "confirmed_wording": claim_text,

                }
            with connect(DATABASE_PATH) as connection:
                state.approach_b_result = run_approach_b(
                    connection,
                    state.approach_b_query,
                    claim,
                    profile,
                    fingerprint,
                    ambiguities=list(proposal.ambiguities),
                    interpretation_method=proposal.interpretation_source,
                )
            state.approach_b_confirmed_items = {
                **state.get("approach_b_confirmed_items", {}),
                proposed.claim_id: state.approach_b_result,
            }
            state.approach_b_stage = "result"
            st.rerun()

result = state.get("approach_b_result")
if result and result.runtime_metadata.get("active_modelling_release") != "phase2":
    state.pop("approach_b_result", None)
    state.approach_b_stage = "question"
    st.info("The active corpus is now Phase 2 only. Please assess your question again.")
    result = None
if result and state.approach_b_stage == "result":
    st.html(employee_print_html(result))
    with st.chat_message("assistant"):
        st.subheader("1. Answer")
        left, right = st.columns(2)
        left.metric("Verdict", result.outcome.value)
        right.metric("Confidence", result.confidence.value)
        st.write(result.safe_employee_guidance)
        st.caption(
            "The deterministic reasoner assessed eligible, temporally applicable evidence; dependent copies do not count as corroboration."
        )
        st.subheader("2. Evidence and reasoning")
        primary, additional = employee_evidence(result)
        evidence_group("Decisive evidence", primary, "No decisive evidence available.")
        st.write(gap_summary(result.evidence_gaps))
        for note in result.policy_practice_divergence:
            st.info(note)
        if result.divergence_evidence:
            evidence_group("Observed practice — separate from the policy verdict",
                           result.divergence_evidence[:1], "")
            visible_ids = {item["evidence_id"] for item in result.divergence_evidence[:1]}
            additional = [item for item in additional if item["evidence_id"] not in visible_ids]
        if result.dependency_duplication_notes:
            st.caption("Equivalent duplicate copy omitted.")
        with st.expander(f"Additional eligible evidence ({len(additional)})"):
            evidence_group("Additional evidence", additional, "No additional eligible evidence.")
        with st.expander(
            f"Excluded evidence with reasons ({len(result.not_applicable_evidence)})"
        ):
            st.caption(
                "Exclusion is distinct from missing evidence or organisational non-compliance."
            )
            counts, examples = excluded_summary(result.not_applicable_evidence)
            st.caption("A record can fail more than one check.")
            for reason, count in counts.items():
                st.write(f"{reason.replace('_', ' ').title()}: {count}")
            with st.expander(f"Optional excluded examples ({len(examples)})"):
                evidence_group("Excluded examples", examples, "No exclusions.")

        st.subheader("3. Recommended next action")
        st.write(result.recommended_organisational_action)
        if result.responsible_role:
            label = (
                "Responsible role identified in the cited policy"
                if result.responsible_role_basis == "cited policy text" else "Responsible contact"
            )
            st.caption(f"{label}: {result.responsible_role}")

    with st.expander("Graph and provenance"):
        st.write(
            "The graph expanded only explicit lineage, derivation, supersession and duplicate relationships. It did not decide the verdict."
        )
        st.json(result.assessment_provenance)
    proposal = state.get("approach_b_proposal")
    if proposal and len(proposal.claims) > 1:
        completed = state.get("approach_b_confirmed_items", {})
        st.caption(f"{len(completed)} of {len(proposal.claims)} atomic items assessed.")
        if st.button("Confirm or review another atomic item"):
            state.approach_b_stage = "confirm"
            st.rerun()
    with st.expander("Advanced technical details"):
        st.json(state.get("approach_b_technical_provenance", {}))
        st.download_button(
            "Download technical audit (JSON)",
            result.model_dump_json(indent=2),
            file_name="approach_b_audit.json",
            mime="application/json",
        )
        st.json(
            {
                "components": result.retrieval_component_status,
                "latency_ms": result.runtime_metadata.get("latency_ms"),
                "deterministic_rule_trace": result.rules_applied,
            }
        )
    if st.button("Ask another question", type="primary"):
        state.approach_b_stage = "question"
        state.pop("approach_b_proposal", None)
        state.pop("approach_b_result", None)
        st.rerun()
