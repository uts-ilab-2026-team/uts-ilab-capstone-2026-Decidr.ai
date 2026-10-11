"""Optional, evidence-backed deal-scope clarification; no verdict inference."""

import re

from decidr.retrieval_models import Evidence, Source


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
    # This first bounded intake rule does not ask about unsupported paraphrases.
    text = claim.casefold()
    if not re.search(r"\bdiscounts?\b", text) or not re.search(r"\bapprov\w*\b|sign[- ]off", text):
        return result
    if re.search(
        r"\bnew[- ]business\b|\brenewals?\b|\bboth\b|\b(?:all|every|any)\s+(?:customer\s+)?(?:discounts?|deals?)\b",
        text,
    ):
        return result
    if re.search(r"\b[A-Z][A-Z0-9]*-\d+\b", claim):
        return result  # A specific record must be resolved from its own evidence.
    patterns = {
        "New-business deals": r"\bnew[- ]business deals?\b",
        "Renewal deals": r"\brenewal discounts?\b",
    }
    found = {}
    for passage in sorted(evidence, key=lambda p: p.evidence_id):
        source = sources.get(passage.source_id)
        if (
            source is None
            or source.source_type != "policy"
            or source.ingestion_status != "ingested"
            or (passage.heading or "").casefold() != "formal requirements"
        ):
            continue
        for label, pattern in patterns.items():
            if label not in found and re.search(pattern, passage.text, re.IGNORECASE):
                found[label] = {
                    "label": label,
                    "source_title": source.title,
                    "source_id": source.source_id,
                    "evidence_id": passage.evidence_id,
                    "locator": passage.locator,
                    "quotation": passage.text,
                }
    if len(found) == 2 and len({v["source_id"] for v in found.values()}) == 2:
        result.update(
            status="clarification_available",
            question="Does your claim concern new-business deals, renewals, or all deal types?",
            options=[*patterns, "All deal types"],
            basis=list(found.values()),
        )
    return result
