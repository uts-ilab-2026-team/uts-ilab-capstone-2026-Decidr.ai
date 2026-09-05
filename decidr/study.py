"""Human-study readiness checks and blind reviewer packet generation."""

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import sqlite3

from decidr.models import AtomicClaim


@dataclass(frozen=True, slots=True)
class StudyReadiness:
    ready: bool
    included_claims: int
    development_claims: int
    held_out_claims: int
    atomicity_pending: tuple[str, ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]


def validate_portfolio(
    claims: list[AtomicClaim], minimum: int = 6, maximum: int = 10, held_out_minimum: int = 2
) -> StudyReadiness:
    """Validate methodological portfolio constraints without choosing claims automatically."""
    included = [claim for claim in claims if claim.inclusion_status == "included"]
    held_out = [claim for claim in included if claim.evaluation_split == "held_out"]
    development = [claim for claim in included if claim.evaluation_split == "development"]
    pending = tuple(
        claim.claim_id
        for claim in included
        if claim.atomicity_status not in {"appears_atomic", "confirmed_atomic"}
    )
    blockers = []
    warnings = []
    if len(included) < minimum:
        blockers.append(
            f"Portfolio has {len(included)} included claims; at least {minimum} are required."
        )
    if len(included) > maximum:
        blockers.append(f"Portfolio has {len(included)} included claims; maximum is {maximum}.")
    if len(held_out) < held_out_minimum:
        blockers.append(
            f"Portfolio has {len(held_out)} held-out claims; at least {held_out_minimum} are required."
        )
    if pending:
        blockers.append(f"Atomicity review is pending for: {', '.join(pending)}.")
    if len(development) < 1:
        blockers.append("At least one development claim is required.")
    if not claims:
        warnings.append("No claims have been entered; no candidate claim was fabricated.")
    return StudyReadiness(
        ready=not blockers,
        included_claims=len(included),
        development_claims=len(development),
        held_out_claims=len(held_out),
        atomicity_pending=pending,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
    )


def load_claims(connection: sqlite3.Connection) -> list[AtomicClaim]:
    rows = connection.execute("SELECT payload_json FROM claims ORDER BY claim_id").fetchall()
    return [AtomicClaim.model_validate_json(row[0]) for row in rows]


def reviewer_packet(claims: list[AtomicClaim], reviewer: str) -> dict[str, object]:
    """Create a blind packet containing claims and instructions, never automated outcomes."""
    if not reviewer.strip():
        raise ValueError("A real reviewer identifier is required")
    included = [claim for claim in claims if claim.inclusion_status == "included"]
    reviewer_fields = (
        "claim_id",
        "claim_text",
        "subject",
        "predicate",
        "object",
        "process",
        "scope",
        "conditions",
        "applicable_start_date",
        "applicable_end_date",
        "claim_type",
        "evidence_target",
    )
    return {
        "packet_type": "blind_independent_review",
        "reviewer": reviewer.strip(),
        "instructions": [
            "Identify evidence in the supplied corpus and retain exact evidence locators.",
            "Assess target, scope, conditions, and temporal applicability separately.",
            "Classify each item as support, contradict, qualify, contextual, or not applicable.",
            "Record contextual credibility dimensions and justification.",
            "Choose one four-way outcome and separate confidence only after evidence review.",
            "Do not consult automated outcomes or another reviewer's judgements.",
            "Treat missing evidence as a gap, not automatic contradiction.",
        ],
        "claims": [
            {field: claim.model_dump(mode="json")[field] for field in reviewer_fields}
            for claim in included
        ],
        "automated_outcomes_included": False,
        "other_reviewer_judgements_included": False,
    }


def held_out_access_allowed(configuration: dict[str, object]) -> bool:
    """Unlock held-out comparison only after an explicitly frozen reasoning ruleset."""
    return (
        configuration.get("reasoning_ruleset_status") == "approved_and_frozen"
        and configuration.get("held_out_access_status") == "unlocked"
    )


def comparison_claims(
    claims: list[AtomicClaim], configuration: dict[str, object]
) -> list[AtomicClaim]:
    """Expose development claims until the held-out seal is explicitly released."""
    if held_out_access_allowed(configuration):
        return claims
    return [claim for claim in claims if claim.evaluation_split == "development"]


def write_configured_study_materials(
    claims: list[AtomicClaim], configuration: dict[str, object], output_dir: Path
) -> dict[str, object]:
    """Write reviewer-isolated blind workspaces from the approved study configuration."""
    if not configuration.get("packet_generation_authorised"):
        raise ValueError("Packet generation is not authorised")
    if configuration.get("portfolio_status") != "approved_and_frozen":
        raise ValueError("The portfolio must be approved and frozen")
    reviewers = configuration.get("reviewers")
    if not isinstance(reviewers, dict) or set(reviewers) != {"reviewer-a", "reviewer-b"}:
        raise ValueError("Configured reviewer-a and reviewer-b are required")
    output_dir.mkdir(parents=True, exist_ok=True)
    packet_paths = {}
    for reviewer_id, reviewer_name in reviewers.items():
        workspace = output_dir / reviewer_id
        workspace.mkdir(parents=True, exist_ok=True)
        packet = reviewer_packet(claims, str(reviewer_name))
        packet["reviewer_id"] = reviewer_id
        packet_path = workspace / "blind-review-packet.json"
        packet_path.write_text(json.dumps(packet, indent=2), encoding="utf-8")
        packet_paths[reviewer_id] = str(packet_path)
    manifest = {
        "portfolio_version": configuration["configuration_version"],
        "packet_count": 2,
        "reviewer_workspaces": packet_paths,
        "contains_split": False,
        "contains_verification_conclusions": False,
        "contains_automated_outcomes": False,
        "held_out_access_status": configuration["held_out_access_status"],
    }
    (output_dir / "packet_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return manifest


def write_study_materials(
    claims: list[AtomicClaim], reviewer_a: str, reviewer_b: str, output_dir: Path
) -> dict[str, object]:
    """Write two independent packets only when two real, distinct identifiers are provided."""
    if reviewer_a.strip() == reviewer_b.strip():
        raise ValueError("Two distinct reviewer identifiers are required")
    output_dir.mkdir(parents=True, exist_ok=True)
    packets = [reviewer_packet(claims, reviewer_a), reviewer_packet(claims, reviewer_b)]
    for packet in packets:
        safe = "".join(
            character if character.isalnum() or character in "-_" else "-"
            for character in str(packet["reviewer"])
        )
        (output_dir / f"blind-review-{safe}.json").write_text(
            json.dumps(packet, indent=2), encoding="utf-8"
        )
    readiness = validate_portfolio(claims)
    manifest = {
        "reviewers": [reviewer_a.strip(), reviewer_b.strip()],
        "packet_count": 2,
        "readiness": asdict(readiness),
        "contains_automated_outcomes": False,
    }
    (output_dir / "study_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return manifest
