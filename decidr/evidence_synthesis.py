"""Connect approval evidence without equating relevance with verified authority.

Typed record fields and exact identifiers establish links. Shared topics are
labelled context; narrative passages retain their original wording for review.
"""

from datetime import date
from decimal import Decimal, InvalidOperation
import json
import re

from decidr.approval_propositions import normalise_role, parse_approval_rule
from decidr.expense_approval import parse_expense_rule
from decidr.retrieval import record_identifiers


def _day(value):
    try:
        return date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _name(value):
    return normalise_role(re.sub(r"\s*\([^)]*\)\s*$", "", str(value)).casefold().strip())


def _row(p):
    try:
        row = json.loads(p.text)
        return row if isinstance(row, dict) else {}
    except (ValueError, TypeError):
        return {}


def _claim_scope(claim):
    lowered = claim.casefold()
    topic = (
        "discount"
        if re.search(r"\bdiscounts?\b", lowered)
        else "expense"
        if re.search(r"\bexpense claims?\b", lowered)
        else None
    )
    if not topic or not re.search(r"\b(approv\w*|authori[sz]\w*|sign.off)\b", lowered):
        return None
    complete = parse_approval_rule(claim) if topic == "discount" else parse_expense_rule(claim)
    fields = complete.model_dump() if hasattr(complete, "model_dump") else complete
    if fields:
        return {
            "topic": topic,
            "threshold": fields.get("percentage", fields.get("amount")),
            "boundary": fields["boundary"],
            "currency": fields.get("currency"),
            "deal_scope": fields.get("deal_scope"),
            "complete_rule": True,
        }
    # Short claims can guide evidence selection without inventing omitted scope.
    token = (
        r"(?P<value>\d+(?:\.\d+)?)\s*(?:%|percent|per cent)"
        if topic == "discount"
        else r"(?P<currency>[$£€])(?P<value>\d+(?:\.\d+)?)"
    )
    match = re.search(r"\b(?P<boundary>above|over|at least|below|at most)\s+" + token, lowered)
    return {
        "topic": topic,
        "threshold": match["value"] if match else None,
        "boundary": {
            "above": "gt",
            "over": "gt",
            "at least": "ge",
            "below": "lt",
            "at most": "le",
        }.get(match["boundary"])
        if match
        else None,
        "currency": match.groupdict().get("currency") if match else None,
        "deal_scope": None,
        "complete_rule": False,
    }


def build_evidence_synthesis(claim, passages, sources, as_of, *, resolved_record_ids=None):
    scope = _claim_scope(claim)
    if scope is None:
        return None
    topic = scope["topic"]
    identifiers = set(record_identifiers(claim))
    resolved = {
        value.upper()
        for value in (resolved_record_ids or [])
        if isinstance(value, str) and record_identifiers(value) == [value.upper()]
    }
    # Resolution may add a uniquely matched event, but must never replace an explicit claim ID.
    from_resolution = not identifiers and len(resolved) == 1
    if from_resolution:
        identifiers = resolved
    subject = re.compile(
        r"\bdiscount\w*\b" if topic == "discount" else r"\bexpense\w*\b", re.IGNORECASE
    )
    approval = re.compile(r"\b(approv\w*|authori[sz]\w*|sign.off|okays?)\b", re.IGNORECASE)
    nodes = []
    edges = []
    future = set()
    seen = set()
    headers = {}
    for p in passages:
        dates = re.findall(
            r"(?:Timestamp|Interview date|Date):\*{0,2}\s*(\d{4}-\d{2}-\d{2})",
            p.text,
            re.IGNORECASE,
        )
        headers.setdefault((p.source_id, p.section or p.heading), set()).update(dates)

    def add(p, lane, relation, reason, start=0, end=None, record_id=None, details=None):
        s = sources[p.source_id]
        end = len(p.text) if end is None else end
        key = (p.evidence_id, start, end, lane)
        if key in seen:
            if details and details.get("person"):
                for node in nodes:
                    citation = node["citation"]
                    if (
                        citation["evidence_id"],
                        citation["start"],
                        citation["end"],
                        node["lane"],
                    ) == key:
                        node["details"].update(details)
            return
        seen.add(key)
        section_dates = headers.get((p.source_id, p.section or p.heading), set())
        known = [
            d
            for d in [s.creation_date, p.relevant_start_date, *[_day(d) for d in section_dates]]
            if d
        ]
        if any(d > as_of for d in known):
            future.add(p.evidence_id)
            return
        temporal = "dated" if known else "date_not_established"
        if s.effective_start_date and s.effective_start_date > as_of:
            temporal = "not_yet_effective"
        elif s.effective_end_date and s.effective_end_date < as_of:
            temporal = "historical"
        elif s.lifecycle_status in {"superseded", "draft"}:
            temporal = s.lifecycle_status
        limits = ["Source authority and independence are not established by this connection."]
        if not known:
            limits.append("Source availability at the assessment date is not established.")
        if temporal in {"not_yet_effective", "historical", "superseded", "draft"}:
            limits.append(
                "Policy applicability requires review; this is not automatically a current rule."
            )
        if s.metadata_conflicts:
            limits.append("Source metadata contains conflicts.")
        if s.derived_from_source_id or s.duplicate_group:
            limits.append(
                "Known source dependence or duplication; do not count as independent corroboration."
            )
        nodes.append(
            {
                "id": f"connected:{len(nodes) + 1}",
                "lane": lane,
                "relationship": relation,
                "reason": reason,
                "source_title": s.title,
                "source_id": p.source_id,
                "record_id": record_id,
                "temporal_status": temporal,
                "details": details or {},
                "limitations": limits,
                "citation": {
                    "evidence_id": p.evidence_id,
                    "source_id": p.source_id,
                    "locator": p.locator,
                    "quotation": p.text[start:end],
                    "start": start,
                    "end": end,
                },
            }
        )

    # Formal, reported and role context use subject-specific passages, not whole documents.
    for p in passages:
        s = sources.get(p.source_id)
        if not s or s.ingestion_status != "ingested" or _row(p):
            continue
        for match in re.finditer(r"[^\n]+", p.text):
            text = match[0]
            if not (
                subject.search(text)
                or (s.source_type in {"policy", "procedure"} and subject.search(p.text))
            ) or not approval.search(text):
                continue
            if s.source_type == "policy":
                if not re.search(r"\b(requires?|must|may|shall)\b", text, re.IGNORECASE):
                    continue
                add(
                    p,
                    "formal",
                    "documented_requirement",
                    "Policy wording; check the stated scope, dates and exceptions.",
                    match.start(),
                    match.end(),
                )
            elif s.source_type in {"interview", "internal_communication", "meeting"}:
                add(
                    p,
                    "observed",
                    "reported_account",
                    "A reported account to compare with the formal requirement; its wording alone is not a verified event or contradiction.",
                    match.start(),
                    match.end(),
                )
            elif s.source_type in {"procedure", "organisational_information", "role_description"}:
                # Retain relevant table rows, not unrelated onboarding rows in the same table.
                add(
                    p,
                    "formal",
                    "role_or_process_context",
                    "Documented role or process context; does not by itself establish policy-adoption rights.",
                    match.start(),
                    match.end(),
                    details={"heading": p.heading},
                )

    roles = []
    for p in passages:
        if p.source_type not in {"organisational_information", "role_description"}:
            continue
        s = sources.get(p.source_id)
        if (
            not s
            or s.ingestion_status != "ingested"
            or (s.creation_date and s.creation_date > as_of)
        ):
            continue
        match = re.fullmatch(r"(.+?)\s+[—–]\s+(.+)", p.heading or "")
        if match:
            roles.append((_name(match[2]), match[1], p))

    # Scan all structured records, not only the first retrieval page.
    for p in passages:
        s = sources.get(p.source_id)
        row = _row(p)
        if not s or s.ingestion_status != "ingested" or not row:
            continue
        if topic == "discount" and p.source_type != "crm_records":
            continue
        if topic == "expense" and (
            p.source_type != "project_tasks"
            or "expense" not in str(row.get("process_or_capability", "")).casefold()
        ):
            continue
        record_id = str(
            row.get("deal_id" if topic == "discount" else "task_id", p.row_identifier or "")
        )
        if identifiers and record_id.upper() not in identifiers:
            continue
        if scope["threshold"] is not None:
            try:
                value = Decimal(
                    str(
                        row.get("discount_pct")
                        if topic == "discount"
                        else row.get("expense_amount", row.get("amount"))
                    )
                )
                threshold = Decimal(scope["threshold"])
                if not value.is_finite():
                    continue
                if not {
                    "gt": value > threshold,
                    "ge": value >= threshold,
                    "lt": value < threshold,
                    "le": value <= threshold,
                    "eq": value == threshold,
                }[scope["boundary"]]:
                    continue
                if topic == "expense" and row.get("currency") != scope["currency"]:
                    continue
            except InvalidOperation:
                continue
        elif not identifiers:
            # An omitted threshold is shown as a selection gap, not filled from a policy.
            continue
        recorded_scope = (
            str(row.get("deal_scope", row.get("deal_type", ""))).casefold().replace(" ", "-")
        )
        if (
            scope["deal_scope"]
            and recorded_scope
            and recorded_scope != scope["deal_scope"].replace(" ", "-")
        ):
            continue
        event_day = _day(row.get("close_date" if topic == "discount" else "reimbursement_date"))
        if event_day and event_day > as_of:
            future.add(p.evidence_id)
            continue
        approver = str(row.get("approval_role", ""))
        matches = [
            (role, role_passage) for name, role, role_passage in roles if name == _name(approver)
        ]
        record = str(row.get("approval_record", "")).strip()
        outside = bool(re.search(r"\b(outside CRM|slack|email)\b", record, re.IGNORECASE))
        missing = not record or bool(
            re.search(r"\b(no|none|missing|unknown|unconfirmed)\b", record, re.IGNORECASE)
        )
        add(
            p,
            "observed",
            "recorded_approval_route",
            "Recorded transaction fields. A named approver does not exclude another approval or establish delegated authority.",
            record_id=record_id,
            details={
                "approver": approver or None,
                "role": matches[0][0] if len(matches) == 1 else None,
                "discount_pct": row.get("discount_pct"),
                "event_date": event_day.isoformat() if event_day else None,
                "scope": recorded_scope or "not established",
            },
        )
        if outside or missing:
            add(
                p,
                "documented",
                "approval_referenced_elsewhere" if outside else "approval_documentation_gap",
                "Approval is referenced outside CRM; inspect the original communication and any recording requirement."
                if outside
                else "The record lacks a clear approval reference. This is not proof that approval never happened.",
                record_id=record_id,
                details={"approval_record": record or None},
            )
        for role, role_passage in matches:
            # Exact heading-to-person match only, never fuzzy title equivalence.
            add(
                role_passage,
                "formal",
                "documented_role",
                "The role heading names the recorded approver; dates, delegation and authority still require review.",
                details={"heading": role_passage.heading, "person": approver, "role": role},
            )

    selected_records = {n["record_id"] for n in nodes if n["record_id"]}
    for p in passages:
        source = sources.get(p.source_id)
        if not source or source.ingestion_status != "ingested" or _row(p):
            continue
        linked = selected_records.intersection(record_identifiers(p.text))
        if linked and source.source_type in {
            "interview",
            "internal_communication",
            "meeting",
            "audit_events",
        }:
            add(
                p,
                "documented",
                "explicit_record_reference",
                "This passage explicitly names a selected record. Inspect its statement and date; the reference alone does not establish approval.",
            )

    # Edge types disclose why evidence is connected rather than implying corroboration.
    for node in nodes:
        edges.append(
            {
                "from": "claim",
                "to": node["id"],
                "relationship": "subject_context"
                if not node["record_id"]
                else "resolved_transaction_reference"
                if from_resolution
                else "record_in_claim_range",
                "basis": "Subject and approval wording"
                if not node["record_id"]
                else "Record selected by the transaction component comparison; the original claim supplied no record identifier. Scope remains a separate check."
                if from_resolution
                else "Explicit record identifier or numeric threshold; unrecorded scope remains unresolved.",
            }
        )
    for index, left in enumerate(nodes):
        left_ids = set(record_identifiers(left["citation"]["quotation"]))
        for right in nodes[index + 1 :]:
            relationship = None
            if left["record_id"] and left["record_id"] == right["record_id"]:
                relationship = "same_record"
            elif (
                right["record_id"]
                and right["record_id"] in left_ids
                or left["record_id"]
                and left["record_id"] in record_identifiers(right["citation"]["quotation"])
            ):
                relationship = "explicit_record_reference"
            elif (
                left["details"].get("person")
                and _name(left["details"]["person"]) == _name(right["details"].get("approver", ""))
                or right["details"].get("person")
                and _name(right["details"]["person"]) == _name(left["details"].get("approver", ""))
            ):
                relationship = "recorded_person_role"
            if relationship:
                edges.append(
                    {
                        "from": left["id"],
                        "to": right["id"],
                        "relationship": relationship,
                        "basis": "Exact identifier or person field match; not verified authority or independent corroboration.",
                    }
                )
    comparisons = []
    for policy in nodes:
        if policy["relationship"] != "documented_requirement" or policy["temporal_status"] in {
            "historical",
            "superseded",
            "draft",
            "not_yet_effective",
        }:
            continue
        rule = parse_approval_rule(policy["citation"]["quotation"])
        if not rule:
            continue
        for event in nodes:
            role = event["details"].get("role")
            if event["relationship"] != "recorded_approval_route" or not role:
                continue
            if _name(role) != _name(rule.approver):
                comparisons.append(
                    {
                        "kind": "different_recorded_role",
                        "summary": f"{event['record_id']} names an approver documented as {role}; the policy passage requires {rule.approver}. This does not establish that required approval was absent. Deal scope, exceptions and delegated authority still need checking.",
                        "node_ids": [policy["id"], event["id"]],
                    }
                )
                edges.append(
                    {
                        "from": policy["id"],
                        "to": event["id"],
                        "relationship": "different_recorded_role",
                        "basis": "Compare the required policy role with the exact person-to-role heading link; difference alone is not a violation.",
                    }
                )
    counts = {
        lane: sum(n["lane"] == lane for n in nodes)
        for lane in ["formal", "observed", "documented"]
    }
    return {
        "status": "connected_evidence" if nodes else "no_matching_evidence",
        "scope": scope,
        "record_selection": {
            "basis": "resolved_transaction" if from_resolution else "claim_identifiers_or_range",
            "record_ids": sorted(identifiers),
        },
        "nodes": nodes,
        "comparisons": comparisons,
        "edges": edges,
        "counts": counts,
        "future_evidence_excluded": len(future),
        "summary": f"{counts['formal']} formal/context passages, {counts['observed']} reported or recorded practice passages, and {counts['documented']} documentation findings connected.",
        "notice": (
            "The transaction comparison selected "
            + ", ".join(sorted(identifiers))
            + "; the original claim did not supply a record identifier. "
            if from_resolution
            else ""
        )
        + "These connections compare evidence across the same subject. Reports and recorded routes are not automatically policy violations; requiring Finance approval does not mean only Finance can approve. Missing scope, authority, dates and independence remain unresolved.",
        "questions": [
            "Does the stated policy apply to this deal type and event date?",
            "Was required approval obtained, and was any alternative approver authorised?",
            "Does the original approval exist, and was it recorded where the policy requires?",
        ],
    }
