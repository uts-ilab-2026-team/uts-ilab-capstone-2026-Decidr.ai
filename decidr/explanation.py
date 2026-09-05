"""Deterministic explanations generated only from structured reasoning records."""

from decidr.models import AtomicClaim, EvidenceRelationship
from decidr.reasoning import ReasoningResult


def render_explanation(claim: AtomicClaim, result: ReasoningResult) -> str:
    """Render a reconstructable Markdown assessment with direct evidence citations."""
    lines = [
        f"# Assessment: {claim.claim_id}",
        "",
        f"**Claim:** {claim.claim_text}",
        f"**Scope:** {claim.scope or 'Not specified'}",
        f"**Conditions:** {', '.join(claim.conditions) if claim.conditions else 'None specified'}",
        f"**Applicable period:** {claim.applicable_start_date or 'Open'} to {claim.applicable_end_date or 'Open'}",
        f"**Outcome:** {result.outcome.value}",
        f"**Confidence:** {result.confidence.value}",
        "",
    ]
    for relationship, heading in (
        (EvidenceRelationship.SUPPORT, "Supporting evidence"),
        (EvidenceRelationship.CONTRADICT, "Contradicting evidence"),
        (EvidenceRelationship.QUALIFY, "Qualifying evidence"),
        (EvidenceRelationship.CONTEXTUAL, "Contextual evidence"),
    ):
        items = [item for item in result.applicable if item.relationship == relationship]
        lines.extend([f"## {heading}", ""])
        lines.extend(
            f"- [{item.evidence_id}] source `{item.source_id}`, locator `{item.locator}`"
            for item in items
        )
        if not items:
            lines.append("- None identified.")
        lines.append("")
    lines.extend(["## Excluded or dependent evidence", ""])
    lines.extend(
        f"- [{item.evidence_id}] `{item.source_id}` at `{item.locator}`: {reason}"
        for item, reason in result.excluded
    )
    if not result.excluded:
        lines.append("- None.")
    lines.extend(["", "## Evidence gaps", ""])
    lines.extend(f"- {gap} (recorded as a gap, not contradiction)." for gap in result.gaps)
    if not result.gaps:
        lines.append("- No expected gaps were recorded.")
    lines.extend(["", "## Rules applied", ""])
    lines.extend(
        f"{index}. `{trace['rule_id']}`" for index, trace in enumerate(result.traces, start=1)
    )
    lines.extend(
        [
            "",
            "## Conclusion",
            "",
            (
                f"The structured evidence and configured rules produce **{result.outcome.value}**. "
                f"Confidence is reported separately as **{result.confidence.value}**."
            ),
        ]
    )
    return "\n".join(lines) + "\n"
