"""Result container for an end-to-end claim assessment."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from framework.models import FactAssessment

from decidr.claim_combiner import ClaimVerdict


@dataclass(frozen=True, slots=True)
class ClaimAssessment:
    """Everything produced for one claim, for inspection or serialisation."""

    claim_text: str
    as_of: date
    verdict: ClaimVerdict
    facet_assessments: dict[str, FactAssessment]
    split: dict
    reading: dict
    passages: list[dict]
    retrieval: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
