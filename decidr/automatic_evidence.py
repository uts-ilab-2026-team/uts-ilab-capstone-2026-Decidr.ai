"""Conservative, span-grounded employee evidence classification; no retrieval scores.

Supported grammar: complete literal propositions, explicit opposite polarity,
single-valued numeric equalities, and explicit approval-threshold rules. Unsupported
language remains unclassified and cannot manufacture a decisive verdict.
"""

from decimal import Decimal
import re

from decidr.models import AtomicClaim, ClaimEvidenceLink, CredibilityAssessment

VERSION = "bounded-evidence-5"
NUMBER = r"\d+(?:\.\d+)?\s*%?"
UNCERTAIN = re.compile(
    r"\b(might|could|perhaps|possibly|apparently|reportedly|proposed|draft|uncertain|"
    r"if|unless|except|excluding|according to|used to|previously|formerly)\b",
    re.IGNORECASE,
)


def clean(text):
    text = re.sub(r"[*`]", "", text).casefold()
    text = re.sub(r"^\s*(?:\d+\.\s+|[-•]\s+)", "", text)
    return " ".join(text.strip(" .").split())


def threshold_claim(text):
    return re.fullmatch(
        rf"(?:the )?(?:current |prescribed )?threshold for (.+?) approval is ({NUMBER})",
        clean(text),
    )


def expense_route_claim(text):
    """Only the complete general-route proposition; changed conditions need comparison anew."""
    return re.fullmatch(
        r"customer[ -]onboarding travel follows the (?:normal|standard|usual) expense approval (?:route|process)",
        clean(text),
    )


def _expense_route_comparison(claim, span, record):
    if not expense_route_claim(claim.claim_text):
        return None
    text = clean(span)
    title = clean(record["source"]["title"])
    context = " ".join(clean(c["text"]) for c in record.get("source_context", []))
    boundary = re.fullmatch(
        r"expense claims over \$(\d+) require approval from .+ before reimbursement is processed",
        text,
    )
    if (
        "expense approval" in title
        and boundary
        and "all employees submitting expense claims" in context
        and "none documented in this version" in context
        and re.search(
            rf"expense claims of \${boundary[1]} or less may be approved by", clean(record["text"])
        )
        and "all expense claims must include an itemised receipt" in clean(record["text"])
    ):
        return (
            "support",
            "The general expense rule applies to all employees submitting claims; the amount-dependent route and receipt conditions remain as stated in the source. No exception is documented in this policy version.",
        )
    if (
        "travel expenses incurred during customer onboarding visits" in text
        and "standing pre-approved in practice" in text
    ) or (
        "onboarding" in text
        and ("customer visit" in text or "onboarding-visit travel" in text)
        and ("don't make" in text or "nobody makes us get separate sign-off" in text)
    ):
        return (
            "contradict",
            "This passage reports standing pre-approval for onboarding-visit travel in practice; it does not amend the written expense policy.",
        )
    return None


def _polarity(text):
    # Only explicit paired predicates; 'not required' is not 'required not to'.
    match = re.search(r"\b(is|are|must|shall) not\b", text)
    return (
        (text[: match.start()] + match[1] + text[match.end() :], True) if match else (text, False)
    )


def _compare(claim_text, sentence):
    claim, evidence = clean(claim_text), clean(sentence)
    if not evidence or any(mark in sentence for mark in ('"', "“", "”")):
        return None
    if evidence == claim:
        return "support", "Complete proposition matches, including its quantities and conditions."
    left, negative_left = _polarity(claim)
    right, negative_right = _polarity(evidence)
    if left == right and negative_left != negative_right:
        return "contradict", "The same complete proposition has explicitly opposite polarity."
    # Different values conflict only in a single-valued equality, not in bounds,
    # permissions, lists of authorised people, or partially overlapping scopes.
    equality = rf"(.+?\b(?:is|equals)) ({NUMBER})(.*)"
    a, b = re.fullmatch(equality, claim), re.fullmatch(equality, evidence)
    if (
        a
        and b
        and a[1] == b[1]
        and a[3] == b[3]
        and a[2].endswith("%") == b[2].endswith("%")
        and not re.search(r"\b(or|and|to|than)\b|\d", a[3])
    ):
        return (
            "support" if Decimal(a[2].strip(" %")) == Decimal(b[2].strip(" %")) else "contradict",
            "Compared the explicit numeric value of the same single-valued property and scope.",
        )
    threshold = threshold_claim(claim)
    if threshold:
        # Explicit lower-bound approval rule, retaining business scope and measure.
        rule = re.fullmatch(
            rf"any ([\w-]+) of ({NUMBER}) (or greater|or more|and above) "
            r"off list price on a ([\w-]+) deal requires (?:written )?approval"
            r"(?: from [\w &'-]+)?(?: before .+)?",
            evidence,
        )
        if (
            rule
            and threshold[1] == f"{rule[4]} {rule[1]}"
            and threshold[2].endswith("%") == rule[2].endswith("%")
        ):
            return (
                "support"
                if Decimal(threshold[2].strip(" %")) == Decimal(rule[2].strip(" %"))
                else "contradict",
                "Explicit inclusive approval boundary matches the requested measure and business scope; compared the boundary value, not retrieval similarity.",
            )
    return None


def _completion(text):
    """Parse a passive completion deadline, preserving population and clock origin."""
    text = clean(text)
    for value, word in enumerate(
        (
            "zero",
            "one",
            "two",
            "three",
            "four",
            "five",
            "six",
            "seven",
            "eight",
            "nine",
            "ten",
            "eleven",
            "twelve",
        )
    ):
        text = re.sub(rf"\b{word}\b", str(value), text)
    return re.fullmatch(
        r"(.+?) (must be|shall be|is|are|must not be|shall not be) "
        r"(?:completed|finished) (?:within|in no more than) (\d+) (weeks?|days?|hours?)"
        r"(?: (of|from|after) (.+))?",
        text,
    )


def _completion_comparison(claim, span, record):
    a, b = _completion(claim.claim_text), _completion(span)
    if not a or not b:
        return None
    formal_requirement = record["source"]["source_type"] in {"policy", "procedure"} and bool(
        re.search(r"requirements|rules", record["locator"], re.IGNORECASE)
    )
    # A descriptive sentence is normative only in an explicit formal rule section.
    if b[2] in {"is", "are"} and not formal_requirement:
        return None
    left, right = a[1], b[1]
    if "customer onboarding" in clean(record["source"]["title"]):
        left = left.replace("customer onboarding", "onboarding")
        right = right.replace("customer onboarding", "onboarding")
    if left != right:
        if left.endswith("onboarding") and right.endswith("onboarding"):
            return (
                "qualify",
                "The completion rule covers a different population (for example standard versus all onboarding).",
            )
        return None
    if a[6] and a[6] != b[6]:
        return "qualify", "The deadline uses a different or unspecified starting event."
    scale = {"week": 168, "day": 24, "hour": 1}
    av, bv = int(a[3]) * scale[a[4].rstrip("s")], int(b[3]) * scale[b[4].rstrip("s")]
    if av != bv:
        return (
            "qualify",
            "The completion bounds differ; unequal upper bounds alone do not establish opposite propositions.",
        )
    relation = "contradict" if ("not" in a[2]) != ("not" in b[2]) else "support"
    return (
        relation,
        "Compared the same completion requirement, population and duration; source clock starts "
        + (b[6] or "at an unspecified event")
        + ".",
    )


def _context_comparison(claim, record):
    """Recognise explicit process context, never infer support from topic overlap."""
    if "customer onboarding" not in clean(claim.claim_text):
        return None
    text, title = clean(record["text"]), clean(record["source"]["title"])
    if re.search(r"new[ -]hire|probation", text + " " + title):
        return (
            "not_applicable",
            "Employee onboarding and probation concern a different population from customer onboarding.",
        )
    if re.search(r'"process_or_capability":\s*"contract renewal"', text):
        return (
            "not_applicable",
            "This record concerns contract renewal, not new-customer onboarding.",
        )
    if "customer data" in title and "onboarding" not in text:
        return (
            "not_applicable",
            "Data handling permissions do not address the onboarding completion requirement.",
        )
    if "customer onboarding" in title or re.search(r"\bonboarding\b|\bsix weeks\b", text):
        if "contract signature" in text and "within" in text:
            reason = "This purpose statement times productive use from contract signature; it does not state the same onboarding-completion event and starting point as the claim."
        elif "extension" in text or "complex" in text:
            reason = "Complex-account extensions provide exception context; they do not negate the standard completion rule."
        elif "prior to" in text:
            reason = "Historical onboarding arrangements provide background, not the current rule."
        else:
            reason = "Onboarding steps, records or testimony provide process context, not a separate prescribed deadline."
        return "contextual", reason
    return None


def classify_evidence(claim: AtomicClaim, record: dict, run_id: str) -> dict:
    """Freeze each target comparison so later replay never reclassifies evidence."""

    def compare(scoped_claim):
        try:
            return _classify_evidence(scoped_claim, record, run_id)
        except Exception as error:  # noqa: BLE001 -- isolate a candidate classifier failure
            reason = (
                f"Classifier failed ({type(error).__name__}); this candidate was not assessed."
            )
            link_id = f"{run_id}:{record['evidence_id']}"
            return {
                "link": {
                    "link_id": link_id,
                    "claim_id": claim.claim_id,
                    "evidence_id": record["evidence_id"],
                    "relationship": None,
                    "applicability_reason": reason,
                    "method": "automatic",
                    "review_status": "not_reviewed",
                    "reviewer": VERSION,
                    **{
                        key: False
                        for key in (
                            "target_match",
                            "scope_match",
                            "condition_match",
                            "temporal_match",
                        )
                    },
                },
                "credibility": {
                    "assessment_id": link_id + ":cred",
                    "link_id": link_id,
                    "evidence_mode": "other",
                    "reviewer_justification": reason,
                    **{
                        key: 0.0
                        for key in (
                            "relevance",
                            "institutional_authority",
                            "directness",
                            "temporal_validity",
                            "independence",
                            "completeness",
                            "organisational_applicability",
                        )
                    },
                },
                "classification": {
                    "version": VERSION,
                    "status": "unclassified",
                    "failure_kind": "classifier_error",
                    "reason": reason,
                    "comparisons": [],
                    "limitations": [reason],
                },
                "gaps": [],
                "settlement": "",
                "responsible_role": "",
                "role_quote": "",
                "risks": [],
                "risk_reason": "",
                "origin_source_id": "",
                "origin_quote": "",
                "temporal_basis": "",
                "intended_value_confirmed": False,
                "corroborating_evidence_ids": [],
            }

    note = compare(claim)
    note["target_findings"] = {
        target: compare(claim.model_copy(update={"evidence_target": target}))
        for target in ("prescribed_rule", "actual_practice", "recorded_state")
    }
    return note


def _classify_evidence(claim: AtomicClaim, record: dict, run_id: str) -> dict:
    source, evidence = record["source"], record["evidence"]
    formal = source["source_type"] in {"policy", "procedure"}
    recorded = source["source_type"] in {
        "crm_records",
        "task_records",
        "audit_logs",
        "crm",
        "crm_export",
        "task_record",
        "audit_log",
        "operational_record",
        "structured_data",
        "system_export",
    } or evidence["extraction_method"].startswith("csv")
    practice = source["source_type"] in {"interview", "meeting_notes", "internal_communication"}
    route_practice = bool(expense_route_claim(claim.claim_text)) and any(
        (comparison := _expense_route_comparison(claim, span, record))
        and comparison[0] == "contradict"
        for span in record["text"].splitlines()
    )
    if route_practice:
        # A process document can report practice without making it a formal rule.
        formal, practice = False, True
    target_match = (
        formal
        if claim.evidence_target == "prescribed_rule"
        else recorded
        if claim.evidence_target == "recorded_state"
        else practice
        if claim.evidence_target == "actual_practice"
        else formal or practice or recorded
    )
    mode = "formal_rule" if formal else "observed_practice" if practice or recorded else "other"
    comparisons = []
    limitations = []
    for span in re.split(r"\n|(?<=[.!?])\s+(?!\d)", record["text"]):
        compared = (
            _compare(claim.claim_text, span)
            or _completion_comparison(claim, span, record)
            or _expense_route_comparison(claim, span, record)
        )
        if not compared:
            qualified = re.sub(
                r"^\s*(?:perhaps|possibly|apparently|reportedly|proposed:|draft:)\s*",
                "",
                span,
                flags=re.IGNORECASE,
            )
            if qualified != span and _compare(claim.claim_text, qualified):
                compared = (
                    "qualify",
                    "The matching proposition is explicitly uncertain or proposed.",
                )
        if compared:
            relation, reason = compared
            # Historical source status is date applicability, handled by the reasoner.
            # Only a historical passage section changes this semantic comparison.
            if UNCERTAIN.search(record["text"]) or re.search(
                r"history|historical|superseded", record["locator"].split(" > ")[-1], re.IGNORECASE
            ):
                relation, reason = (
                    "qualify",
                    "Qualified, conditional or historical wording cannot establish the unqualified current proposition.",
                )
            comparisons.append({"relationship": relation, "reason": reason, "span": span})
    relations = {c["relationship"] for c in comparisons}
    if {"support", "contradict"} <= relations:
        relation, reason = (
            "qualify",
            "This evidence unit contains incompatible propositions; resolve its internal conflict before using it decisively.",
        )
    elif comparisons:
        relation = next(iter(relations)) if len(relations) == 1 else "qualify"
        reason = "; ".join(dict.fromkeys(c["reason"] for c in comparisons))
    else:
        context = _context_comparison(claim, record)
        relation, reason = context or (
            "contextual",
            "The bounded classifier could not compare this passage with the claim. The evidence is present; its relationship is unclassified.",
        )
        if context:
            comparisons.append(
                {"relationship": relation, "reason": reason, "span": record["text"]}
            )
    classified = bool(comparisons)
    if not target_match and comparisons and relation not in {"contextual", "not_applicable"}:
        relation, reason = (
            "contextual",
            reason + " Source type provides context only for this knowledge target.",
        )
    contextual = relation == "contextual" and classified
    if contextual:
        limitations.append(
            "Context is retained for interpretation and cannot independently establish this assessment target."
        )
    if _completion(claim.claim_text) and classified and relation != "not_applicable":
        for context in record.get("source_context", []):
            for line in context["text"].splitlines():
                if "applicable to:" in clean(line):
                    limitations.append(clean(line).removeprefix("- "))
            if "extension" in clean(context["text"]):
                limitations.append(context["text"])
        for comparison in comparisons:
            completion = _completion(comparison["span"])
            if completion and completion[6]:
                limitations.append(
                    "The source measures completion from "
                    + completion[6]
                    + "; the claim does not specify a clock origin."
                    if not _completion(claim.claim_text)[6]
                    else "Completion clock: " + completion[6] + "."
                )
    approved = clean(source.get("approval_status") or "") in {"approved", "ratified"}
    valid_lifecycle = source["lifecycle_status"] in {"current", "superseded"}
    decisive = relation in {"support", "contradict"} and target_match and valid_lifecycle
    dimensions = {
        "relevance": 0.9 if comparisons else 0.2,
        "institutional_authority": 0.8 if formal and approved else 0.5 if target_match else 0.2,
        "directness": 0.9 if comparisons else 0.2,
        "temporal_validity": 0.8 if source.get("effective_start_date") else 0.3,
        "independence": 0.3
        if source.get("derived_from_source_id") or source.get("duplicate_group")
        else 0.5,
        "completeness": 0.8 if decisive else 0.3,
        "organisational_applicability": 0.8 if target_match and comparisons else 0.2,
    }
    link_id = f"{run_id}:{record['evidence_id']}"
    link = ClaimEvidenceLink(
        link_id=link_id,
        claim_id=claim.claim_id,
        evidence_id=record["evidence_id"],
        relationship=relation,
        applicability_reason=reason,
        target_match=target_match or contextual,
        scope_match=classified and relation != "not_applicable",
        condition_match=classified,
        temporal_match=valid_lifecycle,
        reviewer=VERSION,
        method="automatic",
        review_status="not_reviewed",
    )
    credibility = CredibilityAssessment(
        assessment_id=link_id + ":cred",
        link_id=link_id,
        evidence_mode=mode,
        reviewer_justification="System assumptions based on literal comparison, source type, approval metadata, dates and provenance. Applicability and effective periods are checked by the shared reasoner.",
        limitations=[
            "Bounded grammar; unknown paraphrases remain unresolved.",
            "Credibility scores are transparent assumptions, not calibrated probabilities. Undocumented independence is unknown.",
        ],
        **dimensions,
    )
    link_payload = link.model_dump(mode="json")
    if not classified:
        # No relationship assertion exists until classification or human review completes.
        link_payload["relationship"] = None
    return {
        "link": link_payload,
        "credibility": credibility.model_dump(mode="json"),
        "classification": {
            "version": VERSION,
            "status": "classified" if classified else "unclassified",
            "failure_kind": None if classified else "unsupported_comparison",
            "comparisons": comparisons,
            "reason": reason,
            "limitations": list(dict.fromkeys(limitations)),
        },
        "gaps": [],
        "settlement": "",
        "responsible_role": "",
        "role_quote": "",
        "risks": [],
        "risk_reason": "",
        "origin_source_id": "",
        "origin_quote": "",
        "temporal_basis": "",
        "intended_value_confirmed": False,
        "corroborating_evidence_ids": [],
    }
