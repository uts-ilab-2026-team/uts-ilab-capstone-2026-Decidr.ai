"""Citation-backed field comparisons for explicitly identified approval events.

These describe what linked records establish, separately from source credibility.
No policy adoption right, event time or foreign-key connection is inferred.
"""

from datetime import date
from decimal import Decimal, InvalidOperation
import json
import re

from decidr.retrieval import find_record_references

_ID = r"[A-Za-z][A-Za-z0-9]*(?:-[0-9]+)+"
_PERSON = r"[A-Za-zÀ-ž][A-Za-zÀ-ž'’-]*(?: [A-Za-zÀ-ž][A-Za-zÀ-ž'’-]*){0,4}?"
_ACTION = rf"(?P<approver>{_PERSON}) (?:approved|authorised|authorized) (?:a |the )?(?P<percentage>\d+(?:\.\d+)?)\s*(?:%|percent|per cent) discount"


def parse_transaction_claim(text):
    text = " ".join(text.strip().rstrip(".").split())
    if re.search(
        r"\b(?:in principle|subject to|if|unless|allegedly|possibly)\b", text, re.IGNORECASE
    ):
        return None
    timing = re.search(
        r" before (?:(?:the )?contract (?:was |is )?signed|signing)$", text, re.IGNORECASE
    )
    if timing:
        text = text[: timing.start()]
    channel = None
    record_id = ""
    # Extract only complete syntactic modifiers; leftover assertions must still
    # match the whole approval sentence, so compound/unsupported claims abstain.
    prefix = re.match(rf"(?:For |On )?({_ID})[,:]? ", text, re.IGNORECASE)
    if prefix:
        record_id, text = prefix[1].upper(), text[prefix.end() :]
    for _ in range(2):
        record = re.search(rf" (?:for|on) ({_ID})$", text, re.IGNORECASE)
        channel_match = re.search(
            r" (?:on|via|in|over) ([A-Za-z][A-Za-z0-9_-]*)$", text, re.IGNORECASE
        )
        if record:
            if record_id:
                return None
            record_id, text = record[1].upper(), text[: record.start()]
        elif channel_match:
            if channel:
                return None
            channel, text = channel_match[1], text[: channel_match.start()]
        else:
            break
    passive = rf"(?:the |a )?(?P<percentage>\d+(?:\.\d+)?)\s*(?:%|percent|per cent) discount(?: for (?P<record_id>{_ID}))? (?:was |is )?(?:approved|authorised|authorized) by (?P<approver>{_PERSON})"
    for pattern in (_ACTION, passive):
        match = re.fullmatch(pattern, text, re.IGNORECASE)
        if not match or Decimal(match["percentage"]) > 100:
            continue
        if re.search(
            r"\b(not|never|if|unless|possibly|allegedly|before|after|signing)\b",
            match["approver"],
            re.IGNORECASE,
        ):
            continue
        embedded_id = match.groupdict().get("record_id")
        if record_id and embedded_id:
            return None
        return {
            "record_id": record_id or (embedded_id or "").upper(),
            "approver": match["approver"],
            "percentage": match["percentage"],
            "before_signing": bool(timing),
            **({"channel": channel} if channel else {}),
        }
    return None


def _row(passage):
    try:
        value = json.loads(passage.text)
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}


def _name(value):
    return re.sub(r"\s*\([^)]*\)\s*$", "", str(value)).strip().casefold()


def _date(value):
    try:
        return date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _deal_scope(value):
    value = re.sub(r"[-_\s]+", " ", str(value)).strip().casefold()
    value = re.sub(r" deals?$", "", value)
    return {"new business": "new business", "renewal": "renewal", "renewals": "renewal"}.get(value)


def approval_state(row):
    """Compare completion assertions, without treating documentation gaps as negations."""
    status = re.sub(r"[_-]+", " ", str(row.get("approval_status", ""))).strip().casefold()
    positive_status = status in {"approved", "authorised", "authorized", "granted"}
    negative_status = status in {"not approved", "rejected", "denied", "declined"}
    pending_status = status in {
        "pending",
        "awaiting approval",
        "awaiting sign off",
        "requested",
        "not requested",
        "in progress",
    }
    person = _name(row.get("approval_role", ""))
    actor = r"(?:" + re.escape(person) + "|" + re.escape(person.split(" ")[0]) + r")"
    affirmative, negative, qualified = False, False, False
    reference = str(row.get("approval_record", "")).strip()
    notes = str(row.get("notes", row.get("comments", ""))).strip()
    reference_assertion = re.fullmatch(
        r"(?:approved|authori[sz]ed|approval granted)(?: (?:via|in|by|on) .+)?[.!]?",
        reference,
        re.IGNORECASE,
    )
    if (
        reference_assertion
        and re.match(r"(?:approved|authori[sz]ed) by ", reference, re.IGNORECASE)
        and (
            not person
            or not re.match(
                r"(?:approved|authori[sz]ed) by " + actor + r"(?=\s*$|[.,;]|\s+(?:on|via)\b)",
                reference,
                re.IGNORECASE,
            )
        )
    ):
        return (
            "conflicting",
            "The approval reference and recorded approver do not identify the same person.",
        )
    # Only an approval assertion's own clause supplies its polarity. A separate
    # 'never logged in CRM' clause concerns documentation, not whether approval occurred.
    clauses = [(reference, bool(reference_assertion))] + [
        (clause, False) for clause in re.split(r"\s+[—–]\s+|[;\n]|(?<=[.!?])\s+", notes)
    ]
    for clause, reference_positive in clauses:
        relevant = bool(
            re.search(r"\b(approv\w*|authori[sz]\w*|sign[ -]?off)\b", clause, re.IGNORECASE)
        )
        if not relevant:
            continue
        documentation_only = re.search(
            r"\b(?:crm|logged|recorded)\b|\bapproval (?:record|field|entry)\b",
            clause,
            re.IGNORECASE,
        ) and not re.search(
            r"\b(?:approve|approved|authori[sz]ed|authori[sz]e)\b|\bapproval (?:was |is )?(?:pending|denied|rejected|granted|not granted)\b",
            clause,
            re.IGNORECASE,
        )
        if documentation_only:
            continue
        denied = bool(
            re.fullmatch(
                r"\s*(?:not approved|never approved|approval (?:was |is )?(?:denied|rejected|not granted))[.!]?\s*",
                clause,
                re.IGNORECASE,
            )
            or (
                person
                and (
                    re.search(
                        r"\b(?:not|never) (?:approved|authori[sz]ed) by "
                        + actor
                        + r"(?=\s*$|[.,;]|\s+(?:via|on|over|in)\b)",
                        clause,
                        re.IGNORECASE,
                    )
                    or re.match(
                        r"\s*" + actor + r" (?:did|does) not (?:approve|authori[sz]e)\b",
                        clause,
                        re.IGNORECASE,
                    )
                )
            )
        )
        conditional = bool(
            re.search(
                r"\b(if|unless|would|could|might|may|awaiting|pending|requested|requesting|proposed|unconfirmed|unverified|conditional|conditionally|provisional|provisionally|draft|allegedly|said|reported|claims)\b|\b(in principle|subject to)\b",
                clause,
                re.IGNORECASE,
            )
        )
        positive = reference_positive or bool(
            person
            and (
                re.search(
                    r"\b(?:approved|authori[sz]ed) by "
                    + actor
                    + r"(?=\s*[.,;]|\s*$|\s+(?:via|on|over|in)\b)",
                    clause,
                    re.IGNORECASE,
                )
                or re.match(
                    r"\s*" + actor + r" (?:approved|authori[sz]ed)\b", clause, re.IGNORECASE
                )
            )
        )
        negative |= denied
        qualified |= conditional or (
            bool(re.search(r"\b(not|never|no)\b", clause, re.IGNORECASE)) and not denied
        )
        affirmative |= positive and not denied and not conditional
    if (affirmative or positive_status) and (
        negative or negative_status or pending_status or qualified
    ):
        return (
            "conflicting",
            "The record contains inconsistent or qualified approval assertions; review is required.",
        )
    if negative_status or negative:
        return "denied", "The record explicitly denies completed approval."
    if pending_status:
        return (
            "pending",
            "Approval is requested, pending or awaiting sign-off; completion is not established.",
        )
    if status and not positive_status:
        return "unresolved", "The approval status is not recognised as completed approval."
    if qualified:
        return "unresolved", "The approval assertion is qualified or unverified."
    if positive_status or affirmative:
        return "approved", "The record explicitly asserts completed approval."
    return (
        "unresolved",
        "An approval reference, approver name or date alone does not establish completed approval.",
    )


def assess_transaction_claim(claim, passages, sources, as_of, scope_answer=None):
    fields = parse_transaction_claim(claim)
    if fields is None:
        return None
    names = {_name(_row(p).get("approval_role", "")) for p in passages}
    wanted = fields["approver"].casefold()
    matching_names = {name for name in names if name == wanted or name.startswith(wanted + " ")}
    candidates = set()
    inferred = not fields["record_id"]
    if inferred:
        for passage in passages:
            row = _row(passage)
            name = _name(row.get("approval_role", ""))
            source = sources.get(passage.source_id)
            if (
                not source
                or source.ingestion_status != "ingested"
                or source.metadata_conflicts
                or (source.creation_date and source.creation_date > as_of)
            ):
                continue
            if any(
                day and day > as_of
                for day in (
                    _date(row.get("approval_date")),
                    _date(row.get("close_date")),
                    _date(row.get("contract_signed_date")),
                    _date(row.get("signed_date")),
                )
            ):
                continue
            try:
                same_amount = Decimal(str(row.get("discount_pct"))) == Decimal(
                    fields["percentage"]
                )
            except InvalidOperation:
                same_amount = False
            if same_amount and (
                name == wanted or (len(matching_names) == 1 and name in matching_names)
            ):
                record_id = str(row.get("deal_id", "")).upper()
                if re.fullmatch(_ID, record_id):
                    candidates.add(record_id)
    record_id = fields["record_id"] or (next(iter(candidates)) if len(candidates) == 1 else "")
    refs = [
        ref
        for key in ([record_id] if record_id else sorted(candidates))
        for ref in find_record_references(key, passages)
    ]
    links = {ref.evidence_id: ref for ref in refs}
    observations = {"discount": [], "approval": [], "timing": [], "channel": [], "scope": []}
    citations, connections = [], []
    approval_dates, signing_dates = {}, {}
    scoped = scope_answer is not None and scope_answer.strip().casefold() != "all deal types"
    expected_scope = _deal_scope(scope_answer) if scoped else None
    eligible_ids = []
    for passage in passages:
        if passage.evidence_id not in links:
            continue
        source = sources.get(passage.source_id)
        if not source or source.ingestion_status != "ingested":
            continue
        citation = {
            "evidence_id": passage.evidence_id,
            "source_id": passage.source_id,
            "locator": passage.locator,
            "quotation": passage.text,
            "start": 0,
            "end": len(passage.text),
        }
        citations.append(citation)
        connections.append(
            {
                "evidence_id": passage.evidence_id,
                "relationship": links[passage.evidence_id].relationship
                if record_id
                else "candidate_transaction_not_selected",
            }
        )
        row = _row(passage)
        # A passage mentioning multiple entities cannot transfer its fields to this one.
        row_id = str(
            row.get("deal_id", row.get("related_record", passage.row_identifier or ""))
        ).upper()
        if row_id != record_id:
            continue
        if source.metadata_conflicts or (source.creation_date and source.creation_date > as_of):
            continue
        if any(
            day and day > as_of
            for day in (
                _date(row.get("approval_date")),
                _date(row.get("contract_signed_date")),
                _date(row.get("signed_date")),
                _date(row.get("close_date")),
            )
        ):
            continue

        def add(component, status, reason, evidence_id=passage.evidence_id):
            observations[component].append(
                {"status": status, "reason": reason, "evidence_id": evidence_id}
            )

        eligible_ids.append(passage.evidence_id)
        if scoped:
            for key in ("deal_scope", "deal_type"):
                value = row.get(key)
                if value is None or not str(value).strip():
                    continue
                recorded_scope = _deal_scope(value)
                if expected_scope is None or recorded_scope is None:
                    scope_status = "unresolved"
                    reason = (
                        f"The linked record gives {key} as {value!r}; comparison with the "
                        f"selected scope {scope_answer!r} requires review."
                    )
                else:
                    scope_status = (
                        "supported" if recorded_scope == expected_scope else "contradicted"
                    )
                    reason = (
                        f"The linked record explicitly gives {key} as {value!r}, which "
                        f"{'matches' if scope_status == 'supported' else 'differs from'} "
                        f"the selected scope {scope_answer!r}."
                    )
                add("scope", scope_status, reason)

        try:
            amount = Decimal(str(row.get("discount_pct")))
            if amount.is_finite() and 0 <= amount <= 100:
                same = amount == Decimal(fields["percentage"])
                add(
                    "discount",
                    "supported" if same else "contradicted",
                    f"The linked record specifies a {amount}% discount.",
                )
        except InvalidOperation:
            pass
        signed = _date(row.get("contract_signed_date", row.get("signed_date")))
        if signed:
            signing_dates.setdefault(signed, []).append(passage.evidence_id)
        name = _name(row.get("approval_role", ""))
        actor_matches = name == wanted or (len(matching_names) == 1 and name in matching_names)
        state, state_reason = approval_state(row)
        if actor_matches and state in {"denied", "conflicting"}:
            add("approval", "contradicted" if state == "denied" else "conflicting", state_reason)
        elif actor_matches and state == "approved":
            add(
                "approval",
                "supported",
                f"The record identifies {row.get('approval_role')}. {state_reason}",
            )
            if fields.get("channel"):
                channel = fields["channel"]
                reference = str(row.get("approval_record", "")).strip()
                reported = str(row.get("approval_channel", "")).strip()
                channel_match = re.fullmatch(
                    r"(?:Recorded outside CRM \(([^()]+)\)|(?:Approved|Authorised|Authorized) (?:via|on|in) ([A-Za-z][A-Za-z0-9_-]*))[.!]?",
                    reference,
                    re.IGNORECASE,
                )
                if not reported and channel_match:
                    reported = next(value for value in channel_match.groups() if value)
                add(
                    "channel",
                    "supported" if reported.casefold() == channel.casefold() else "unresolved",
                    f"The record reports the approval channel as {reported}. The original message has not been verified."
                    if reported
                    else "The approval channel is not explicitly established by the linked record.",
                )
            if fields["before_signing"]:
                approved = _date(row.get("approval_date"))
                if approved:
                    approval_dates.setdefault(approved, []).append(passage.evidence_id)
        elif name:
            add(
                "approval",
                "unresolved",
                "The named approver or completed approval cannot be matched unambiguously. "
                + state_reason,
            )

    if scoped and not observations["scope"]:
        observations["scope"] = [
            {
                "status": "unresolved",
                "reason": (
                    f"The linked record does not explicitly identify its deal type as {scope_answer!r}. "
                    "Customer segment, sales stage and policy wording do not establish the deal type."
                ),
                "evidence_id": key,
            }
            for key in eligible_ids
        ]

    if fields["before_signing"]:
        timing_ids = list(
            dict.fromkeys(
                [key for values in approval_dates.values() for key in values]
                + [key for values in signing_dates.values() for key in values]
            )
        )
        status, reason = (
            "unresolved",
            "Explicit approval and contract signing dates are needed for the same transaction. CRM close dates do not establish signing.",
        )
        if len(approval_dates) == len(signing_dates) == 1:
            approved, signed = next(iter(approval_dates)), next(iter(signing_dates))
            if approved != signed:
                status = "supported" if approved < signed else "contradicted"
                reason = f"Explicitly linked records give approval date {approved} and contract signing date {signed}."
            else:
                reason = (
                    "Same-day dates do not establish whether approval preceded contract signing."
                )
        elif len(approval_dates) > 1 or len(signing_dates) > 1:
            reason = "Multiple approval or signing dates are recorded. The intended approval and signing events cannot be selected unambiguously."
        observations["timing"] = [
            {"status": status, "reason": reason, "evidence_id": key} for key in timing_ids
        ]

    components = []
    labels = {
        "discount": "Discount percentage",
        "approval": "Named approver and approval",
        "timing": "Approval before contract signing",
        "channel": "Recorded approval channel",
        "scope": "Selected deal scope",
    }
    for key, items in observations.items():
        if key == "channel" and not fields.get("channel"):
            continue
        if key == "scope" and not scoped:
            continue
        if key == "timing" and not fields["before_signing"]:
            continue
        states = {item["status"] for item in items}
        status = (
            "conflicting"
            if "conflicting" in states or {"supported", "contradicted"} <= states
            else "contradicted"
            if "contradicted" in states
            else "unresolved"
            if key == "scope" and "unresolved" in states
            else "supported"
            if "supported" in states
            else "unresolved"
        )
        components.append(
            {"field": key, "label": labels[key], "status": status, "observations": items}
        )
    states = {c["status"] for c in components}
    status = (
        "conflicting_records"
        if "conflicting" in states
        else "contradicted_by_records"
        if "contradicted" in states
        else "supported_by_records"
        if states == {"supported"}
        else "partially_supported"
        if "supported" in states
        else "unresolved"
    )
    next_steps = []
    if inferred and not record_id:
        next_steps.append("Supply the deal number to identify the intended transaction.")
    if any(c["field"] == "timing" and c["status"] == "unresolved" for c in components):
        next_steps.append(
            "Locate the original approval and signed contract for this record, with the approver identity and timestamps, to resolve timing."
        )
    if any(c["field"] == "scope" and c["status"] != "supported" for c in components):
        next_steps.append(
            f"Review an explicit deal-type field or linked record for {record_id or 'the intended transaction'} "
            f"to establish whether the selected scope {scope_answer!r} applies."
        )
    return {
        "status": status,
        "record_id": record_id or "Unidentified transaction",
        "candidate_record_ids": sorted(candidates),
        "record_resolution": "unique_actor_amount_match"
        if inferred and record_id
        else "ambiguous_or_missing"
        if inferred
        else "explicit_id",
        "claim_fields": fields,
        "components": components,
        "citations": citations,
        "connections": connections,
        "notice": (
            "The deal number was not supplied; the record was selected by a unique approver and discount match. "
            if inferred and record_id
            else "Multiple or no matching transactions: supply a deal number to identify the event. "
            if inferred
            else ""
        )
        + "This compares the claim with linked records. It does not independently verify source authenticity, approver authority or independence. Human review remains pending.",
        "next_step": " ".join(next_steps)
        or "Review the linked evidence and any conflicting records.",
    }


def transaction_conclusion(transaction):
    """Summarise the recorded claim comparison, never rewrite credibility scores."""
    if not transaction:
        return None
    labels = {
        "supported_by_records": "Supported by the available record",
        "partially_supported": "Partially supported by the available records",
        "contradicted_by_records": "Contradicted by the available records",
        "conflicting_records": "Conflicting records",
        "unresolved": "Not established by the available records",
    }
    status = transaction["status"]
    supported = [c["label"] for c in transaction["components"] if c["status"] == "supported"]
    unresolved = [c["label"] for c in transaction["components"] if c["status"] == "unresolved"]
    disputed = [
        c["label"]
        for c in transaction["components"]
        if c["status"] in {"contradicted", "conflicting"}
    ]
    sentences = []
    if supported:
        sentences.append("The linked record supports: " + "; ".join(supported) + ".")
    if unresolved:
        sentences.append("Not established: " + "; ".join(unresolved) + ".")
    if disputed:
        sentences.append(
            "Contradictory or conflicting recorded evidence: " + "; ".join(disputed) + "."
        )
    return {
        "status": status,
        "label": labels.get(status, labels["unresolved"]),
        "summary": " ".join(sentences),
        "basis": "recorded_event_comparison",
        "notice": "This assesses what the linked records say, not independently verified truth or policy compliance. Human review is pending.",
    }
