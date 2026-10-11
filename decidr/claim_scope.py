"""Bounded, corpus-backed scope questions; no interpretation or verdict inference."""

from dataclasses import dataclass
import re

from decidr.retrieval_models import Evidence, Source


@dataclass(frozen=True)
class ScopeRule:
    key: str
    trigger: str
    resolved: str
    question: str
    options: tuple[str, ...]
    # Each option needs an exact passage in a relevant, documented section.
    patterns: tuple[tuple[str, str, str], ...]
    distinct_sources: bool = False


RULES = (
    ScopeRule(
        "discount_deal_type",
        r"(?=.*\bdiscounts?\b)(?=.*(?:\bapprov\w*\b|sign[- ]off))",
        r"\bnew[- ]business\b|\brenewals?\b|\bboth\b",
        "Does your claim concern new-business deals, renewals, or all deal types?",
        ("New-business deals", "Renewal deals", "All deal types"),
        (
            ("New-business deals", r".*", r"\bnew[- ]business deals?\b"),
            ("Renewal deals", r".*", r"\brenewal discounts?\b"),
        ),
        True,
    ),
    ScopeRule(
        "onboarding_population",
        r"\bonboarding\b",
        r"\bcustomers?\b|\baccounts?\b|\bimplementation\b|\bemployees?\b|\bhires?\b|\bstaff\b|\bprobation\b|\bremote\b",
        "Does onboarding mean customer implementation, new-hire onboarding, or both?",
        ("Customer implementation", "New-hire onboarding", "Both onboarding processes"),
        (
            ("Customer implementation", r"customer.*onboarding", r"\bonboarding\b.*\b6 weeks\b"),
            (
                "New-hire onboarding",
                r"new hire.*onboarding",
                r"\bnew hire\b.*\bonboarding checklist\b",
            ),
        ),
        True,
    ),
    ScopeRule(
        "expense_amount",
        r"(?=.*\b(?:this|my|an) expense\b)(?=.*\bapprov\w*\b)",
        r"\$|\b\d+\b|\bdollars?\b|\b(?:over|under|above|below|at least|at most)\b|\bfive hundred\b",
        "What is the amount of the expense you mean?",
        ("Over $500", "$500 or less", "Amount not known"),
        (
            ("Over $500", r"expense approval", r"expense claims.*over \$500"),
            ("$500 or less", r"expense approval", r"expense claims of \$500 or less"),
        ),
    ),
    ScopeRule(
        "renewal_responsibility",
        r"(?=.*\brenewals?\b)(?=.*\b(?:owns?|ownership|responsible|accountable|responsibility)\b)",
        r"\bcommercial\b|\bnegotiat\w*\b|\bhealth\b|\bdiscount\w*\b|\bfinal\b|\bdisagree\w*\b|\bescalat\w*\b|\bchurn\b|\bstrateg\w*\b",
        "Which part of renewal responsibility do you mean?",
        (
            "Commercial negotiation",
            "Customer relationship health",
            "Final accountability",
            "The whole renewal process",
        ),
        (
            (
                "Commercial negotiation",
                r"contract renewal",
                r"Account Executive leads commercial renewal",
            ),
            ("Customer relationship health", r"contract renewal", r"relationship[- ]health"),
        ),
    ),
    ScopeRule(
        "product_decision_stage",
        r"(?=.*\b(?:product|feature)\b)(?=.*\b(?:approv\w*|owns?|responsible|accountable)\b)",
        r"\bp[1-4]\b|\bprioriti\w*\b|\bfeasib\w*\b|\bsequenc\w*\b|\bsprint\b|\btriage\b|\bplanning\b|\bplanned\b",
        "Which product-change decision does your claim concern?",
        (
            "Prioritisation",
            "Engineering feasibility and sequencing",
            "P1 entry into a sprint",
            "All decision stages",
        ),
        (
            (
                "Prioritisation",
                r"product change|feature request",
                r"Product Manager \(prioritisation\)",
            ),
            (
                "Engineering feasibility and sequencing",
                r"product change|feature request",
                r"Head of Engineering \(feasibility/sequencing\)",
            ),
            (
                "P1 entry into a sprint",
                r"product change|feature request",
                r"sign-off for P1 cards entering a sprint",
            ),
        ),
    ),
)

# A discrepancy or an omitted condition in a clear assertion is an assessment
# finding. Do not turn it into a request to change the original assertion.
EXPLICIT_SCOPE = re.compile(
    r"\b(?:all|every|any|each|both|neither)\b|\b(?:always|never)\b", re.IGNORECASE
)
RECORD_ID = re.compile(r"\b[A-Z][A-Z0-9]*-\d+\b", re.IGNORECASE)
ALLOWED_SECTIONS = {
    "formal requirements",
    "steps",
    "responsible / accountable",
    "required approvals",
}


def _basis(rule: ScopeRule, sources: dict[str, Source], evidence: list[Evidence]) -> list[dict]:
    found = {}
    for passage in sorted(evidence, key=lambda p: p.evidence_id):
        source = sources.get(passage.source_id)
        if (
            source is None
            or source.source_type not in {"policy", "procedure"}
            or source.ingestion_status != "ingested"
            or (passage.heading or "").casefold() not in ALLOWED_SECTIONS
        ):
            continue
        # The original deal-type rule is grounded in policy requirements only.
        if rule.key == "discount_deal_type" and (
            source.source_type != "policy"
            or (passage.heading or "").casefold() != "formal requirements"
        ):
            continue
        for label, title_pattern, text_pattern in rule.patterns:
            if (
                label not in found
                and re.search(title_pattern, source.title, re.IGNORECASE)
                and re.search(text_pattern, passage.text, re.IGNORECASE | re.DOTALL)
            ):
                found[label] = {
                    "label": label,
                    "source_title": source.title,
                    "source_id": source.source_id,
                    "evidence_id": passage.evidence_id,
                    "locator": passage.locator,
                    "quotation": passage.text,
                }
    if len(found) != len(rule.patterns):
        return []
    if rule.distinct_sources and len({item["source_id"] for item in found.values()}) < 2:
        return []
    return list(found.values())


def scope_context(
    claim: str, answer: str | None, sources: dict[str, Source], evidence: list[Evidence]
) -> dict:
    result = {
        "status": "not_requested",
        "question": None,
        "options": [],
        "answer": answer,
        "facet": claim,
        "basis": [],
    }
    if answer is not None:
        result.update(
            status="scope_supplied", facet=f"{claim}\n\nScope supplied by user: {answer}"
        )
        return result
    if EXPLICIT_SCOPE.search(claim) or RECORD_ID.search(claim):
        return result
    for rule in RULES:
        if not re.search(rule.trigger, claim, re.IGNORECASE | re.DOTALL):
            continue
        if re.search(rule.resolved, claim, re.IGNORECASE):
            continue
        basis = _basis(rule, sources, evidence)
        if basis:
            result.update(
                status="clarification_available",
                question=rule.question,
                options=list(rule.options),
                basis=basis,
            )
            break  # One optional question; no automatic questionnaire or rewriting.
    return result
