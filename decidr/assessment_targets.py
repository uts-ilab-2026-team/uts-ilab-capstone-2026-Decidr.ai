"""Supplied assessment targets; no natural-language classification or scoring."""

from typing import Literal

AssessmentTarget = Literal["unspecified", "recorded_statement", "underlying_event", "formal_rule"]
TARGETS = {"unspecified", "recorded_statement", "underlying_event", "formal_rule"}


def validate_target(value: str) -> None:
    if not isinstance(value, str) or value not in TARGETS:
        raise ValueError("Invalid assessment/evidence target")


def target_exclusion(assessment_target: str, evidence_target: str, mode: str) -> str | None:
    """Compare declarations only; matching labels do not establish entailment."""
    validate_target(assessment_target)
    validate_target(evidence_target)
    if assessment_target == evidence_target == "unspecified":
        return None  # Legacy requests retain their previous admission behaviour.
    if assessment_target == "unspecified":
        return "Assessment target must be declared when an evidence target is supplied."
    if evidence_target == "unspecified":
        return "Evidence target is unspecified for an explicitly targeted assessment."
    if assessment_target != evidence_target:
        return "Evidence target does not match the assessment target."
    required_mode = "formal" if assessment_target == "formal_rule" else "observed"
    if mode != required_mode:
        return f"Assessment target {assessment_target} requires mode={required_mode}."
    return None
