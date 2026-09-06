"""Approach A: deterministic, reviewer-led lexical baseline.

This module intentionally contains no model calls or automatic relationship
classification. It resolves an existing claim, retrieves evidence with SQLite FTS5,
and applies the shared deterministic rules only to completed human reviews.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime
import json
from pathlib import Path
import sqlite3
from time import perf_counter
from typing import Any

from decidr.contracts import AssessmentResult, StructuredClaimResult
from decidr.explanation import render_explanation
from decidr.models import (
    AtomicClaim,
    ClaimEvidenceLink,
    CredibilityAssessment,
    EvidenceRelationship,
    Source,
)
from decidr.reasoning import ReasoningConfig, ReasoningResult, ReviewedEvidence, assess_claim
from decidr.retrieval import RetrievalResult, lexical_search


@dataclass(slots=True)
class RegisteredClaimParser:
    """Resolve only exact, pre-registered claim IDs or claim text.

    Approach A deliberately does not infer a structured claim from free text. An
    employee must select a frozen or manually registered atomic claim.
    """

    connection: sqlite3.Connection

    def parse(self, query: str) -> list[AtomicClaim]:
        """Return the one registered claim matching ``query`` exactly."""
        reference = query.strip().casefold()
        if not reference:
            raise ValueError("A claim ID or exact registered claim is required")
        rows = self.connection.execute(
            "SELECT payload_json FROM claims ORDER BY claim_id"
        ).fetchall()
        claims = [AtomicClaim.model_validate_json(row[0]) for row in rows]
        matches = [
            claim
            for claim in claims
            if claim.claim_id.casefold() == reference or claim.claim_text.casefold() == reference
        ]
        if not matches:
            raise LookupError(
                "Approach A only accepts an exact registered claim ID or claim wording"
            )
        if len(matches) > 1:
            raise ValueError("The claim reference is ambiguous; use the claim ID")
        if matches[0].inclusion_status != "included":
            raise ValueError("The selected claim is excluded from assessment")
        return matches


@dataclass(slots=True)
class LexicalRetriever:
    """Interpretable FTS5/BM25 retriever used by the baseline."""

    connection: sqlite3.Connection
    synonyms: dict[str, list[str]] | None = None

    def retrieve(self, claim: AtomicClaim, limit: int = 20) -> list[RetrievalResult]:
        """Retrieve ranked evidence and retain term-level match reasons."""
        return lexical_search(self.connection, claim, limit=limit, synonyms=self.synonyms)


def _period_justifies_superseded_source(claim: AtomicClaim, source: Source) -> bool:
    """Allow a superseded source only when the claim is explicitly scoped to its period."""
    if claim.applicable_start_date is None and claim.applicable_end_date is None:
        return False
    lower_bound = claim.applicable_start_date or date.min
    upper_bound = claim.applicable_end_date or date.max
    source_start = source.effective_start_date or date.min
    source_end = source.effective_end_date or date.max
    return source_start <= lower_bound and upper_bound <= source_end


def load_completed_human_reviews(
    connection: sqlite3.Connection,
    claim: AtomicClaim,
    reviewer: str,
) -> list[ReviewedEvidence]:
    """Load one reviewer's completed evidence judgements from the shared ledger."""
    rows = connection.execute(
        """
        SELECT l.payload_json, c.payload_json, s.payload_json,
               e.source_id, e.locator
        FROM claim_evidence_links l
        JOIN credibility_assessments c ON c.link_id=l.link_id
        JOIN evidence e ON e.evidence_id=l.evidence_id
        JOIN sources s ON s.source_id=e.source_id
        WHERE l.claim_id=? AND l.reviewer=?
        ORDER BY l.evidence_id
        """,
        (claim.claim_id, reviewer),
    ).fetchall()
    reviewed: list[ReviewedEvidence] = []
    for link_json, credibility_json, source_json, source_id, locator in rows:
        link = ClaimEvidenceLink.model_validate_json(link_json)
        if link.review_status != "complete" or link.method != "human_review":
            continue
        credibility = CredibilityAssessment.model_validate_json(credibility_json)
        source = Source.model_validate_json(source_json)
        reviewed.append(
            ReviewedEvidence(
                evidence_id=link.evidence_id,
                source_id=source_id,
                locator=locator,
                relationship=link.relationship,
                target_match=link.target_match,
                scope_match=link.scope_match,
                condition_match=link.condition_match,
                temporal_match=link.temporal_match,
                credibility=credibility,
                duplicate_group=source.duplicate_group,
                lifecycle_status=source.lifecycle_status,
                superseded_is_temporally_justified=_period_justifies_superseded_source(
                    claim, source
                ),
            )
        )
    return reviewed


def _review_is_complete(
    connection: sqlite3.Connection,
    claim_id: str,
    reviewer: str,
) -> bool:
    row = connection.execute(
        """
        SELECT 1 FROM claim_assessments
        WHERE claim_id=? AND reviewer=? AND review_status='complete'
        """,
        (claim_id, reviewer),
    ).fetchone()
    return row is not None


def to_assessment_result(
    claim: AtomicClaim,
    reasoning: ReasoningResult,
    *,
    query: str,
    runtime_metadata: dict[str, Any],
) -> AssessmentResult:
    """Translate the relational lexical baseline into the common comparison contract."""
    buckets = {relationship: [] for relationship in EvidenceRelationship}
    citations = []
    for item in reasoning.applicable:
        record = {
            "evidence_id": item.evidence_id,
            "source_id": item.source_id,
            "locator": item.locator,
            "relationship": item.relationship.value,
        }
        buckets[item.relationship].append(record)
        citations.append({key: record[key] for key in ("evidence_id", "source_id", "locator")})

    not_applicable = []
    dependent_groups = []
    for item, reason in reasoning.excluded:
        record = {
            "evidence_id": item.evidence_id,
            "source_id": item.source_id,
            "locator": item.locator,
            "relationship": item.relationship.value,
            "exclusion_reason": reason,
        }
        if "dependent duplicate" in reason:
            dependent_groups.append(record)
        else:
            not_applicable.append(record)

    metadata = {
        **runtime_metadata,
        "timestamp": datetime.now(UTC).isoformat(),
        "claim_version": claim.portfolio_version,
    }
    return AssessmentResult(
        approach_id="approach_a_relational_lexical",
        query=query,
        structured_claim=StructuredClaimResult(
            subject=claim.subject,
            predicate=claim.predicate,
            target_object=claim.object,
            scope=claim.scope,
            conditions=claim.conditions,
            applicable_period={
                "start": (
                    claim.applicable_start_date.isoformat()
                    if claim.applicable_start_date
                    else None
                ),
                "end": (
                    claim.applicable_end_date.isoformat() if claim.applicable_end_date else None
                ),
            },
            evidence_target=(
                claim.evidence_target.value if claim.evidence_target else "unspecified"
            ),
        ),
        outcome=reasoning.outcome,
        confidence=reasoning.confidence,
        supporting_evidence=buckets[EvidenceRelationship.SUPPORT],
        contradicting_evidence=buckets[EvidenceRelationship.CONTRADICT],
        qualifying_evidence=buckets[EvidenceRelationship.QUALIFY],
        contextual_evidence=buckets[EvidenceRelationship.CONTEXTUAL],
        not_applicable_evidence=not_applicable,
        dependent_evidence_groups=dependent_groups,
        evidence_gaps=list(reasoning.gaps),
        rules_applied=list(reasoning.traces),
        explanation=render_explanation(claim, reasoning),
        citations=citations,
        runtime_metadata=metadata,
    )


def run_approach_a(
    connection: sqlite3.Connection,
    query: str,
    claim: AtomicClaim,
    reviewer: str,
    config: dict[str, Any],
    corpus_fingerprint: str,
    *,
    reasoning_config: ReasoningConfig | None = None,
    expected_evidence_gaps: list[str] | None = None,
) -> AssessmentResult:
    """Run the complete no-LLM baseline using completed human relationships only."""
    if config.get("requires_completed_human_review", True) and not _review_is_complete(
        connection, claim.claim_id, reviewer
    ):
        raise ValueError(
            "Approach A is locked until this reviewer completes the blind claim assessment"
        )

    started = perf_counter()
    retrieval_started = perf_counter()
    limit = int(config.get("retrieval_limit", 30))
    retrieved = LexicalRetriever(connection).retrieve(claim, limit=limit)
    retrieval_latency_ms = (perf_counter() - retrieval_started) * 1000
    retrieved_ids = {item.evidence_id for item in retrieved}

    all_reviewed = load_completed_human_reviews(connection, claim, reviewer)
    reviewed = [item for item in all_reviewed if item.evidence_id in retrieved_ids]
    reviewed_ids = {item.evidence_id for item in reviewed}
    unreviewed_ids = sorted(retrieved_ids - reviewed_ids)
    gaps = list(expected_evidence_gaps or [])
    if not retrieved:
        gaps.append("Lexical retrieval returned no candidate evidence.")
    elif unreviewed_ids:
        gaps.append(
            f"{len(unreviewed_ids)} retrieved evidence unit(s) have no completed human review."
        )
    if not reviewed:
        gaps.append(
            "No completed human-reviewed relationship is available in the lexical result set."
        )

    reasoning = assess_claim(
        reviewed,
        expected_evidence_gaps=list(dict.fromkeys(gaps)),
        config=reasoning_config,
        evidence_target=claim.evidence_target,
    )
    retrieval_trace = [
        {
            "evidence_id": item.evidence_id,
            "source_id": item.source_id,
            "locator": item.locator,
            "rank": item.rank,
            "bm25_score": item.score,
            "matched_terms": list(item.matched_terms),
        }
        for item in retrieved
    ]
    runtime_metadata = {
        "configuration_version": config["configuration_version"],
        "corpus_fingerprint": corpus_fingerprint,
        "reviewer": reviewer,
        "claim_parser": config.get("claim_parser", "frozen_or_manual"),
        "retrieval_method": config.get("retriever", "sqlite_fts5_bm25"),
        "retrieval_limit": limit,
        "retrieved_count": len(retrieved),
        "reviewed_retrieved_count": len(reviewed),
        "reviewed_outside_current_result_count": len(all_reviewed) - len(reviewed),
        "retrieval_results": retrieval_trace,
        "relationship_source": "completed_human_review_only",
        "automatic_relationship_classification": False,
        "llm_used": False,
        "ruleset_version": config.get("ruleset_version", "deterministic_v1"),
        "latency_ms": {
            "lexical_retrieval": retrieval_latency_ms,
            "total": (perf_counter() - started) * 1000,
        },
    }
    return to_assessment_result(
        claim,
        reasoning,
        query=query,
        runtime_metadata=runtime_metadata,
    )


def load_profile(path: Path) -> dict[str, Any]:
    """Load the JSON-compatible YAML baseline profile."""
    return json.loads(path.read_text(encoding="utf-8"))
