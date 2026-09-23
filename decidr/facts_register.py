"""Derived facts register over the authoritative relational evidence ledger.

The register does not create a second store of truth.  It presents claim
candidates, review progress, and adjudicated findings from existing ledger
records.  A reviewer or automated result is never silently promoted to a final
organisational finding.
"""

import csv
from enum import StrEnum
from io import StringIO
import json
import sqlite3

from pydantic import Field

from decidr.database import save_claim
from decidr.models import (
    Adjudication,
    AtomicClaim,
    ClaimAssessment,
    ClaimOutcome,
    ConfidenceLevel,
    StrictModel,
)


class FactRecordStatus(StrEnum):
    """Lifecycle state of a row in the facts register."""

    CANDIDATE = "Candidate"
    REVIEW_IN_PROGRESS = "Review in progress"
    REVIEWED = "Reviewed - awaiting adjudication"
    ASSESSED_FINDING = "Assessed organisational finding"
    UNRESOLVED_DISAGREEMENT = "Unresolved reviewer disagreement"
    EXCLUDED = "Excluded"


class ReviewerFinding(StrictModel):
    """One reviewer's claim-level result, kept separate from the final finding."""

    reviewer: str
    outcome: ClaimOutcome
    confidence: ConfidenceLevel
    review_status: str
    explanation: str
    uncertainty_explanation: str


class FactRecord(StrictModel):
    """A safe, traceable facts-register projection for one atomic claim."""

    claim: AtomicClaim
    status: FactRecordStatus
    status_reason: str
    final_outcome: ClaimOutcome | None = None
    final_confidence: ConfidenceLevel | None = None
    finalised_by: str | None = None
    adjudication_id: str | None = None
    reviewer_findings: list[ReviewerFinding] = Field(default_factory=list)
    independent_human_reviewers: list[str] = Field(default_factory=list)
    evidence_review_count: int = 0
    credibility_review_count: int = 0
    source_count: int = 0
    evidence_gaps: list[str] = Field(default_factory=list)

    @property
    def is_final_finding(self) -> bool:
        """Return true only for a resolved, adjudicated organisational finding."""
        return self.status == FactRecordStatus.ASSESSED_FINDING


class FactsRegister:
    """Register and retrieve facts-register rows from one ledger connection."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def register_candidate(self, claim: AtomicClaim) -> FactRecord:
        """Add an atomic claim candidate without asserting that it is true."""
        save_claim(self.connection, claim)
        return self.get(claim.claim_id)

    def get(self, claim_id: str) -> FactRecord:
        """Build one facts-register row from claims, reviews, and adjudication."""
        claim_row = self.connection.execute(
            "SELECT payload_json FROM claims WHERE claim_id=?", (claim_id,)
        ).fetchone()
        if claim_row is None:
            raise KeyError(f"Unknown claim_id: {claim_id}")
        claim = AtomicClaim.model_validate_json(claim_row[0])

        assessment_rows = self.connection.execute(
            """
            SELECT payload_json FROM claim_assessments
            WHERE claim_id=?
            ORDER BY reviewer, assessment_id
            """,
            (claim_id,),
        ).fetchall()
        assessments = [ClaimAssessment.model_validate_json(row[0]) for row in assessment_rows]
        reviewer_findings = [
            ReviewerFinding(
                reviewer=item.reviewer,
                outcome=item.outcome,
                confidence=item.confidence,
                review_status=item.review_status,
                explanation=item.explanation,
                uncertainty_explanation=item.uncertainty_explanation,
            )
            for item in assessments
        ]
        human_reviewers = sorted(
            {
                item.reviewer
                for item in assessments
                if item.review_status == "complete" and not item.reviewer.startswith("automated:")
            }
        )

        adjudication_row = self.connection.execute(
            """
            SELECT payload_json FROM adjudications
            WHERE claim_id=?
            ORDER BY created_at DESC, adjudication_id DESC
            LIMIT 1
            """,
            (claim_id,),
        ).fetchone()
        adjudication = (
            Adjudication.model_validate_json(adjudication_row[0])
            if adjudication_row is not None
            else None
        )

        counts = self.connection.execute(
            """
            SELECT
                COUNT(DISTINCT l.link_id) AS evidence_reviews,
                COUNT(DISTINCT c.assessment_id) AS credibility_reviews,
                COUNT(DISTINCT e.source_id) AS source_count
            FROM claim_evidence_links l
            LEFT JOIN credibility_assessments c ON c.link_id=l.link_id
            LEFT JOIN evidence e ON e.evidence_id=l.evidence_id
            WHERE l.claim_id=?
            """,
            (claim_id,),
        ).fetchone()
        evidence_reviews, credibility_reviews, source_count = (int(value or 0) for value in counts)
        gaps = self._load_gaps(claim_id)

        status, reason = self._status(
            claim,
            assessments,
            evidence_reviews,
            adjudication,
        )
        final_outcome = None
        final_confidence = None
        finalised_by = None
        adjudication_id = None
        if adjudication is not None:
            adjudication_id = adjudication.adjudication_id
            if not adjudication.preserve_disagreement:
                final_outcome = adjudication.final_outcome
                final_confidence = adjudication.final_confidence
                finalised_by = adjudication.adjudicator

        return FactRecord(
            claim=claim,
            status=status,
            status_reason=reason,
            final_outcome=final_outcome,
            final_confidence=final_confidence,
            finalised_by=finalised_by,
            adjudication_id=adjudication_id,
            reviewer_findings=reviewer_findings,
            independent_human_reviewers=human_reviewers,
            evidence_review_count=evidence_reviews,
            credibility_review_count=credibility_reviews,
            source_count=source_count,
            evidence_gaps=gaps,
        )

    def list_records(self, *, include_excluded: bool = False) -> list[FactRecord]:
        """Return all register rows in stable claim-ID order."""
        rows = self.connection.execute(
            "SELECT claim_id, inclusion_status FROM claims ORDER BY claim_id"
        ).fetchall()
        return [self.get(row[0]) for row in rows if include_excluded or row[1] != "excluded"]

    def to_csv(self, *, include_excluded: bool = False) -> str:
        """Export a human-readable flat facts register without losing review status."""
        records = self.list_records(include_excluded=include_excluded)
        columns = [
            "claim_id",
            "claim_text",
            "subject",
            "predicate",
            "object",
            "scope",
            "applicable_start_date",
            "applicable_end_date",
            "status",
            "status_reason",
            "final_outcome",
            "final_confidence",
            "finalised_by",
            "independent_human_reviewers",
            "evidence_review_count",
            "credibility_review_count",
            "source_count",
            "evidence_gaps",
        ]
        handle = StringIO(newline="")
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    "claim_id": record.claim.claim_id,
                    "claim_text": record.claim.claim_text,
                    "subject": record.claim.subject,
                    "predicate": record.claim.predicate,
                    "object": record.claim.object,
                    "scope": record.claim.scope or "",
                    "applicable_start_date": record.claim.applicable_start_date or "",
                    "applicable_end_date": record.claim.applicable_end_date or "",
                    "status": record.status.value,
                    "status_reason": record.status_reason,
                    "final_outcome": record.final_outcome.value if record.final_outcome else "",
                    "final_confidence": (
                        record.final_confidence.value if record.final_confidence else ""
                    ),
                    "finalised_by": record.finalised_by or "",
                    "independent_human_reviewers": json.dumps(record.independent_human_reviewers),
                    "evidence_review_count": record.evidence_review_count,
                    "credibility_review_count": record.credibility_review_count,
                    "source_count": record.source_count,
                    "evidence_gaps": json.dumps(record.evidence_gaps),
                }
            )
        return handle.getvalue()

    def to_json(self, *, include_excluded: bool = False) -> str:
        """Export the complete nested register as readable JSON."""
        return json.dumps(
            [
                record.model_dump(mode="json")
                for record in self.list_records(include_excluded=include_excluded)
            ],
            indent=2,
        )

    def _load_gaps(self, claim_id: str) -> list[str]:
        rows = self.connection.execute(
            """
            SELECT t.details_json
            FROM rule_traces t
            JOIN claim_assessments a ON a.assessment_id=t.assessment_id
            WHERE a.claim_id=? AND t.rule_id='R5_MISSINGNESS_IS_A_GAP'
            ORDER BY t.trace_id
            """,
            (claim_id,),
        ).fetchall()
        gaps: list[str] = []
        for row in rows:
            details = json.loads(row[0])
            for gap in details.get("gaps", []):
                if gap not in gaps:
                    gaps.append(gap)
        return gaps

    @staticmethod
    def _status(
        claim: AtomicClaim,
        assessments: list[ClaimAssessment],
        evidence_review_count: int,
        adjudication: Adjudication | None,
    ) -> tuple[FactRecordStatus, str]:
        if claim.inclusion_status == "excluded":
            return FactRecordStatus.EXCLUDED, claim.exclusion_reason or "Claim was excluded."
        if adjudication is not None and adjudication.preserve_disagreement:
            return (
                FactRecordStatus.UNRESOLVED_DISAGREEMENT,
                "Independent reviewers disagreed and the adjudicator preserved the disagreement.",
            )
        if adjudication is not None:
            return (
                FactRecordStatus.ASSESSED_FINDING,
                "Two reviewer records were adjudicated into a final organisational finding.",
            )
        completed_human = [
            item
            for item in assessments
            if item.review_status == "complete" and not item.reviewer.startswith("automated:")
        ]
        if completed_human:
            return (
                FactRecordStatus.REVIEWED,
                "At least one human review is complete, but no final adjudication exists.",
            )
        if evidence_review_count or assessments:
            return (
                FactRecordStatus.REVIEW_IN_PROGRESS,
                "Evidence or claim review has started, but the human review is incomplete.",
            )
        return (
            FactRecordStatus.CANDIDATE,
            "The atomic claim is registered but has not yet been assessed.",
        )
