"""Fair-comparison scaffolding guarded by human-reference and held-out states."""

from dataclasses import dataclass
from typing import Any

from decidr.config import DATABASE_PATH, PROJ_ROOT
from decidr.corpus import freeze_compatibility


@dataclass(frozen=True, slots=True)
class ComparisonReadiness:
    development_ready: bool
    held_out_ready: bool
    blockers: tuple[str, ...]


def comparison_readiness(
    configuration: dict[str, Any], completed_reviewers: int, development_references: int
) -> ComparisonReadiness:
    blockers = []
    if completed_reviewers < 2:
        blockers.append("Two independent human reviews are not complete.")
    compatible, note = freeze_compatibility(DATABASE_PATH, configuration, PROJ_ROOT)
    if not compatible:
        blockers.append(note)
    development_ready = compatible and completed_reviewers >= 2 and development_references > 0
    held_out_ready = (
        development_ready
        and configuration.get("reasoning_ruleset_status") == "approved_and_frozen"
        and configuration.get("held_out_access_status") == "unlocked"
        and configuration.get("final_evaluation_authorised") is True
    )
    if not held_out_ready:
        blockers.append(
            "Held-out comparison remains sealed until ruleset freeze and authorization."
        )
    return ComparisonReadiness(development_ready, held_out_ready, tuple(blockers))
