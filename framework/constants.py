"""Shared vocabulary for the graph-governed credibility framework.

A ``Fact`` is a searchable topic.  Asserted values live only on FORMAL or
OBSERVED Document -> Fact edges as ``attests_value``; nothing here stores a
value.
"""

from __future__ import annotations

CREDIBILITY_DIMENSIONS = (
    "source_authority",
    "approval_status",
    "version_recency",
    "directness",
    "specificity",
    "corroboration",
    "source_independence",
    "evidence_completeness",
)

CREDIBILITY_QUESTIONS = {
    "source_authority": "Is the source authoritative for this topic and is any named actor valid?",
    "approval_status": "Is the document approved/current rather than draft or superseded?",
    "version_recency": "Was the source effective at the date relevant to the claim?",
    "directness": "Is this a primary record or direct statement?",
    "specificity": "Does it address the exact threshold, event, scope or value?",
    "corroboration": "Is the same stance supported by a separate evidential origin?",
    "source_independence": "Is this genuinely independent rather than a duplicate?",
    "evidence_completeness": "Does it contain the material details needed for judgement?",
}

OUTCOMES = ("Supported", "Contradicted", "Contested", "Insufficient evidence")
CONFIDENCE_LEVELS = ("Higher confidence", "Moderate confidence", "Lower confidence")
