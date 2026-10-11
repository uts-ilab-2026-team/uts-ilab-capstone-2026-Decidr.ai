"""Canonical, citation-validated aggregation of interpreted claim components.

Confidence is a disclosed heuristic of the evidence supporting the assessment,
not a probability that the claim is true or a statistically calibrated estimate.
"""

from datetime import date
import json
import re

from decidr.claim_interpreter import approval_boundary_exclusion
from decidr.source_metadata import DOCUMENT_REFERENCE, HEADER, approval_lifecycle, approval_signals
from decidr.transaction_claims import approval_state

SCHEMA_VERSION = "canonical-assessment-v1"
CONFIDENCE_METHOD = "assessment-evidence-quality-v1"
TARGETS = {
    "formal_requirement",
    "formal_authority",
    "event",
    "observed_practice",
    "reported_statement",
    "value_accuracy",
    "current_state",
    "historical_state",
}
RELATIONSHIPS = {"supports", "contradicts", "qualifies", "context", "unresolved"}
BASES = {
    "direct_statement",
    "recorded_action",
    "reported_statement",
    "independent_validation",
    "contextual",
}
OUTCOMES = {
    "supported": "Supported",
    "contradicted": "Contradicted",
    "partially_supported": "Partially supported",
    "conflicting": "Conflicting evidence",
    "insufficient": "Insufficient evidence",
}
WEIGHTS = {
    "coverage": 0.25,
    "directness": 0.15,
    "temporal_fit": 0.10,
    "scope_fit": 0.10,
    "source_quality": 0.15,
    "independence": 0.10,
    "agreement": 0.05,
    "interpretation_clarity": 0.10,
}
CONFIDENCE_BASIS = [
    "Coverage: proportion of components with admitted support or contradiction; qualifications alone do not establish a component.",
    "Directness, temporal fit and scope fit: proportions of unique admitted findings rated direct or explicitly applicable.",
    "Source quality: proportion of observable source checks satisfied (ingested, no metadata conflicts, named author/system, creation date known). These checks do not verify authenticity or authority.",
    "Independence: independently verified distinct origins, capped at two; copied passages and linked source lineage never add independent corroboration. Unverified independence contributes zero to this factor.",
    "Agreement: larger supporting/contradicting origin group divided by both groups; contradictions remain visible even when they lower agreement.",
    "Interpretation clarity: 1 / (1 + material claim interpretation ambiguities + unique unresolved evidence passages for the component). Repeated or copied unresolved text counts once. No provider confidence or retrieval similarity is used.",
    "The disclosed weighted mean is an uncalibrated assessment-confidence score, not a probability that the claim is true. A well-evidenced contradiction can receive a high score.",
]


class InvalidAssessment(ValueError):
    pass


def _dict(value):
    return value.model_dump(mode="python") if hasattr(value, "model_dump") else dict(value)


def _day(value):
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _component_date(component, as_of):
    temporal = component.get("temporal")
    if isinstance(temporal, dict):
        return _day(temporal.get("as_of", temporal.get("date"))) or as_of
    dates = set(re.findall(r"\b\d{4}-\d{2}-\d{2}\b", str(temporal or "")))
    return _day(next(iter(dates))) or as_of if len(dates) == 1 else as_of


def processing_failure(code, message, *, interpretation=None, diagnostics=None, provenance=None):
    if not (
        isinstance(interpretation, dict)
        and interpretation.get("target") in TARGETS
        and isinstance(interpretation.get("components"), list)
        and all(
            isinstance(component, dict)
            and all(isinstance(component.get(key), str) for key in ("id", "text", "claim_quote"))
            and isinstance(component.get("entities"), list)
            and isinstance(component.get("quantities"), list)
            and isinstance(component.get("scope"), list)
            for component in interpretation["components"]
        )
        and isinstance(interpretation.get("ambiguities"), list)
    ):
        interpretation = None
    return {
        "schema_version": SCHEMA_VERSION,
        "processing": {"status": "failed", "code": code, "message": message},
        "interpreted_claim": interpretation,
        "components": [],
        "overall_outcome": None,
        "summary": message,
        "confidence": {
            "score": None,
            "method": CONFIDENCE_METHOD,
            "label": "Not assessed",
            "calibrated": False,
            "meaning": "No assessment confidence is available for a processing failure.",
            "basis": [],
            "components": [],
            "weights": WEIGHTS.copy(),
        },
        "unresolved_questions": [],
        "evidence_relations": [],
        "citations": [],
        "diagnostics": diagnostics or {},
        "provenance": provenance or {},
    }


def _citation(finding, evidence, sources):
    evidence_id, source_id = finding.get("evidence_id"), finding.get("source_id")
    if evidence_id not in evidence or source_id not in sources:
        raise InvalidAssessment(
            "A finding cites evidence or a source outside the selected corpus snapshot."
        )
    passage = evidence[evidence_id]
    quotation = finding.get("quotation")
    if (
        passage.get("source_id") != source_id
        or not isinstance(quotation, str)
        or not quotation.strip()
    ):
        raise InvalidAssessment("A finding has a mismatched source or an empty citation.")
    start = passage["text"].find(quotation)
    if start < 0:
        raise InvalidAssessment("A quotation is not an exact substring of the cited evidence.")
    # Provider offsets and locators are never trusted; reconstruct from the frozen passage.
    return {
        "evidence_id": evidence_id,
        "source_id": source_id,
        "locator": passage["locator"],
        "quotation": quotation,
        "start": start,
        "end": start + len(quotation),
    }


def _ownership_metadata_only(text):
    if re.fullmatch(r"\s*[-*\s]*document owner[:*\s]+[^\n]+", text, re.IGNORECASE):
        return True
    metadata_keys = {
        "document owner",
        "owner",
        "version",
        "approval status",
        "effective date",
        "review date",
        "supersedes",
        "applicable to",
        "related documents",
        "creation date",
        "last updated",
    }
    keys = []
    for line in text.splitlines():
        if not line.strip() or re.match(r"^#{1,6}\s", line):
            continue
        match = HEADER.fullmatch(line.strip())
        if not match or match["key"].strip().casefold() not in metadata_keys:
            return False
        keys.append(match["key"].strip().casefold())
    return bool({"document owner", "owner"}.intersection(keys))


def _formal_temporal_basis(finding, component, target, source, evidence, sources, as_of):
    """Resolve document applicability only from exact, directly sourced header evidence."""
    if (
        finding["time_fit"] == "no"
        or target not in {"formal_requirement", "formal_authority"}
        or source.get("source_type")
        not in {"policy", "procedure", "role_description", "organisational_information"}
        or source.get("lifecycle_status") != "current"
        or source.get("ingestion_status") != "ingested"
        or source.get("metadata_conflicts")
        or source.get("superseded_date")
        or source.get("successor_source_id")
        or source.get("effective_end_date")
    ):
        return None
    start = _day(source.get("effective_start_date"))
    provenance = source.get("metadata_provenance", {})
    if not start or not all(
        str(provenance.get(key, "")).startswith("direct:")
        for key in ("effective_date", "approval_status")
    ):
        return None
    temporal = component.get("temporal") or ""
    if not isinstance(temporal, str):
        return None
    normalized = temporal.strip().lower()
    if normalized in {"", "current", "currently", "present", "now", "as of assessment date"}:
        assessed_date = as_of
        # A missing temporal extraction must not silently erase a historical assertion.
        claim_words = component.get("claim_quote", "") + " " + component.get("text", "")
        if re.search(
            r"\b(?:historical|formerly|previously|last year|last month|in \d{4}|\d{4}-\d{2}-\d{2})\b",
            claim_words,
            re.IGNORECASE,
        ):
            return None
    elif re.fullmatch(r"(?:(?:as of|as at|on|at)\s+)?\d{4}-\d{2}-\d{2}", normalized):
        assessed_date = _day(normalized[-10:])
    else:
        return None
    creation = _day(source.get("creation_date"))
    if (
        not assessed_date
        or not start <= assessed_date <= as_of
        or (creation and creation > assessed_date)
    ):
        return None
    headers = source.get("header_evidence", [])
    citations = []
    for key, value in (
        ("effective date", start.isoformat()),
        ("approval status", source.get("approval_status")),
    ):
        matches = [h for h in headers if h.get("key") == key]
        if len(matches) != 1:
            return None
        header = matches[0]
        if (
            header.get("scope") != "document_header"
            or header.get("source_id") != source["source_id"]
            or header.get("value") != value
            or not isinstance(header.get("quote"), str)
        ):
            return None
        parsed = HEADER.fullmatch(header["quote"])
        if (
            not parsed
            or parsed["key"].strip().casefold() != key
            or parsed["value"].strip() != value
        ):
            return None
        if key == "approval status":
            code = DOCUMENT_REFERENCE.match(source.get("title", ""))
            lifecycle, clauses, conflicts = approval_lifecycle(value, code[0] if code else "")
            own = [c for c in clauses if c["scope"] == "own_document"]
            if (
                lifecycle != "current"
                or conflicts
                or not own
                or any(c["lifecycle"] != "current" for c in own)
            ):
                return None
        passage = next(
            (
                p
                for p in evidence.values()
                if p["source_id"] == source["source_id"] and header["quote"] in p["text"]
            ),
            None,
        )
        if passage is None:
            return None
        citations.append(
            _citation(
                {
                    "source_id": source["source_id"],
                    "evidence_id": passage["evidence_id"],
                    "quotation": header["quote"],
                },
                evidence,
                sources,
            )
        )
    return {
        "method": "formal-header-applicability-v1",
        "assessed_date": assessed_date.isoformat(),
        "effective_start_date": start.isoformat(),
        "reason": "Exact source headers record approval and an effective date on or before the assessed date; the frozen source has no recorded end date, supersession or metadata conflict. This establishes document-date applicability only, not scope, authority or actual compliance.",
        "citations": citations,
    }


def _guard(finding, component, target, passage, source, as_of):
    relationship = finding["relationship"]
    reasons = []
    effective_date = _component_date(component, as_of)
    if source.get("ingestion_status") != "ingested":
        reasons.append("The source is not successfully ingested.")
    if source.get("metadata_conflicts"):
        reasons.append("Source metadata conflicts require review.")
    if any(
        day and day > as_of
        for day in (_day(source.get("creation_date")), _day(passage.get("relevant_start_date")))
    ):
        reasons.append("This evidence is dated after the assessment date.")
    current = target in {
        "current_state",
        "observed_practice",
        "formal_requirement",
        "formal_authority",
    }
    if current or target == "historical_state":
        start, end = (
            _day(source.get("effective_start_date")),
            _day(source.get("effective_end_date")),
        )
        if start and start > effective_date:
            reasons.append("The source is not yet effective for the assessed date.")
        if end and end < effective_date:
            reasons.append("The source's effective period ended before the assessed date.")
        superseded = _day(source.get("superseded_date"))
        if superseded and superseded <= effective_date:
            reasons.append("The source was superseded by the assessed date.")
        elif source.get("lifecycle_status") == "superseded" and not (
            target == "historical_state" and superseded and superseded > effective_date
        ):
            reasons.append(
                "Superseded documentation cannot establish this state at the assessed date."
            )
    # Review dates schedule review; they are deliberately never used as expiry dates.
    if target in {"formal_requirement", "formal_authority"} and source.get("lifecycle_status") in {
        "draft",
        "proposed",
    }:
        reasons.append(
            "A draft or proposed document does not establish an adopted requirement or right."
        )
    if target in {"formal_requirement", "formal_authority"}:
        code = DOCUMENT_REFERENCE.match(source.get("title", ""))
        _, approval_clauses, _ = approval_lifecycle(
            source.get("approval_status"), code[0] if code else ""
        )
        own_clauses = [c for c in approval_clauses if c["scope"] == "own_document"]
        own_approval = " ".join(c["quote"] for c in own_clauses)
        negative, _ = approval_signals(own_approval)
        pending = re.search(
            r"^\s*pending\s*[.!]?\s*$|\bpending (?:formal |board )?approval\b|"
            r"\bapproval (?:is )?pending\b|\bawaiting (?:approval|adoption|sign[ -]?off)\b",
            own_approval,
            re.IGNORECASE,
        )
        if (
            negative
            or pending
            or any(c["lifecycle"] in {"draft", "withdrawn", "superseded"} for c in own_clauses)
        ):
            reasons.append(
                "The source's own approval status is unapproved, pending, draft or withdrawn; "
                "it does not establish an effective formal requirement or right."
            )
    if finding["scope_fit"] == "no":
        reasons.append("The passage concerns a different scope.")
    if finding["time_fit"] == "no":
        reasons.append("The passage does not apply to the claimed time.")
    source_type = source.get("source_type", passage.get("source_type"))
    if target in {"observed_practice", "current_state"} and source_type in {"policy", "procedure"}:
        reasons.append(
            "A documented rule or procedure alone does not establish current observed practice."
        )
    if target in {"formal_requirement", "formal_authority"} and (
        source_type == "interview"
        or finding.get("basis") in {"recorded_action", "reported_statement"}
    ):
        reasons.append(
            "Interview reports and recorded actions do not by themselves establish a documented formal requirement or grant of authority."
        )
    if finding.get("basis") == "contextual" and relationship in {
        "supports",
        "contradicts",
        "qualifies",
    }:
        reasons.append(
            "A contextual relationship is background; it does not establish, refute or qualify the claimed component."
        )
    if target == "formal_authority" and _ownership_metadata_only(finding["quotation"]):
        reasons.append(
            "Document ownership alone does not establish approval or delegation rights."
        )
    if (
        target == "value_accuracy"
        and relationship == "supports"
        and finding.get("basis") != "independent_validation"
    ):
        reasons.append(
            "A stored value or approval event does not validate numerical accuracy; independent validation is required."
        )
    try:
        row = json.loads(passage["text"])
    except (ValueError, TypeError):
        row = {}
    if isinstance(row, dict) and target in {"event", "current_state", "observed_practice"}:
        predicate = component.get("predicate", "")
        component_words = predicate + " " + component["text"]
        approval_predicate = re.search(
            r"\b(?:approv(?:e[ds]?|al)|authori[sz](?:ed|ation)|sign(?:ed)?[ -]?off)\b",
            predicate,
            re.IGNORECASE,
        ) and not re.search(
            r"\b(?:amount|value|quantity|percentage|rate|threshold|duration|timing)\b",
            predicate,
            re.IGNORECASE,
        )
        completed_approval = re.search(
            r"\b(?:approved|authori[sz]ed|signed[ -]?off)\b|"
            r"\b(?:received|obtained|gave|granted|completed)\s+(?:\w+\s+)?approval\b|"
            r"\bapproval\s+(?:was\s+|is\s+)?(?:granted|completed)\b",
            component_words,
            re.IGNORECASE,
        )
        pending_or_negative = component.get("polarity") in {"negative", "negated"} or re.search(
            r"\b(?:not|never|pending|awaiting|requested|requesting|planned|proposed|scheduled)\b",
            component_words,
            re.IGNORECASE,
        )
        if (
            target == "event"
            and relationship == "supports"
            and approval_predicate
            and completed_approval
            and not pending_or_negative
            and {
                "approval_status",
                "approval_record",
                "approval_role",
                "approval_date",
            }.intersection(row)
        ):
            approval, approval_reason = approval_state(row)
            if approval != "approved":
                reasons.append(f"The structured approval state is {approval}: {approval_reason}")
        date_only_approval = row.get("approval_date")
        signing_dates = [row.get("signed_date"), row.get("contract_signed_date")]
        order_component = approval_predicate or re.search(
            r"\b(?:before|after|preceded|followed|timing|order)\b", predicate, re.IGNORECASE
        )
        if (
            target == "event"
            and relationship in {"supports", "contradicts"}
            and order_component
            and not pending_or_negative
            and re.search(
                r"\b(?:before|after|preceded|followed)\b", component_words, re.IGNORECASE
            )
            and re.search(r"\b(?:approv\w*|authori[sz]\w*)\b", component_words, re.IGNORECASE)
            and re.search(r"\b(?:signing|signature|signed)\b", component_words, re.IGNORECASE)
            and isinstance(date_only_approval, str)
            and re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_only_approval)
            and _day(date_only_approval)
            and date_only_approval in signing_dates
        ):
            reasons.append(
                "Approval and signing have the same date without timestamps; these dates establish neither before nor after."
            )
        event_dates = [
            _day(str(row.get(key, ""))[:10])
            for key in (
                "timestamp",
                "event_date",
                "approval_date",
                "completion_date",
                "completed_date",
                "contract_signed_date",
                "signed_date",
                "close_date",
                "reimbursement_date",
                "recorded_at",
            )
        ]
        if any(day and day > as_of for day in event_dates):
            reasons.append("The linked record dates this event after the assessment date.")
        state = (
            str(row.get("status", row.get("task_status", row.get("state", "")))).strip().casefold()
        )
        asserted_plan = re.search(
            r"\b(planned|proposed|pending|awaiting|scheduled)\b", component["text"], re.IGNORECASE
        )
        if (
            state
            in {
                "planned",
                "proposed",
                "pending",
                "awaiting approval",
                "in progress",
                "not started",
            }
            and not asserted_plan
            and relationship == "supports"
            and component.get("polarity") not in {"negative", "negated"}
        ):
            reasons.append(
                "A proposed or unfinished task does not establish a completed event or current implementation."
            )
    boundary_exclusion = approval_boundary_exclusion(component, finding, target)
    if boundary_exclusion:
        reasons.append(boundary_exclusion)
    if reasons and relationship in {"supports", "contradicts", "qualifies"}:
        relationship = "context"
    if relationship in {"supports", "contradicts"} and (
        finding["scope_fit"] == "unknown" or finding["time_fit"] == "unknown"
    ):
        relationship = "unresolved" if relationship == "contradicts" else "qualifies"
        reasons.append("Material scope or temporal applicability remains unresolved.")
    return relationship, reasons


def _outcome(findings):
    relationships = {f["relationship"] for f in findings}
    if {"supports", "contradicts"} <= relationships:
        return "conflicting"
    if "contradicts" in relationships:
        return "contradicted"
    if "supports" in relationships and not ({"qualifies", "unresolved"} & relationships):
        return "supported"
    if "supports" in relationships:
        return "partially_supported"
    return "insufficient"


def _lineage(source_id, sources):
    path, positions = [], {}
    while source_id in sources:
        if source_id in positions:
            # All descendants of this cycle share its origin group; the entry path is not a new origin.
            return "lineage:" + ",".join(sorted(path[positions[source_id] :]))
        positions[source_id] = len(path)
        path.append(source_id)
        source = sources[source_id]
        if source.get("duplicate_group"):
            return "duplicate:" + str(source["duplicate_group"])
        parent = source.get("derived_from_source_id")
        if not parent:
            return "source:" + source_id
        source_id = parent
    # An unindexed parent is still an explicit shared origin, not one origin per copy.
    return "source:" + source_id


def _confidence(component, findings, sources, ambiguity_count):
    usable = [f for f in findings if f["admitted"]]
    unresolved_count = len(
        {
            " ".join(f["quotation"].casefold().split())
            for f in findings
            if f["relationship"] == "unresolved"
        }
    )

    def source_checks(finding):
        source = sources[finding["source_id"]]
        return [
            source.get("ingestion_status") == "ingested",
            not source.get("metadata_conflicts"),
            bool(source.get("author_or_system")),
            _day(source.get("creation_date")) is not None,
        ]

    unique = {}
    for finding in sorted(
        usable, key=lambda f: (sum(source_checks(f)), f["source_id"], f["evidence_id"])
    ):
        text_key = " ".join(finding["quotation"].casefold().split())
        # Copies and repeated inference paths receive one quality observation.
        key = (text_key, finding["relationship"])
        unique.setdefault(key, finding)
    values = list(unique.values())
    n = len(values)
    mean = lambda parts: sum(parts) / len(parts) if parts else 0.0
    source_quality = []
    for finding in values:
        source_quality.append(mean(source_checks(finding)))
    origins = {_lineage(f["source_id"], sources) for f in values}
    # No source-type heuristic or provider assertion establishes independent origins.
    verified = {
        _lineage(f["source_id"], sources)
        for f in values
        if sources[f["source_id"]].get("metadata_provenance", {}).get("independence_verified")
        == "verified"
        and sources[f["source_id"]]
        .get("metadata_provenance", {})
        .get("independence_basis", "")
        .strip()
    }
    supports = {
        _lineage(f["source_id"], sources) for f in values if f["relationship"] == "supports"
    }
    contradicts = {
        _lineage(f["source_id"], sources) for f in values if f["relationship"] == "contradicts"
    }
    polar_count = len(supports) + len(contradicts)
    factors = {
        "coverage": float(bool(supports or contradicts)),
        "directness": mean([f["directness"] == "direct" for f in values]),
        "temporal_fit": mean([f["time_fit"] == "yes" for f in values]),
        "scope_fit": mean([f["scope_fit"] == "yes" for f in values]),
        "source_quality": mean(source_quality),
        "independence": min(1.0, len(verified) / 2),
        "agreement": max(len(supports), len(contradicts)) / polar_count if polar_count else 0.0,
        "interpretation_clarity": 1.0 / (1 + ambiguity_count + unresolved_count),
    }
    return {
        "component_id": component["id"],
        "score": round(100 * sum(WEIGHTS[key] * value for key, value in factors.items())),
        "factors": factors,
        "basis": [
            f"{n} unique admitted finding(s); {len(origins)} documented origin group(s), {len(verified)} independently verified.",
            f"{ambiguity_count} material claim interpretation ambiguity/ambiguities and {unresolved_count} unique unresolved evidence passage(s) reduce interpretation clarity.",
        ],
    }


def _summary(components, status, ambiguities):
    """Explain the result from checked findings, respecting admission safeguards."""
    findings = [finding for component in components for finding in component["findings"]]
    support = next((f for f in findings if f["relationship"] == "supports"), None)
    contradiction = next((f for f in findings if f["relationship"] == "contradicts"), None)
    uncertainty = next((f for f in findings if f["relationship"] == "unresolved"), None)
    uncertainty = uncertainty or next(
        (f for f in findings if f["relationship"] == "qualifies"), None
    )
    explanations = []

    def explain(label, text):
        text = text.strip()
        explanations.append(f"{label}: {text}" + ("" if text.endswith((".", "?", "!")) else "."))

    if support:
        explain("Supporting evidence", support["reason"])
    if contradiction:
        explain("Contradicting evidence", contradiction["reason"])
    if uncertainty:
        # A guard can override an otherwise positive model explanation.
        reasons = uncertainty["exclusion_reasons"]
        explain(
            "Remaining uncertainty",
            " ".join(reasons) if reasons else uncertainty["reason"],
        )
    elif status in {"insufficient", "partially_supported"}:
        missing = next((c for c in components if c["status"] == "insufficient"), None)
        if missing:
            retained = missing["findings"]
            reasons = [reason for f in retained for reason in f["exclusion_reasons"]]
            explain(
                "Evidence gap",
                reasons[0]
                if reasons
                else retained[0]["reason"]
                if retained
                else f"No cited finding establishes or contradicts: {missing['text']}",
            )
    if ambiguities:
        explain("Interpretation remains uncertain", ambiguities[0])
    elif status == "supported" and support and support["limitations"]:
        explain("Evidence limitation", support["limitations"][0])
    if not explanations:
        explain("Evidence gap", "No admitted finding establishes or contradicts the claim")
    counts = ""
    if len(components) > 1:
        states = dict.fromkeys(c["status"] for c in components)
        counts = (
            f" ({len(components)} components: "
            + "; ".join(
                f"{sum(c['status'] == state for c in components)} {OUTCOMES[state].lower()}"
                for state in states
            )
            + ")"
        )
    return f"{OUTCOMES[status]}{counts}. " + " ".join(explanations)


def canonical_assessment(
    interpretation, evaluated, evidence_map, sources_map, as_of, diagnostics=None, provenance=None
):
    """Return one result, or a processing failure without an assessment outcome."""
    try:
        evidence = {key: _dict(value) for key, value in evidence_map.items()}
        sources = {key: _dict(value) for key, value in sources_map.items()}
        as_of = _day(as_of)
        if as_of is None:
            raise InvalidAssessment("An explicit ISO assessment date is required.")
        if not evidence or not sources:
            return processing_failure(
                "empty_corpus",
                "The selected corpus contains no assessable evidence.",
                interpretation=interpretation,
                diagnostics=diagnostics,
                provenance=provenance,
            )
        if not isinstance(interpretation, dict) or interpretation.get("target") not in TARGETS:
            raise InvalidAssessment("The interpretation has no supported assessment target.")
        components = interpretation.get("components")
        ambiguities = interpretation.get("ambiguities", [])
        if (
            not isinstance(components, list)
            or not components
            or not isinstance(ambiguities, list)
            or any(not isinstance(x, str) for x in ambiguities)
        ):
            raise InvalidAssessment(
                "The interpretation must contain components and explicit ambiguities."
            )
        ids = set()
        for component in components:
            if (
                not isinstance(component, dict)
                or not all(
                    isinstance(component.get(k), str) and component[k].strip()
                    for k in ("id", "text", "claim_quote")
                )
                or component["id"] in ids
            ):
                raise InvalidAssessment(
                    "Claim components need unique identifiers, text and original claim quotations."
                )
            ids.add(component["id"])
        if not isinstance(evaluated, dict) or not isinstance(evaluated.get("findings"), list):
            raise InvalidAssessment("The evaluator must return structured evidence findings.")
        grouped = {key: [] for key in ids}
        citations, relations = [], []
        seen_citations, seen_findings = set(), set()
        by_id = {c["id"]: c for c in components}
        for raw in evaluated["findings"]:
            if (
                not isinstance(raw, dict)
                or raw.get("component_id") not in ids
                or raw.get("relationship") not in RELATIONSHIPS
            ):
                raise InvalidAssessment(
                    "An evidence finding has an invalid component or relationship."
                )
            if (
                not isinstance(raw.get("reason"), str)
                or not raw["reason"].strip()
                or raw.get("scope_fit") not in {"yes", "no", "unknown"}
                or raw.get("time_fit") not in {"yes", "no", "unknown"}
                or raw.get("directness") not in {"direct", "indirect"}
                or raw.get("basis") not in BASES
            ):
                raise InvalidAssessment(
                    "An evidence finding lacks its reasoning or applicability checks."
                )
            if not isinstance(raw.get("limitations"), list) or any(
                not isinstance(x, str) for x in raw["limitations"]
            ):
                raise InvalidAssessment("Evidence limitations must be an explicit list of text.")
            citation = _citation(raw, evidence, sources)
            finding_key = (
                raw["component_id"],
                citation["evidence_id"],
                citation["start"],
                citation["end"],
                raw["relationship"],
            )
            if finding_key in seen_findings:
                continue
            seen_findings.add(finding_key)
            component = by_id[raw["component_id"]]
            temporal_basis = _formal_temporal_basis(
                raw,
                component,
                interpretation["target"],
                sources[raw["source_id"]],
                evidence,
                sources,
                as_of,
            )
            adjusted = {**raw, "time_fit": "yes"} if temporal_basis else raw
            finding_citations = [
                citation,
                *(temporal_basis["citations"] if temporal_basis else []),
            ]
            relation, reasons = _guard(
                adjusted,
                component,
                interpretation["target"],
                evidence[raw["evidence_id"]],
                sources[raw["source_id"]],
                as_of,
            )
            finding = {
                **adjusted,
                "original_relationship": raw["relationship"],
                "relationship": relation,
                "admitted": relation in {"supports", "contradicts", "qualifies"},
                "exclusion_reasons": reasons,
                "citations": finding_citations,
            }
            if temporal_basis:
                finding["original_time_fit"] = raw["time_fit"]
                finding["temporal_derivation"] = temporal_basis
            grouped[raw["component_id"]].append(finding)
            relations.append(
                {
                    "component_id": raw["component_id"],
                    "evidence_id": raw["evidence_id"],
                    "source_id": raw["source_id"],
                    "relationship": relation,
                    "reason": raw["reason"] + (" " + " ".join(reasons) if reasons else ""),
                    "inferential": finding["admitted"],
                    "citations": finding_citations,
                }
            )
            for cited in finding_citations:
                citation_key = (cited["evidence_id"], cited["start"], cited["end"])
                if citation_key not in seen_citations:
                    citations.append(cited)
                    seen_citations.add(citation_key)
        questions = evaluated.get("unresolved_questions", [])
        if not isinstance(questions, list) or any(not isinstance(q, str) for q in questions):
            raise InvalidAssessment("Unresolved questions must be text.")
        questions = questions.copy()
        results, scores = [], []
        for component in components:
            findings = grouped[component["id"]]
            status = _outcome(findings)
            results.append(
                {
                    **component,
                    "status": status,
                    "outcome": OUTCOMES[status],
                    "findings": findings,
                    "citations": [c for f in findings for c in f["citations"]],
                }
            )
            scores.append(_confidence(component, findings, sources, len(ambiguities)))
            if status in {"insufficient", "partially_supported", "conflicting"} or any(
                f["relationship"] == "unresolved" for f in findings
            ):
                questions.append(
                    f"Resolve the remaining qualification, conflict or evidence gap for: {component['text']}"
                )
        states = {component["status"] for component in results}
        status = (
            "conflicting"
            if "conflicting" in states
            else "contradicted"
            if "contradicted" in states
            else "supported"
            if states == {"supported"} and not ambiguities
            else "partially_supported"
            if {"supported", "partially_supported"} & states
            else "insufficient"
        )
        questions.extend(ambiguities)
        summary = _summary(results, status, ambiguities)
        score = round(sum(c["score"] for c in scores) / len(scores))
        return {
            "schema_version": SCHEMA_VERSION,
            "processing": {
                "status": "assessed",
                "code": "assessment_complete",
                "message": "Claim components and exact evidence citations were evaluated.",
            },
            "interpreted_claim": interpretation,
            "components": results,
            "overall_outcome": OUTCOMES[status],
            "summary": summary,
            "confidence": {
                "score": score,
                "method": CONFIDENCE_METHOD,
                "label": "Uncalibrated assessment confidence",
                "calibrated": False,
                "meaning": "Quality of the evidential basis for this assessment, not probability that the claim is true.",
                "basis": CONFIDENCE_BASIS.copy(),
                "components": scores,
                "weights": WEIGHTS.copy(),
            },
            "unresolved_questions": list(dict.fromkeys(questions)),
            "evidence_relations": relations,
            "citations": citations,
            "diagnostics": {
                **(diagnostics or {}),
                "aggregation_method": SCHEMA_VERSION,
                "component_count": len(results),
                "evaluated_findings": len(relations),
                "admitted_findings": sum(r["inferential"] for r in relations),
                "components_with_decisive_evidence": sum(
                    c["status"] in {"supported", "contradicted", "conflicting"} for c in results
                ),
                "aggregation_semantics": "Components form a conjunction. Any contradicted component contradicts the conjunction; unresolved or qualified components prevent full support. Within-component support and contradiction remain conflicting evidence. Material interpretation ambiguity prevents full support.",
            },
            "provenance": {
                **(provenance or {}),
                "canonical_method": SCHEMA_VERSION,
                "confidence_method": CONFIDENCE_METHOD,
            },
        }
    except (InvalidAssessment, TypeError, KeyError, ValueError) as error:
        return processing_failure(
            "invalid_model_output",
            str(error),
            interpretation=interpretation,
            diagnostics=diagnostics,
            provenance=provenance,
        )
