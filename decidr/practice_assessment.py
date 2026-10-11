"""Compare explicit operational fields with a rule without rewriting its formal verdict.

Record-level comparisons are conditional on what the source records. Missing fields,
role aliases and task completion dates are not silently promoted to event facts.
"""

from datetime import date
from decimal import Decimal, InvalidOperation
import json
import re

from decidr.approval_propositions import normalise_role, parse_approval_rule
from decidr.expense_approval import parse_expense_rule
from decidr.retrieval_models import Evidence, Source
from decidr.transaction_claims import approval_state


def _day(value):
    try:
        return date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _number(value):
    try:
        number = Decimal(str(value))
        return number if number.is_finite() and number >= 0 else None
    except InvalidOperation:
        return None


def _role(value):
    return normalise_role(str(value).casefold().strip()).removeprefix("the ")


def _covered(amount, threshold, boundary):
    return {
        "gt": amount > threshold,
        "ge": amount >= threshold,
        "eq": amount == threshold,
        "lt": amount < threshold,
        "le": amount <= threshold,
    }[boundary]


def _record(passage):
    if not passage.locator.startswith("csv:"):
        return None
    try:
        value = json.loads(passage.text)
        return value if isinstance(value, dict) else None
    except (ValueError, TypeError):
        return None


def assess_practice(
    claim: str, passages: list[Evidence], sources: dict[str, Source], as_of: date
) -> dict:
    expense = parse_expense_rule(claim)
    discount = parse_approval_rule(claim)
    result = {
        "status": "unsupported_rule",
        "findings": [],
        "examined_records": 0,
        "omitted_findings": 0,
        "notice": "Operational comparisons describe recorded events and reported departures, not independent verification or proof that a formal policy is invalid.",
    }
    if not expense and not discount:
        return result
    rule = expense or discount.model_dump()
    threshold = Decimal(rule.get("amount", rule.get("percentage")))
    findings = []
    for passage in sorted(passages, key=lambda p: p.evidence_id):
        row = _record(passage)
        source = sources.get(passage.source_id)
        if not row or source is None or source.ingestion_status != "ingested":
            continue
        if expense:
            if passage.source_type != "project_tasks" or not re.search(
                r"\bexpense\b", str(row.get("process_or_capability", "")), re.IGNORECASE
            ):
                continue
        elif passage.source_type != "crm_records":
            continue
        result["examined_records"] += 1
        notes = str(row.get("comments" if expense else "notes", ""))
        limitations = []
        scope_ok = bool(expense)
        amount_conflict = False
        if expense:
            # A currency-less amount is not assumed to use the claim's currency.
            raw_amount = row.get("expense_amount", row.get("amount"))
            amount = _number(raw_amount)
            currency = row.get("currency")
            amounts = re.findall(
                r"(?<![-\w])([$£€])((?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?)(?![0-9.,])",
                notes,
            )
            if amount is not None and amounts:
                amount_conflict = any(
                    symbol != currency or _number(value.replace(",", "")) != amount
                    for symbol, value in amounts
                )
                if amount_conflict:
                    limitations.append(
                        "Amounts in the structured fields and notes differ; review is required."
                    )
            if amount is None and len(amounts) == 1:
                currency, raw_amount = amounts[0]
                amount = _number(raw_amount.replace(",", ""))
            if amount is None or currency != rule["currency"]:
                continue
        else:
            amount = _number(row.get("discount_pct"))
            if amount is None or amount > 100:
                continue
            scope = (
                str(row.get("deal_scope", row.get("deal_type", ""))).casefold().replace(" ", "-")
            )
            expected = rule["deal_scope"].replace(" ", "-")
            if scope and scope != expected:
                continue
            scope_ok = scope == expected
            if not scope_ok:
                limitations.append(
                    "Deal scope is not explicitly recorded; applicability remains unresolved."
                )
            if row.get("discount_basis") != "list_price":
                scope_ok = False
                limitations.append("The discount price basis is not explicitly recorded.")
        if not _covered(amount, threshold, rule["boundary"]):
            continue
        event_field = "reimbursement_date" if expense else "close_date"
        event_date = _day(row.get(event_field))
        completion_date = _day(row.get("completion_date")) if expense else None
        if (event_date and event_date > as_of) or (completion_date and completion_date > as_of):
            continue
        if source.creation_date and source.creation_date > as_of:
            continue
        if source.metadata_conflicts:
            limitations.append("Source metadata conflicts require review.")
        if source.derived_from_source_id or source.duplicate_group:
            limitations.append(
                "This source has recorded dependency or duplication; it is not independent corroboration."
            )
        approval_date = _day(row.get("approval_date"))
        actual_role = row.get("approval_role", "")
        if expense:
            event_complete = str(row.get("payment_status", "")).casefold() == "reimbursed"
        else:
            event_complete = str(row.get("stage", "")).casefold() == "closed won"
        event_matches = bool(expense) or rule["event"] in {"closed won", "closed won in the crm"}
        complete = (
            scope_ok
            and event_matches
            and event_complete
            and event_date
            and rule["timing"] == "before"
        )
        status = "unresolved_record"
        reason = "The record falls within the claimed amount range, but approval, role or event-timing facts are incomplete."
        state, state_reason = approval_state(row)
        approval_conflict = (
            state == "conflicting"
            or bool(approval_date)
            and str(row.get("approval_status", "")).casefold() in {"not_requested", "rejected"}
        )
        if state != "approved":
            limitations.append(state_reason)
        if approval_date and approval_date > as_of:
            continue
        if approval_conflict:
            limitations.append("Approval status and approval date conflict; review is required.")
        if (
            complete
            and not source.metadata_conflicts
            and not amount_conflict
            and not approval_conflict
        ):
            if (
                state == "approved"
                and approval_date
                and approval_date > event_date
                and _role(actual_role) == _role(rule["approver"])
            ):
                status, reason = (
                    "recorded_departure",
                    "The record dates approval after the completed event, contrary to the claimed before-event requirement.",
                )
            elif not approval_date and str(row.get("approval_status", "")).casefold() in {
                "not_requested",
                "rejected",
            }:
                status, reason = (
                    "recorded_departure",
                    "The record explicitly reports a completed event with approval not requested or rejected.",
                )
            elif (
                state == "approved"
                and approval_date
                and approval_date < event_date
                and _role(actual_role) == _role(rule["approver"])
                and (not rule["written"] or row.get("written_approval") is True)
            ):
                status, reason = (
                    "recorded_consistent_event",
                    "The recorded approver and approval date agree with the rule for this event. One event does not establish universal compliance.",
                )
        if status == "unresolved_record":
            # Surface explicit alternate routing as a report, not a proven event violation.
            bypass = re.search(r"\brather than routing to\s+([^.!?]+)", notes, re.IGNORECASE)
            if bypass and not re.search(
                r"\b(if|would|will|not|never|planned)\b", notes, re.IGNORECASE
            ):
                status, reason = (
                    "reported_alternative_route",
                    "The record reports an alternative approval route: "
                    + bypass[0]
                    + ". Role equivalence and reimbursement timing still require review.",
                )
            elif not row.get("approval_record") and not actual_role and not approval_date:
                status, reason = (
                    "missing_approval_record",
                    "No approval record is supplied in the structured fields. This is a documentation gap, not proof that approval never occurred.",
                )
        if not event_date:
            limitations.append(
                f"No explicit {event_field} is recorded; task completion is not proof of reimbursement timing."
            )
        if approval_date and event_date and approval_date == event_date:
            limitations.append(
                "Same-day dates do not establish whether approval preceded the event."
            )
        if not source.creation_date:
            limitations.append(
                "Source creation date is missing; its availability at the assessment date is not established."
            )
        limitations.append(
            "Applicability of this requirement at the event date, source authenticity, exceptions and decision authority require separate evidence; this finding does not alter the formal-rule verdict."
        )
        findings.append(
            {
                "status": status,
                "reason": reason,
                "record_id": str(
                    row.get("task_id" if expense else "deal_id", passage.evidence_id)
                ),
                "source_title": source.title,
                "amount": str(amount),
                "required_approver": rule["approver"],
                "recorded_approver": str(actual_role),
                "event_date": event_date.isoformat() if event_date else None,
                "approval_date": approval_date.isoformat() if approval_date else None,
                "limitations": limitations,
                "citation": {
                    "evidence_id": passage.evidence_id,
                    "source_id": passage.source_id,
                    "locator": passage.locator,
                    "quotation": passage.text,
                    "start": 0,
                    "end": len(passage.text),
                },
            }
        )
    priority = {
        "recorded_departure": 0,
        "reported_alternative_route": 1,
        "recorded_consistent_event": 2,
        "missing_approval_record": 3,
        "unresolved_record": 4,
    }
    findings.sort(
        key=lambda f: (priority[f["status"]], f["record_id"], f["citation"]["evidence_id"])
    )
    result.update(
        status="compared" if findings else "no_comparable_records",
        findings=findings[:50],
        omitted_findings=max(0, len(findings) - 50),
    )
    return result
