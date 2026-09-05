"""Claim atomicity checks and safe compound-claim splitting."""

from dataclasses import dataclass
import re

from decidr.models import AtomicClaim

CONJUNCTION_PATTERN = re.compile(r"\b(?:and|as well as|plus)\b|;", re.IGNORECASE)
MULTIPLE_MODAL_PATTERN = re.compile(
    r"\b(?:must|requires?|is|are|owns?|approves?|records?|follows?)\b", re.IGNORECASE
)


@dataclass(frozen=True, slots=True)
class AtomicityResult:
    """Transparent heuristic result; a reviewer makes the final decision."""

    status: str
    reasons: tuple[str, ...]
    suggested_components: tuple[str, ...]


def check_atomicity(text: str) -> AtomicityResult:
    """Flag wording that may need different evidence or outcomes."""
    reasons: list[str] = []
    components = tuple(
        part.strip(" ,.") for part in CONJUNCTION_PATTERN.split(text) if part.strip()
    )
    if len(components) > 1:
        reasons.append("Contains a conjunction or semicolon joining potential propositions.")
    if len(MULTIPLE_MODAL_PATTERN.findall(text)) > 2:
        reasons.append("Contains several relationship or obligation phrases.")
    return AtomicityResult(
        status="potentially_compound" if reasons else "appears_atomic",
        reasons=tuple(reasons),
        suggested_components=components if reasons else (),
    )


def split_claim(claim: AtomicClaim, component_texts: list[str]) -> list[AtomicClaim]:
    """Create reviewer-editable child claims while preserving original wording."""
    if len(component_texts) < 2 or any(not text.strip() for text in component_texts):
        raise ValueError("A compound claim requires at least two non-empty components")
    return [
        claim.model_copy(
            update={
                "claim_id": f"{claim.claim_id}.{index}",
                "claim_text": text.strip(),
                "original_claim_text": claim.original_claim_text or claim.claim_text,
                "parent_claim_id": claim.claim_id,
                "atomicity_status": "review_required",
            }
        )
        for index, text in enumerate(component_texts, start=1)
    ]
