"""Strict validation of unapproved candidate-portfolio records."""

import csv
from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path

from decidr.models import AtomicClaim, EvidenceTarget


@dataclass(frozen=True, slots=True)
class ValidatedCandidate:
    claim: AtomicClaim
    applicable_period_status: str
    assessment_cutoff_date: date
    corpus_verification_status: str
    verified_fields: tuple[str, ...]
    inferred_fields: tuple[str, ...]
    unverified_fields: str | None
    verification_notes: str
    ingestion_completeness: str
    record_population_completeness: str
    claim_evidence_coverage: str
    eligible_case_count: int | None
    numerator_rule: str | None
    denominator_rule: str | None
    portfolio_status: str
    claim_version: str


REQUIRED_COLUMNS = (
    "candidate_claim_id",
    "exact_claim_wording",
    "subject",
    "relationship_predicate",
    "target_object",
    "process",
    "organisational_scope",
    "conditions",
    "evidence_target",
    "applicable_start_date",
    "applicable_end_date",
    "applicable_period_status",
    "assessment_cutoff_date",
    "claim_type",
    "evaluation_split",
    "corpus_verification_status",
    "verified_fields",
    "inferred_fields",
    "unverified_fields",
    "verification_notes",
    "ingestion_completeness",
    "record_population_completeness",
    "claim_evidence_coverage",
    "eligible_case_count",
    "numerator_rule",
    "denominator_rule",
    "portfolio_status",
    "claim_version",
)


def _optional_iso_date(value: str, field: str, claim_id: str) -> date | None:
    if not value:
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{claim_id} has non-ISO {field}: {value}") from error
    if parsed.isoformat() != value:
        raise ValueError(f"{claim_id} has non-canonical {field}: {value}")
    return parsed


def load_candidate_portfolio(
    portfolio_path: Path, study_config_path: Path
) -> list[ValidatedCandidate]:
    """Validate every candidate through AtomicClaim without inserting database rows."""
    configuration = json.loads(study_config_path.read_text(encoding="utf-8"))
    reviewers = configuration.get("reviewers", {})
    if (
        set(reviewers) != {"reviewer-a", "reviewer-b"}
        or len(set(reviewers.values())) != 2
        or any(not item.strip() for item in reviewers.values())
    ):
        raise ValueError(
            "Human-study configuration requires reviewer-a and reviewer-b with distinct names"
        )
    split_by_id = {
        claim_id: split
        for split, claim_ids in configuration["provisional_split"].items()
        for claim_id in claim_ids
    }
    with portfolio_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != REQUIRED_COLUMNS:
            raise ValueError(
                "Candidate portfolio columns are malformed or out of order; expected: "
                + ", ".join(REQUIRED_COLUMNS)
            )
        rows = list(reader)
    for row_number, row in enumerate(rows, start=2):
        if None in row or any(value is None for value in row.values()):
            raise ValueError(
                f"Candidate portfolio row {row_number} is column-shifted or missing fields"
            )
    candidates = []
    for row in rows:
        claim_id = row["candidate_claim_id"]
        if claim_id not in split_by_id:
            raise ValueError(f"{claim_id} is missing from the provisional split configuration")
        start = _optional_iso_date(row["applicable_start_date"], "applicable_start_date", claim_id)
        end = _optional_iso_date(row["applicable_end_date"], "applicable_end_date", claim_id)
        cutoff = _optional_iso_date(
            row["assessment_cutoff_date"], "assessment_cutoff_date", claim_id
        )
        if cutoff is None:
            raise ValueError(f"{claim_id} requires an assessment_cutoff_date")
        if row["evaluation_split"] != split_by_id[claim_id]:
            raise ValueError(f"{claim_id} split disagrees with the human-study configuration")
        if not row["verification_notes"]:
            raise ValueError(f"{claim_id} requires verification_notes")
        if not row["claim_version"]:
            raise ValueError(f"{claim_id} requires claim_version")
        if not row["verified_fields"]:
            raise ValueError(f"{claim_id} requires verified_fields")
        for completeness_field in (
            "ingestion_completeness",
            "record_population_completeness",
            "claim_evidence_coverage",
        ):
            if not row[completeness_field]:
                raise ValueError(f"{claim_id} requires {completeness_field}")
        eligible_count = None
        if row["eligible_case_count"]:
            try:
                eligible_count = int(row["eligible_case_count"])
            except ValueError as error:
                raise ValueError(f"{claim_id} has invalid eligible_case_count") from error
            if eligible_count < 0:
                raise ValueError(f"{claim_id} has negative eligible_case_count")
        is_quantitative = "more than half" in row["exact_claim_wording"].casefold()
        if is_quantitative and (
            not eligible_count or not row["numerator_rule"] or not row["denominator_rule"]
        ):
            raise ValueError(
                f"{claim_id} quantitative claim requires a non-zero eligible population "
                "and numerator/denominator rules"
            )
        claim = AtomicClaim(
            claim_id=claim_id,
            subject=row["subject"],
            predicate=row["relationship_predicate"],
            object=row["target_object"],
            process=row["process"],
            scope=row["organisational_scope"],
            conditions=[part.strip() for part in row["conditions"].split(";") if part.strip()],
            applicable_start_date=start,
            applicable_end_date=end,
            claim_type=row["claim_type"],
            evidence_target=EvidenceTarget(row["evidence_target"]),
            claim_text=row["exact_claim_wording"],
            original_claim_text=row["exact_claim_wording"],
            atomicity_status=(
                "confirmed_atomic"
                if row["portfolio_status"] == "approved_and_frozen"
                else "draft_candidate_reviewed_for_atomicity"
            ),
            evaluation_split=row["evaluation_split"],
            portfolio_status=row["portfolio_status"],
            portfolio_version=row["claim_version"],
        )
        candidates.append(
            ValidatedCandidate(
                claim=claim,
                applicable_period_status=row["applicable_period_status"],
                assessment_cutoff_date=cutoff,
                corpus_verification_status=row["corpus_verification_status"],
                verified_fields=tuple(
                    part.strip() for part in row["verified_fields"].split(";") if part.strip()
                ),
                inferred_fields=tuple(
                    part.strip() for part in row["inferred_fields"].split(";") if part.strip()
                ),
                unverified_fields=row["unverified_fields"] or None,
                verification_notes=row["verification_notes"],
                ingestion_completeness=row["ingestion_completeness"],
                record_population_completeness=row["record_population_completeness"],
                claim_evidence_coverage=row["claim_evidence_coverage"],
                eligible_case_count=eligible_count,
                numerator_rule=row["numerator_rule"] or None,
                denominator_rule=row["denominator_rule"] or None,
                portfolio_status=row["portfolio_status"],
                claim_version=row["claim_version"],
            )
        )
    if set(split_by_id) != {item.claim.claim_id for item in candidates}:
        raise ValueError("Provisional split and candidate portfolio IDs do not match")
    return candidates
