"""Bounded deployment requirement and audit-gap interpretation."""

from datetime import date, datetime
import json
import re


def parse_deployment_rule(text: str, heading: str | None = None) -> dict | None:
    text = " ".join(
        text.casefold().strip().replace("**", "").replace("’", "'").rstrip(".").split()
    )
    m = re.fullmatch(
        r"production deployments touching customer billing require (?P<actor>head of engineering|his|her|their) sign-off before release",
        text,
    )
    if not m:
        return None
    actor = m["actor"]
    if actor != "head of engineering":
        if not heading or not re.fullmatch(r"Head of Engineering — [\w]+(?:[ -][\w]+)*", heading):
            return None
        actor = "head of engineering"
    return {
        "environment": "production",
        "scope": "customer billing",
        "approver": actor,
        "timing": "before release",
    }


def compare_deployment_rules(claim: str, evidence: str, heading: str | None = None) -> dict | None:
    a, b = parse_deployment_rule(claim), parse_deployment_rule(evidence, heading)
    if a is None or b is None:
        return None
    return {
        "claim_fields": a,
        "evidence_fields": b,
        "differences": [],
        "equivalent": True,
        "claim_range_covered": True,
        "evidence_entails_claim": True,
        "method": "deployment_requirement_fields_v1",
    }


def deployment_context_reason(clause: str) -> str | None:
    # Only the observed role-description clauses are accepted; other prose stays unresolved.
    accepted = {
        "- function: engineering & product",
        "- responsibilities: engineering delivery, technical architecture decisions, production deployment sign-off",
        "- decision rights: final say on technical feasibility for feature requests (see proc-03; no single document states the product/engineering prioritisation split explicitly)",
        "- systems accessed: all engineering and production systems",
        "- process participation: p3, p5 (engineering escalation), p7 (billing integration dependency)",
        "- backup/delegate: no named delegate for deployment sign-off",
    }
    if clause in accepted or re.fullmatch(r"- reports to: [a-z]+(?:[ -][a-z]+)* \(ceo\)", clause):
        return "Role context retained; it does not waive the deployment sign-off requirement."
    return None


def deployment_event_findings(claim: str, passages: list, as_of: date) -> list[dict]:
    m = re.fullmatch(
        r"The emergency billing deployment recorded on (.+) received Head of Engineering sign-off before release\.?",
        claim.strip(),
        re.IGNORECASE,
    )
    if not m:
        return []
    try:
        day = (
            date.fromisoformat(m[1])
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", m[1])
            else datetime.strptime(m[1], "%d %B %Y").date()  # noqa: DTZ007 — civil date only
        )
    except ValueError:
        return []
    if day > as_of:
        return []
    findings = []
    for p in passages:
        if p.source_type not in {"audit_events", "audit"}:
            continue
        try:
            row = json.loads(p.text)
        except (ValueError, TypeError):
            continue
        if not isinstance(row, dict):
            continue
        try:
            recorded = datetime.strptime(row.get("timestamp", ""), "%Y-%m-%d %H:%M")  # noqa: DTZ007 — no timezone or ordering inferred
        except (ValueError, TypeError):
            continue
        if (
            recorded.date() != day
            or row.get("action") != "Deployed emergency fix to billing integration"
            or row.get("object") != "Production deployment - billing module"
        ):
            continue
        gap = row.get("notes") == "No linked deployment sign-off record found for this change"
        findings.append(
            {
                "status": "unresolved",
                "event_id": row.get("event_id") if isinstance(row.get("event_id"), str) else None,
                "related_record": row.get("related_record")
                if isinstance(row.get("related_record"), str)
                else None,
                "message": (
                    "The audit record reports no linked deployment sign-off record. This is a recorded evidence gap, not proof that sign-off did not happen."
                    if gap
                    else "The deployment record alone does not establish prior Head of Engineering sign-off."
                ),
                "next_step": "Locate an approval tied to this exact deployment, identify the approver and applicable authority, and compare its timestamp with the release timestamp. A date alone cannot establish ordering.",
                "citation": {
                    "evidence_id": p.evidence_id,
                    "source_id": p.source_id,
                    "locator": p.locator,
                    "quotation": p.text,
                    "start": 0,
                    "end": len(p.text),
                },
            }
        )
    return findings
