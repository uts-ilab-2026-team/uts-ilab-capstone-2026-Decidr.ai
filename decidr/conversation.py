"""Persistent conversation links around immutable employee assessments.

Only a submitted claim and explicit clarification enter intake. Follow-ups read a
selected frozen result; message history is never sent to retrieval or classification.
"""

import json
import re
from uuid import uuid4

from decidr.claim_intake import VERB, interpret_claim
from decidr.claim_workflow import (
    _update_entry,
    clarify_claim,
    ensure_system_assessment,
    get_entry,
    get_run,
    runs,
    save_claim,
    submit_claim,
)
from decidr.database import record_audit


def initialise_conversations(connection):
    for statement in (
        """CREATE TABLE IF NOT EXISTS employee_conversations (
            conversation_id TEXT PRIMARY KEY, title TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS employee_messages (
            message_id INTEGER PRIMARY KEY, conversation_id TEXT NOT NULL
            REFERENCES employee_conversations(conversation_id), payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
    ):
        connection.execute(statement)


def conversations(connection):
    initialise_conversations(connection)
    return [
        {"conversation_id": r[0], "title": r[1]}
        for r in connection.execute(
            "SELECT conversation_id,title FROM employee_conversations ORDER BY rowid DESC"
        )
    ]


def messages(connection, conversation_id):
    return [
        dict(message_id=r[0], **json.loads(r[1]))
        for r in connection.execute(
            "SELECT message_id,payload_json FROM employee_messages WHERE conversation_id=? ORDER BY message_id",
            (conversation_id,),
        )
    ]


def append_message(connection, conversation_id, role, kind, text="", **links):
    connection.execute(
        "INSERT INTO employee_messages(conversation_id,payload_json) VALUES (?,?)",
        (conversation_id, json.dumps(dict(role=role, kind=kind, text=text, **links))),
    )


def create_conversation(connection, title="New conversation"):
    initialise_conversations(connection)
    cid = "CHAT-" + uuid4().hex[:16]
    connection.execute(
        "INSERT INTO employee_conversations(conversation_id,title) VALUES (?,?)",
        (cid, title[:100]),
    )
    return cid


def sync_assessments(connection, cid):
    history = messages(connection, cid)
    seen = {m.get("run_id") for m in history if m["kind"] == "assessment"}
    entry_ids = list(dict.fromkeys(m["entry_id"] for m in history if m.get("entry_id")))
    for eid in entry_ids:
        ensure_system_assessment(connection, eid)
        for run in runs(connection, eid):
            if run["status"] == "completed_assessment" and run["run_id"] not in seen:
                append_message(
                    connection,
                    cid,
                    "assistant",
                    "assessment",
                    entry_id=eid,
                    run_id=run["run_id"],
                    parent_run_id=run.get("parent_run_id")
                    or next(
                        (m.get("parent_run_id") for m in history if m.get("entry_id") == eid), None
                    ),
                )
                seen.add(run["run_id"])


def reopen_claim(connection, entry_id):
    initialise_conversations(connection)
    for c in conversations(connection):
        if any(m.get("entry_id") == entry_id for m in messages(connection, c["conversation_id"])):
            return c["conversation_id"]
    entry = get_entry(connection, entry_id)
    cid = create_conversation(connection, entry["original_wording"])
    append_message(connection, cid, "user", "claim", entry["original_wording"], entry_id=entry_id)
    for response in entry["clarifications"]:
        append_message(connection, cid, "user", "clarification", response, entry_id=entry_id)
    sync_assessments(connection, cid)
    if get_entry(connection, entry_id)["status"] == "awaiting_clarification":
        _question(connection, cid, entry_id)
    return cid


def _question(connection, cid, eid):
    entry = get_entry(connection, eid)
    part = entry["intake"]
    question = part["clarification"]
    if "unclear reference" in question:
        reference = re.search(
            r"\b(it|they|this|that|these|those|he|she|someone|something)\b",
            part["text"],
            re.IGNORECASE,
        )
        question = f"Who or what does “{reference[0]}” refer to? You can reply with a complete claim naming the subject."
    elif not part.get("claim") and not part.get("provenance", {}).get("clarification_kind"):
        question += (
            " Reply with the complete claim you intend; your original wording will be retained."
        )
    append_message(
        connection,
        cid,
        "assistant",
        "question",
        question,
        entry_id=eid,
        context=part.get("provenance", {}).get("terminology_context", []),
    )


def _target(text):
    text = text.strip().casefold().rstrip(".! ")
    text = re.sub(r"^(?:i mean|i am asking about|i’m asking about|i mean the) +", "", text)
    return next(
        (
            target
            for target, pattern in {
                "all": r"both|all|all of (?:them|the above)|both of (?:them|the above)|(?:i want )?your interpretation|(?:assess|consider|check) (?:both|all|all evidence)",
                "prescribed_rule": r"(?:the )?(?:written (?:expense )?policy|written rule|policy|prescribed rule|formal policy|what the policy says)",
                "actual_practice": r"(?:the )?(?:actual practice|practice|in practice|what actually happens|how it works in practice)",
                "recorded_state": r"(?:the )?(?:recorded state|record|what the record says)",
            }.items()
            if re.fullmatch(pattern, text)
        ),
        None,
    )


def followup_kind(text):
    # Deliberately whole-utterance matching: a changed assertion mentioning an
    # exception or source must never be answered with the previous verdict.
    text = text.strip().casefold().rstrip("?.! ")
    text = re.sub(r"^(?:please |can you |could you )", "", text)
    reference = r"(?:this|that|the claim|this claim|the verdict|this assessment)"
    if re.fullmatch(rf"(?:what|which) (?:sources?|evidence) supports? {reference}", text):
        return "sources"
    if re.fullmatch(rf"(?:what|which) (?:sources?|evidence) contradicts? {reference}", text):
        return "contradictions"
    for kind, pattern in {
        "sources": r"(?:(?:show|list)(?: me)? (?:the )?)?(?:sources|evidence|source links)|(?:what|which) (?:sources|evidence)(?: support (?:this|that|the claim))?|where (?:does|did) (?:this|that) come from",
        "contradictions": r"(?:(?:show|explain)(?: me)? (?:the )?)?contradictions|(?:what|which) (?:sources )?contradict(?:s)? (?:this|that|the claim)|(?:are there|any|what about) (?:any )?contradictions",
        "exceptions": r"(?:(?:show|explain|list)(?: me)? (?:the )?)?(?:exceptions|conditions)|(?:are there|any|what about) (?:any )?(?:exceptions|conditions)|what (?:are the )?(?:exceptions|conditions)(?: apply)?",
        "explanation": r"why|explain(?: (?:this|that|the verdict|the assessment))?|why (?:this|that) verdict",
    }.items():
        if re.fullmatch(pattern, text):
            return kind
    return None


def followup_answer(run, kind):
    result = run["result"]
    from decidr.assessment_snapshot import presentation

    relations = {
        "sources": {"support", "contradict", "qualify", "contextual"},
        "contradictions": {"contradict"},
        "exceptions": {"qualify", "contextual"},
        "explanation": {"support", "contradict", "qualify"},
    }[kind]
    findings = [
        f
        for f in presentation(result)["findings"]
        if f["disposition"] == "used" and f["relationship"] in relations
    ]
    ids = list(dict.fromkeys(f["evidence_id"] for f in findings))
    text = (
        result["explanation"]
        if kind == "explanation"
        else {
            "sources": "These passages are linked to this assessment, with their assessed relationships.",
            "contradictions": "These passages record assessed contradictions or policy–practice differences.",
            "exceptions": "These are the assessment's qualifying and contextual passages. Their applicability is shown with each excerpt.",
        }[kind]
    )
    if not ids:
        text += " No such classified passages were established in this snapshot; this does not establish that none exist."
    return {
        "text": text,
        "evidence_ids": ids,
        "finding_ids": [f["finding_id"] for f in findings],
        "limitations": result.get("limitations", [])
        if kind in {"exceptions", "explanation"}
        else [],
    }


def _clarified_wording(entry, response):
    """Substitute a single unclear subject only when the user names its referent."""
    original = entry["intake"]["text"]
    if "unclear reference" not in (entry["intake"]["clarification"] or ""):
        return response, "explicit_user_restatement"
    reference = re.match(r"\s*(They|It|He|She|This|That)\b", original, re.IGNORECASE)
    if not reference:
        return response, "explicit_user_restatement"
    named = re.fullmatch(
        rf"(?:{reference[1]} (?:refers? to|means?) )?([A-Za-z][A-Za-z &'’-]{{0,80}})\.?",
        response.strip(),
        re.IGNORECASE,
    )
    if (
        named
        and not VERB.search(named[1])
        and not re.search(
            r"\b(must|shall|may|is|are|was|were|if|unless|except|not|they|it|he|she|this|that)\b",
            named[1],
            re.IGNORECASE,
        )
    ):
        return original[: reference.start(1)] + named[1] + original[
            reference.end(1) :
        ], "explicit_user_reference"
    return response, "explicit_user_restatement"


def _revision_of(wording, previous):
    # Infer a revision only for the same wording with changed values/polarity.
    # Sharing a subject (e.g. "Employees") is not evidence of the same topic.
    def proposition(text):
        text = re.sub(r"\b\d+(?:\.\d+)?\b", "VALUE", text.casefold())
        text = re.sub(r"\bnot\b", "", text)
        return " ".join(text.strip(" .").split())

    return proposition(wording) == proposition(previous)


def send_message(connection, cid, text, *, linked_run_id=None):
    if not text.strip() or len(text) > 6000:
        raise ValueError("Enter a message of 1–6000 characters")
    if cid not in {c["conversation_id"] for c in conversations(connection)}:
        raise ValueError("Unknown conversation")
    history = messages(connection, cid)
    linked = [m["run_id"] for m in history if m["kind"] == "assessment"]
    if linked_run_id and linked_run_id not in linked:
        raise ValueError("Choose an assessment from this conversation")
    baseline = linked_run_id or (linked[-1] if linked else None)
    # Only the active claim can receive a clarification. An older pending question
    # must not absorb a later topic, even if that older entry remains in history.
    active = next((m["entry_id"] for m in reversed(history) if m.get("entry_id")), None)
    pending = (
        active
        if active and get_entry(connection, active)["status"] == "awaiting_clarification"
        else None
    )
    target = _target(text)
    revision = re.match(
        r"\s*(?:correction|revision|revise (?:that|the claim)|i meant)\s*[:,]\s*(.+)",
        text,
        re.IGNORECASE,
    )
    wording = revision[1] if revision else text
    reference_reply = False
    if pending:
        previous = get_entry(connection, pending)
        old_text = previous["intake"]["text"]
        # A complete restatement resolves a reference only if its predicate and
        # object are unchanged. A new subject/action is a separate submission.
        unclear = re.match(r"\s*(?:They|It|He|She|This|That)\b(.*)", old_text, re.IGNORECASE)
        reference_reply = bool(unclear and wording.rstrip(".").endswith(unclear[1].rstrip(".")))
    short_reference = (
        pending and _clarified_wording(previous, wording)[1] == "explicit_user_reference"
    )
    period_reply = pending and bool(
        re.fullmatch(r"\d{4}-\d{2}-\d{2}(?: to \d{4}-\d{2}-\d{2})?", wording.strip())
    )
    clarifying = pending and (
        target or revision or reference_reply or short_reference or period_reply
    )
    connection.execute("SAVEPOINT conversation_turn")
    try:
        if not history:
            connection.execute(
                "UPDATE employee_conversations SET title=? WHERE conversation_id=?",
                (text[:100], cid),
            )
        kind = followup_kind(text)
        if kind and baseline:
            append_message(connection, cid, "user", "followup", text, run_id=baseline)
            append_message(
                connection,
                cid,
                "assistant",
                "followup",
                run_id=baseline,
                **followup_answer(get_run(connection, baseline), kind),
            )
        elif clarifying:
            append_message(
                connection,
                cid,
                "user",
                "clarification",
                text,
                entry_id=pending,
                parent_run_id=baseline,
            )
            clarify_claim(connection, pending, text, target=target)
            entry = get_entry(connection, pending)
            # A complete explicit restatement can resolve unsupported grammar. No
            # interpolation of prior turns, policy passages, approvers or conditions.
            if entry["status"] == "awaiting_clarification" and not target:
                clarified, basis = _clarified_wording(entry, wording)
                part = interpret_claim(clarified).parts
                if len(part) == 1 and part[0].claim:
                    resolved = part[0]
                    resolved.claim.original_claim_text = entry["original_wording"]
                    resolved.provenance.update(
                        interpreted_claim=resolved.claim.claim_text,
                        original_intake=entry["intake"],
                        meaning_basis=basis,
                    )
                    save_claim(connection, resolved.claim)
                    entry["intake"] = resolved.model_dump(mode="json")
                    _update_entry(connection, pending, entry)
                    connection.execute(
                        "UPDATE employee_claims SET claim_id=?,status=? WHERE entry_id=?",
                        (resolved.claim.claim_id, resolved.status, pending),
                    )
                    record_audit(
                        connection,
                        actor="employee",
                        action="claim_restated",
                        entity_type="employee_claim",
                        entity_id=pending,
                        changed_fields={
                            "original_wording": entry["original_wording"],
                            "interpreted_claim": resolved.claim.claim_text,
                        },
                    )
            sync_assessments(connection, cid)
            if get_entry(connection, pending)["status"] == "awaiting_clarification":
                _question(connection, cid, pending)
        else:
            parent = None
            if target and baseline:
                previous = get_run(connection, baseline)
                wording = previous["claim"]["claim_text"]
                parent = baseline
            elif baseline:
                previous = get_run(connection, baseline)
                if revision or _revision_of(wording, previous["claim"]["claim_text"]):
                    parent = baseline
            eids = submit_claim(connection, wording, target=target, parent_run_id=parent)
            for index, eid in enumerate(eids):
                append_message(
                    connection,
                    cid,
                    "user" if index == 0 else "assistant",
                    "claim" if index == 0 else "claim_part",
                    text
                    if index == 0
                    else "Separate statement: " + get_entry(connection, eid)["intake"]["text"],
                    entry_id=eid,
                    parent_run_id=parent,
                )
            sync_assessments(connection, cid)
            for eid in eids:
                if get_entry(connection, eid)["status"] == "awaiting_clarification":
                    _question(connection, cid, eid)
        connection.execute("RELEASE conversation_turn")
    except Exception:
        connection.execute("ROLLBACK TO conversation_turn")
        connection.execute("RELEASE conversation_turn")
        raise
