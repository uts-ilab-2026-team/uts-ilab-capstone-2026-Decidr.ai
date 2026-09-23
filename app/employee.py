"""Employee and local reviewer interface for the bounded claim-first workflow."""

import json
import sqlite3
from urllib.parse import urlencode

import streamlit as st

from decidr.claim_export import claim_report_html
from decidr.claim_graph import review_graph, source_neighbourhood
from decidr.claim_workflow import (
    DIMENSIONS,
    clarify_claim,
    ensure_system_assessment,
    entries,
    evidence_catalog,
    get_entry,
    get_run,
    knowledge_risks,
    reassess_evidence,
    refresh_system_assessment,
    review_interpretation,
    review_notes,
    runs,
    search_evidence,
    sensitivity,
)
from decidr.config import DATABASE_PATH
from decidr.conversation import (
    conversations,
    create_conversation,
    messages,
    reopen_claim,
    send_message,
    sync_assessments,
)
from decidr.database import connect
from decidr.graph import to_graphviz
from decidr.models import AtomicClaim, EvidenceMode, EvidenceRelationship

TARGET_LABELS = {
    "All relevant evidence": None,
    "Prescribed rule": "prescribed_rule",
    "Actual practice": "actual_practice",
    "Recorded state": "recorded_state",
}
STATUS_LABELS = {
    "awaiting_clarification": "Awaiting clarification or interpretation review",
    "awaiting_evidence_review": "Awaiting evidence review",
    "completed_assessment": "Completed assessment",
}


def evidence_card(item, *, label=None, note=None, expanded=False, run_id=None):
    locator = item["locator"].split(" > ")[-1].split("#block:")[0]
    with st.expander(label or f"{item['source']['title']} · {locator}", expanded=expanded):
        st.caption(f"{item['evidence_id']} · {item['source_id']} · {item['locator']}")
        st.text(item["text"])
        if note:
            st.caption(note["link"]["applicability_reason"])
        params = {"source": item["source_id"], "evidence": item["evidence_id"]}
        if run_id:
            params["assessment"] = run_id
        if st.query_params.get("conversation"):
            params["conversation"] = st.query_params["conversation"]
        st.link_button("Open source", "?" + urlencode(params))
        st.caption(
            f"Source type: {item['source']['source_type']} · Lifecycle: {item['source']['lifecycle_status']}"
        )
        st.write(
            {
                key: item["source"][key]
                for key in ("creation_date", "effective_start_date", "effective_end_date")
            }
        )
        if item["evidence"].get("relevant_start_date") or item["evidence"].get(
            "relevant_end_date"
        ):
            st.caption(
                f"Recorded event period: {item['evidence'].get('relevant_start_date')} to {item['evidence'].get('relevant_end_date')}"
            )
        with st.expander("Source and extraction provenance"):
            for context in item.get("source_context", []):
                st.caption(context["locator"])
                st.text(context["text"])
            st.json(item)


def source_page(source_id):
    """Open ledger source excerpts through an HTTP page, including for local files."""
    if st.button("Return to claim assessment"):
        for key in ("source", "evidence", "assessment"):
            if key in st.query_params:
                del st.query_params[key]
        st.rerun()
    if run_id := st.query_params.get("assessment"):
        try:
            with connect(DATABASE_PATH) as connection:
                run = get_run(connection, run_id)
            records = [r for r in run["result"]["evidence_records"] if r["source_id"] == source_id]
            if not records:
                source = run.get("source_graph", {}).get(source_id)
                if source:
                    st.title(source["title"])
                    st.caption("Frozen source metadata from assessment " + run_id)
                    st.info(
                        "No excerpt from this provenance source was captured in this assessment."
                    )
                    st.json(source)
                else:
                    st.error("This source is not linked to the selected assessment.")
                return
            st.title(records[0]["source"]["title"])
            st.caption("Frozen source excerpts from assessment " + run_id)
            seen = set()
            for record in records:
                for excerpt in [record, *record.get("source_context", [])]:
                    if excerpt["evidence_id"] in seen:
                        continue
                    seen.add(excerpt["evidence_id"])
                    if st.query_params.get("evidence") == excerpt["evidence_id"]:
                        st.info("Selected assessment excerpt")
                    st.subheader(excerpt["locator"])
                    st.text(excerpt["text"])
            with st.expander("Source provenance"):
                st.json(records[0]["source"])
            return
        except ValueError as error:
            st.error(str(error))
            return
    with connect(DATABASE_PATH) as connection:
        records = [
            item
            for item in evidence_catalog(connection).values()
            if item["source"]["source_id"] == source_id
        ]
    if not records:
        st.error(
            "This source is no longer available in the eligible evidence ledger. Use Evidence Explorer to find a current source, or ask the ledger maintainer to restore it."
        )
        return
    source = records[0]["source"]
    st.title(source["title"])
    st.caption(source_id + " · " + source["original_file_path"])
    with st.expander("Source provenance"):
        st.json(source)
    for record in records:
        if st.query_params.get("evidence") == record["evidence"]["evidence_id"]:
            st.info("Selected graph excerpt")
        st.subheader(record["evidence"]["locator"])
        st.text(record["evidence"]["text"])


def result_view(run, *, historical=False):
    """Chat and register render the same frozen assessment and cited findings."""
    from decidr.assessment_snapshot import presentation
    from decidr.automatic_evidence import VERSION

    result = run["result"]
    view = presentation(result)
    records = {r["evidence_id"]: r for r in result["evidence_records"]}
    findings = {f["finding_id"]: f for f in view["findings"]}
    version = run.get("receipt", {}).get("classifier_version")
    historical = historical or not result.get("presentation") or (version and version != VERSION)
    st.caption(
        (
            "Historical result · saved verdict retained"
            if historical
            else "Latest assessed result · frozen snapshot"
        )
        + " · "
        + run["run_id"]
    )
    if result.get("assessed_at"):
        st.caption("Created " + result["assessed_at"])
    st.write(result["claim"]["claim_text"])
    cols = st.columns(2)
    cols[0].metric(
        "Verdict",
        "Insufficient" if result["outcome"] == "Insufficient evidence" else result["outcome"],
    )
    cols[1].metric("Confidence", result["confidence"])
    st.write(result["explanation"])
    st.caption(
        f"Assessment as of {result['as_of']} · Relevant period {result['assessed_period']['start']} to {result['assessed_period']['end']}"
    )
    st.caption("Review status: " + result.get("review_status", "Human reviewed"))
    st.caption("Scope: " + str(result["claim"].get("scope") or "As stated in the claim"))
    for finding in result.get("target_findings", {}).values():
        st.write(f"{finding['title']}: {finding['outcome']}")

    def finding_card(fid, expanded=False):
        finding = findings[fid]
        eid = finding["evidence_id"]
        record = records[eid]
        label = f"{record['source']['title']} · {finding['assessment_target'].replace('_', ' ')} · {finding['relationship'] or 'unclassified'}"
        note = {"link": {"applicability_reason": finding["reason"]}}
        evidence_card(record, label=label, note=note, expanded=expanded, run_id=run["run_id"])

    def citation(fid):
        finding = findings[fid]
        record = records[finding["evidence_id"]]
        params = {
            "source": record["source_id"],
            "evidence": record["evidence_id"],
            "assessment": run["run_id"],
        }
        if st.query_params.get("conversation"):
            params["conversation"] = st.query_params["conversation"]
        st.markdown(
            f"[{record['source']['title']} · {finding['assessment_target'].replace('_', ' ')} · {finding['relationship'] or 'unclassified'}](?{urlencode(params)})"
        )

    for section in view["sections"]:
        st.subheader(section["title"])
        if not section["finding_ids"]:
            st.caption("None established in this assessment.")
        for fid in section["finding_ids"]:
            finding_card(fid, expanded=section["title"] != "Exceptions/practice differences")
    for difference in result.get("policy_practice_divergence", []):
        st.write(difference)

    st.subheader("Evidence gaps")
    if not records:
        st.info("No evidence was retrieved. This snapshot cannot establish the claim.")
    for gap in view["gaps"]:
        st.write(gap["text"])
    if not view["gaps"]:
        st.caption(
            "No genuine evidence gap recorded. This does not establish complete retrieval or classification."
        )
    coverage = view["coverage"]
    st.caption(
        f"Classification coverage: {coverage['classified']}/{coverage['total']} {coverage['unit']}; {coverage['retrieved']} retrieved candidates."
    )
    if view["failures"]:
        st.warning(
            "Coverage is incomplete. Unclassified candidates may change the provisional verdict."
        )
        with st.expander(f"Classification failures ({len(view['failures'])})"):
            st.write(
                "These passages are present but unclassified; they may change the provisional verdict."
            )
            for fid in view["failures"]:
                finding_card(fid)
    with st.expander("Retrieval limits"):
        for text in view["retrieval_limits"]:
            st.write(text)
    with st.expander("Material exclusions and repeated evidence"):
        for fid in view["excluded"]:
            finding_card(fid)
        st.write(result["dependence_note"])
    with st.expander("Source scope and assessment limitations"):
        for text in result.get("limitations", []):
            if text not in view["retrieval_limits"]:
                st.write(text)

    st.subheader("Recommended next action")
    for action in view["recommendations"]:
        st.write(action["text"])
        if len(action["finding_ids"]) > 3:
            with st.expander(f"Cited findings ({len(action['finding_ids'])})"):
                for fid in action["finding_ids"]:
                    citation(fid)
        else:
            for fid in action["finding_ids"]:
                citation(fid)
        for gid in action.get("gap_ids", []):
            st.caption("Basis: " + next(g["text"] for g in view["gaps"] if g["gap_id"] == gid))
        if action.get("limit_ids"):
            st.caption("Basis: " + " ".join(view["retrieval_limits"]))
    if not view["recommendations"]:
        st.caption("No further action recorded in this snapshot.")

    with st.expander("Graph and assessment audit"):
        targets = st.multiselect(
            "Assessment targets",
            list(dict.fromkeys(f["assessment_target"] for f in view["findings"])),
            default=list(dict.fromkeys(f["assessment_target"] for f in view["findings"])),
            key="targets-" + run["run_id"],
        )
        states = st.multiselect(
            "Evidence dispositions",
            ["used", "excluded", "unclassified"],
            default=["used", "excluded", "unclassified"],
            key="states-" + run["run_id"],
        )
        limit = st.slider("Graph node limit", 1, 100, 100, key="limit-" + run["run_id"])
        graph = review_graph(
            run,
            result.get("review_snapshot", {}),
            targets=targets,
            dispositions=states,
            limit=limit,
            conversation_id=st.query_params.get("conversation"),
        )
        counts = graph.graph
        st.caption(
            f"Shown {counts['evidence_shown']}/{counts['evidence_total']} evidence candidates; {counts['findings_shown']}/{counts['findings_total']} target findings. Filtered: {counts['evidence_filtered']}; omitted by node limit: {counts['evidence_omitted_by_limit']}; omitted provenance sources: {counts['provenance_omitted_by_limit']}."
        )
        st.caption(
            "Legend: green support · red contradiction · gold qualification · blue context · grey excluded · purple unclassified. Edges name the assessment target; excluded edges retain the assessed relationship. Click nodes for frozen excerpts."
        )
        st.graphviz_chart(to_graphviz(graph))
        st.dataframe(
            [{"from": a, "to": b, **attrs} for a, b, attrs in graph.edges(data=True)],
            hide_index=True,
        )
        st.download_button(
            "Download shown graph (DOT)",
            to_graphviz(graph),
            file_name=run["run_id"] + ".dot",
            key="dot-" + run["run_id"],
        )
        st.json(result["runtime_metadata"])
    with st.expander("Sensitivity: temporary scenario"):
        st.caption("Recompute from this reviewed snapshot. No baseline records are changed.")
        group = st.selectbox(
            "Remove one source origin group",
            ["None", *result["source_groups"]],
            key="group-" + run["run_id"],
        )
        threshold = st.selectbox(
            "Materiality assumption", [0.5, 0.4, 0.6], key="threshold-" + run["run_id"]
        )
        if st.button("Compare scenario", key="compare-" + run["run_id"]):
            with connect(DATABASE_PATH) as connection:
                comparison = sensitivity(
                    connection,
                    run["run_id"],
                    remove_group=None if group == "None" else group,
                    materiality_threshold=threshold,
                )
            st.json(comparison)
    st.download_button(
        "Download complete print report (HTML)",
        claim_report_html(result),
        file_name=run["run_id"] + ".html",
        mime="text/html",
        key="html-" + run["run_id"],
    )
    st.download_button(
        "Download assessment audit (JSON)",
        json.dumps(result, indent=2),
        file_name=run["run_id"] + ".json",
        mime="application/json",
        key="json-" + run["run_id"],
    )


def entry_view(entry_id):
    try:
        with connect(DATABASE_PATH) as connection:
            ensure_system_assessment(connection, entry_id)
    except (ValueError, OSError, sqlite3.Error) as error:
        st.error(
            f"Automatic assessment could not complete: {error}. Check the evidence ledger and retry by reopening this claim."
        )
        return
    with connect(DATABASE_PATH) as connection:
        entry = get_entry(connection, entry_id)
        assessments = [
            r for r in runs(connection, entry_id) if r["status"] == "completed_assessment"
        ]
    st.write(entry["intake"]["text"])
    st.info(STATUS_LABELS[entry["status"]])
    if entry["submission_parts"] > 1:
        st.caption(
            f"One of {entry['submission_parts']} separately assessed statements. The complete original submission is retained below."
        )
    if entry["status"] == "awaiting_clarification":
        question = entry["intake"]["clarification"]
        st.write(question)
        with st.form("clarification-" + entry_id):
            answer = st.text_area(
                "Clarification",
                help="Your answer is added to the original claim for interpretation review.",
            )
            if st.form_submit_button("Add clarification"):
                try:
                    with connect(DATABASE_PATH) as connection:
                        clarify_claim(connection, entry_id, answer)
                    st.session_state["employee_review_entry"] = entry_id
                    st.rerun()
                except ValueError as error:
                    st.error(str(error))
        if entry["clarifications"]:
            st.warning(
                "Your clarification is saved, but the bounded parser cannot yet resolve this wording. "
                "A named reviewer must complete the interpretation fields below, quoting the claim "
                "and clarification and explaining how its full meaning is preserved."
            )
    elif not assessments:
        target = entry["intake"]["claim"]["evidence_target"]
        st.success("Saved meaning: " + next(k for k, v in TARGET_LABELS.items() if v == target))
    if not assessments and (
        entry["status"] != "awaiting_clarification" or entry["clarifications"]
    ):
        if (
            entry["status"] == "awaiting_clarification"
            and st.session_state.get("employee_review_entry") == entry_id
        ):
            review_page(entry_id)
        elif st.button("Continue this claim's review", key="continue-" + entry_id):
            st.session_state["employee_review_entry"] = entry_id
            st.rerun()
    if assessments:
        next_assessment = st.session_state.pop("next-assessment-" + entry_id, None)
        if next_assessment:
            st.session_state["assessment-" + entry_id] = next_assessment
        selected = st.selectbox(
            "Assessment history",
            [r["run_id"] for r in assessments],
            index=len(assessments) - 1,
            key="assessment-" + entry_id,
            format_func=lambda rid: next(
                ("System" if r.get("assessment_kind") == "system" else "Human") + " · " + rid
                for r in assessments
                if r["run_id"] == rid
            ),
        )
        run = next(r for r in assessments if r["run_id"] == selected)
        result_view(run, historical=selected != assessments[-1]["run_id"])
        if st.button(
            "Reassess automatically with current classifier", key="refresh-" + run["run_id"]
        ):
            try:
                with connect(DATABASE_PATH) as connection:
                    refreshed = refresh_system_assessment(connection, run["run_id"])
                st.session_state["next-assessment-" + entry_id] = refreshed["run_id"]
                st.rerun()
            except ValueError as error:
                st.error(str(error))
        if run.get("system_run_id"):
            post_assessment_review(run)
    with st.expander("Original wording, meaning and transformation audit"):
        st.text(entry["original_wording"])
        st.json(entry)


def post_assessment_review(run):
    with st.expander("Human review: confirm or correct evidence"):
        st.write(
            "The system verdict is already available. Each saved judgement creates a separate reassessment; unchanged classifications keep their original provenance."
        )
        with connect(DATABASE_PATH) as connection:
            system = get_run(connection, run["system_run_id"])
        st.table(
            {
                "Assessment": ["Original system", "Selected snapshot"],
                "Verdict": [system["result"]["outcome"], run["result"]["outcome"]],
                "Confidence": [system["result"]["confidence"], run["result"]["confidence"]],
            }
        )
        if run.get("changes"):
            st.caption("Parent assessment: " + run["parent_run_id"])
            st.json(run["changes"])
        notes = run["result"]["review_snapshot"]
        if not notes:
            st.info(
                "No evidence was retrieved to review. Add applicable sources to the ledger and submit a new assessment; this snapshot will remain available."
            )
            return
        eid = st.selectbox(
            "Evidence to correct", list(notes), key="correct-evidence-" + run["run_id"]
        )
        record = next(r for r in run["packet"]["results"] if r["evidence_id"] == eid)
        evidence_card(record, label="Inspect evidence being reviewed")
        note = notes[eid]
        st.write("Classification provenance: " + note["link"]["method"])
        st.write(note["link"]["applicability_reason"])
        st.json(note.get("classification", {}))
        with st.form("correction-" + run["run_id"] + "-" + eid):
            reviewer = st.text_input("Reviewer name")
            relationships = [r.value for r in EvidenceRelationship]
            relationship = st.selectbox(
                "Evidence relationship",
                relationships,
                index=relationships.index(note["link"]["relationship"])
                if note["link"]["relationship"] in relationships
                else None,
            )
            modes = [m.value for m in EvidenceMode]
            mode = st.selectbox(
                "Evidence mode", modes, index=modes.index(note["credibility"]["evidence_mode"])
            )
            matches = {
                key: st.checkbox(label, value=note["link"][key])
                for key, label in [
                    ("target_match", "Knowledge target matches"),
                    ("scope_match", "Scope matches"),
                    ("condition_match", "Conditions match"),
                    ("temporal_match", "Period matches"),
                ]
            }
            dimensions = {
                name: st.slider(
                    name.replace("_", " ").title(), 0.0, 1.0, float(note["credibility"][name]), 0.1
                )
                for name in DIMENSIONS
            }
            rationale = st.text_area("Reason for confirming or correcting this evidence")
            temporal_basis = st.text_input(
                "Temporal applicability basis when effective dates are undocumented",
                value=note["temporal_basis"],
            )
            confirmed = st.checkbox("I inspected this excerpt and its applicability to the claim")
            if st.form_submit_button("Save human review and reassess"):
                try:
                    if not confirmed:
                        raise ValueError(
                            "Inspect the evidence and confirm the checkbox before saving your judgement."
                        )
                    with connect(DATABASE_PATH) as connection:
                        updated = reassess_evidence(
                            connection,
                            run["run_id"],
                            eid,
                            reviewer=reviewer,
                            rationale=rationale,
                            relationship=relationship,
                            matches=matches,
                            mode=mode,
                            dimensions=dimensions,
                            justification=rationale,
                            applicability_reason=rationale,
                            temporal_basis=temporal_basis,
                        )
                    st.session_state["next-assessment-" + run["entry_id"]] = updated["run_id"]
                    st.rerun()
                except ValueError as error:
                    st.error(str(error))


def conversation_result(run, *, historical=False):
    result_view(run, historical=historical)
    if st.button("Optional human review", key="chat-review-" + run["run_id"]):
        st.session_state["chat_review_run"] = run["run_id"]
    if st.session_state.get("chat_review_run") == run["run_id"]:
        post_assessment_review(run)


def assess_page():
    st.title("Assess a Claim")
    st.write(
        "Send a claim for an automatic assessment across relevant evidence, then explore its findings and sources."
    )
    with connect(DATABASE_PATH) as connection:
        saved = conversations(connection)
    if st.sidebar.button("New conversation"):
        with connect(DATABASE_PATH) as connection:
            cid = create_conversation(connection)
        st.query_params["conversation"] = cid
        st.session_state["conversation_picker"] = cid
        st.rerun()
    cid = st.query_params.get("conversation") or st.session_state.get("conversation_picker")
    if cid and cid not in {c["conversation_id"] for c in saved}:
        st.error(
            "This conversation is unavailable. Choose a saved conversation or start a new one."
        )
        cid = None
    options = [c["conversation_id"] for c in saved]
    query_cid = st.query_params.get("conversation")
    if query_cid in options and st.session_state.get("loaded_conversation_url") != query_cid:
        st.session_state["conversation_picker"] = query_cid
        st.session_state["loaded_conversation_url"] = query_cid
    chosen = st.sidebar.selectbox(
        "Saved conversations",
        options,
        index=options.index(cid) if cid in options else None,
        format_func=lambda value: next(c["title"] for c in saved if c["conversation_id"] == value),
        key="conversation_picker",
    )
    if chosen and chosen != cid:
        st.query_params["conversation"] = chosen
        st.rerun()
    cid = chosen or cid
    history = []
    if cid:
        try:
            with connect(DATABASE_PATH) as connection:
                sync_assessments(connection, cid)
                history = messages(connection, cid)
        except (ValueError, OSError, sqlite3.Error) as error:
            st.error(f"Assessment could not complete: {error}. Reopen this conversation to retry.")
            with connect(DATABASE_PATH) as connection:
                history = messages(connection, cid)
    latest_by_entry = {
        m.get("entry_id"): m["run_id"] for m in history if m["kind"] == "assessment"
    }
    for message in history:
        with st.chat_message(message["role"]):
            if message["text"]:
                st.write(message["text"])
            if message.get("parent_run_id"):
                st.caption("Linked to earlier assessment: " + message["parent_run_id"])
            if message["kind"] == "assessment":
                with connect(DATABASE_PATH) as connection:
                    run = get_run(connection, message["run_id"])
                conversation_result(
                    run, historical=latest_by_entry.get(message.get("entry_id")) != run["run_id"]
                )
            elif message["kind"] == "followup" and message["role"] == "assistant":
                with connect(DATABASE_PATH) as connection:
                    run = get_run(connection, message["run_id"])
                st.caption("Based only on assessment " + run["run_id"])
                records = {r["evidence_id"]: r for r in run["result"]["evidence_records"]}
                from decidr.assessment_snapshot import presentation

                findings = {f["finding_id"]: f for f in presentation(run["result"])["findings"]}
                if message.get("finding_ids"):
                    for fid in message["finding_ids"]:
                        finding = findings[fid]
                        evidence_card(
                            records[finding["evidence_id"]],
                            label=finding["assessment_target"].replace("_", " ")
                            + " · "
                            + str(finding["relationship"]),
                            note={"link": {"applicability_reason": finding["reason"]}},
                            expanded=True,
                            run_id=run["run_id"],
                        )
                else:
                    for eid in message["evidence_ids"]:
                        evidence_card(
                            records[eid],
                            note=run["result"]["review_snapshot"].get(eid),
                            expanded=True,
                            run_id=run["run_id"],
                        )
                for limitation in message.get("limitations", []):
                    st.caption(limitation)
            elif message["kind"] == "question" and message.get("context"):
                with st.expander("Source context used to interpret terminology"):
                    for context in message["context"]:
                        st.text(context["text"])
                        st.link_button(
                            "Open interpretation source",
                            "?"
                            + urlencode(
                                {
                                    "conversation": cid,
                                    "source": context["source_id"],
                                    "evidence": context["evidence_id"],
                                }
                            ),
                        )
    linked = [m["run_id"] for m in history if m["kind"] == "assessment"]
    baseline = (
        st.sidebar.selectbox("Follow-up assessment", linked, index=len(linked) - 1)
        if linked
        else None
    )
    st.caption(
        "Ask about sources, contradictions or exceptions. To change the claim, send the complete revised statement."
    )
    if text := st.chat_input("Your claim or follow-up"):
        try:
            with connect(DATABASE_PATH) as connection:
                if not cid:
                    cid = create_conversation(connection)
                send_message(connection, cid, text, linked_run_id=baseline)
            st.query_params["conversation"] = cid
            # The picker was already instantiated in this run.
            st.rerun()
        except (ValueError, OSError, sqlite3.Error) as error:
            st.error(f"Message could not be assessed: {error}")


def register_page():
    st.title("Claim Register")
    with connect(DATABASE_PATH) as connection:
        register = entries(connection)
    st.caption(
        "Employee-entered and reviewed reusable claims. Experimental and evaluation items remain in Research / admin."
    )
    if not register:
        st.info("No employee claims yet. Start with Assess a Claim.")
        return
    kind = st.selectbox("Show claims", ["All", "reviewed_reusable", "employee_entered"])
    register = [e for e in register if kind == "All" or e["kind"] == kind]
    if not register:
        st.info("No claims in this category yet.")
        return
    st.dataframe(
        [
            {
                "Claim": e["intake"]["text"],
                "Category": e["kind"],
                "State": STATUS_LABELS[e["status"]],
                "ID": e["entry_id"],
            }
            for e in register
        ],
        hide_index=True,
    )
    selected = st.selectbox(
        "Inspect claim",
        [e["entry_id"] for e in register],
        format_func=lambda eid: next(
            e["intake"]["text"] for e in register if e["entry_id"] == eid
        ),
    )
    st.session_state["employee_review_entry"] = selected
    with connect(DATABASE_PATH) as connection:
        cid = reopen_claim(connection, selected)
    st.link_button("Continue in conversation", "./?" + urlencode({"conversation": cid}))
    entry_view(selected)


def risks_page():
    st.title("Knowledge Risks")
    with connect(DATABASE_PATH) as connection:
        dashboard = knowledge_risks(connection)
    st.write(dashboard["coverage"])
    cols = st.columns(3)
    cols[0].metric("Registered claims", dashboard["registered_claims"])
    cols[1].metric("Claims with completed assessments", dashboard["assessed_claims"])
    cols[2].metric("Claims awaiting completion", len(dashboard["pending_claims"]))
    st.caption(
        f"{len(dashboard['pending_reviews'])} open review packets. Flag counts cover only the {dashboard['assessed_claims']} assessed claims; categories can overlap."
    )
    if not dashboard["flags"]:
        st.info("No evidence-linked flags in completed assessments yet.")
    for index, flag in enumerate(dashboard["flags"]):
        with st.expander(f"{flag['kind'].replace('_', ' ').title()} · {flag['claim']}"):
            st.write(flag["reason"])
            with connect(DATABASE_PATH) as connection:
                run = get_run(connection, flag["run_id"])
            for record in run["result"]["evidence_records"]:
                if record["evidence_id"] in flag["evidence_ids"]:
                    evidence_card(record)
            st.caption(f"Claim {flag['entry_id']} · Assessment {flag['run_id']} · {flag['basis']}")
            if st.button("Inspect linked claim", key=f"risk-{index}"):
                st.session_state["risk_entry"] = flag["entry_id"]
    if st.session_state.get("risk_entry"):
        entry_view(st.session_state["risk_entry"])
    with st.expander("Pending claims and reviews"):
        st.dataframe(
            [
                {"Claim": e["intake"]["text"], "State": STATUS_LABELS[e["status"]]}
                for e in dashboard["pending_claims"]
            ]
        )
        st.write(dashboard["pending_reviews"])


def explorer_page():
    st.title("Evidence Explorer")
    st.write(
        "Search matches are evidence candidates, not verified conclusions. Searching does not create an assessment."
    )
    with st.form("evidence_search"):
        query = st.text_input("Search source evidence")
        semantic = st.checkbox("Use optional local semantic retrieval")
        search = st.form_submit_button("Search evidence")
    if search:
        try:
            with connect(DATABASE_PATH) as connection:
                st.session_state["evidence_search_packet"] = search_evidence(
                    connection, query, semantic=semantic
                )
        except ValueError as error:
            st.error(str(error))
    packet = st.session_state.get("evidence_search_packet")
    if packet:
        st.caption(f"Actual method: {packet['method']} · Semantic: {packet['semantic_status']}")
        if not packet["results"]:
            st.info(
                "No relevant evidence retrieved. This does not establish that no evidence exists in the corpus."
            )
        for record in packet["results"]:
            evidence_card(record)
        if packet["results"]:
            with st.expander("Explore source relationships around a search match"):
                evidence_id = st.selectbox(
                    "Evidence graph starting point", [r["evidence_id"] for r in packet["results"]]
                )
                with connect(DATABASE_PATH) as connection:
                    graph = source_neighbourhood(connection, evidence_id)
                st.caption(
                    "Two hops, at most 40 nodes. Ownership and authorship metadata do not establish decision rights; graph proximity is not support."
                )
                st.graphviz_chart(to_graphviz(graph))
                st.dataframe(
                    [{"from": a, "to": b, **attrs} for a, b, attrs in graph.edges(data=True)],
                    hide_index=True,
                )
    with connect(DATABASE_PATH) as connection:
        review_runs = runs(connection)
    if review_runs:
        st.subheader("Bounded claim and source graph")
        chosen = st.selectbox("Review packet graph", [r["run_id"] for r in review_runs])
        run = next(r for r in review_runs if r["run_id"] == chosen)
        with connect(DATABASE_PATH) as connection:
            notes = review_notes(connection, chosen)
        graph = review_graph(run, notes)
        st.caption(
            "Up to 60 nodes. Retrieved matches and proposed links are explicitly distinguished from human-reviewed relationships."
        )
        st.graphviz_chart(to_graphviz(graph))
        st.dataframe(
            [{"from": a, "to": b, **attrs} for a, b, attrs in graph.edges(data=True)],
            hide_index=True,
        )


def review_page(entry_id=None):
    st.subheader("Claim evidence review")
    st.caption(
        "Local research prototype: reviewer names are audit identifiers, not authenticated access control. This workflow does not create formal evaluation records."
    )
    with connect(DATABASE_PATH) as connection:
        register = entries(connection)
    if not register:
        st.info("Submit a claim first.")
        return
    if entry_id is None:
        entry_id = st.selectbox(
            "Employee claim",
            [e["entry_id"] for e in register],
            format_func=lambda eid: next(
                e["intake"]["text"] for e in register if e["entry_id"] == eid
            ),
        )
    entry = next(e for e in register if e["entry_id"] == entry_id)
    if entry["status"] != "awaiting_clarification" or (
        not entry["clarifications"]
        and (entry["intake"]["clarification"] or "").startswith("Is this about")
    ):
        entry_view(entry_id)
        return
    st.text(entry["original_wording"])
    reviewer = st.text_input("Reviewer name")
    if entry["status"] == "awaiting_clarification":
        st.warning(
            "Interpretation requires human review. Preserve every quantity, date, negation, condition and clause; request clarification if meaning cannot be resolved."
        )
        st.write(entry["clarifications"])
        with st.form("manual_interpretation"):
            subject = st.text_input("Actor or subject (exact words)")
            predicate = st.text_input("Action or predicate (exact words)")
            obj = st.text_area("Object and qualifiers (exact words)")
            target = st.selectbox("Knowledge target", list(TARGET_LABELS))
            dated = st.checkbox("Claim has an explicit relevant date or period")
            start = st.date_input("Relevant start date", None)
            end = st.date_input("Relevant end date", None)
            negative = st.checkbox("The proposition is negated")
            reason = st.text_area(
                "Meaning review justification, including treatment of every clause and clarification"
            )
            if st.form_submit_button("Save reviewed interpretation"):
                try:
                    claim = AtomicClaim(
                        claim_id="pending",
                        subject=subject,
                        predicate=predicate,
                        object=obj,
                        claim_text=entry["intake"]["text"].strip(),
                        claim_type="employee_entered",
                        evidence_target=TARGET_LABELS[target],
                        applicable_start_date=start if dated else None,
                        applicable_end_date=end if dated else None,
                        proposition_polarity="negative" if negative else "positive",
                    )
                    with connect(DATABASE_PATH) as connection:
                        review_interpretation(
                            connection, entry_id, claim, reviewer=reviewer, reason=reason
                        )
                    st.rerun()
                except ValueError as error:
                    st.error(str(error))
        return
