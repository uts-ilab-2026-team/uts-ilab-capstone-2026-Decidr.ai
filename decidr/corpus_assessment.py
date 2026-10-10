"""Credibility assessment layered on Saif's structured retrieval engine.

Retrieval supplies ranked evidence and provenance metadata.  This module keeps
the separate responsibilities of deterministic evidence interpretation, graph
credibility scoring and independent human review.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3
from typing import Any

from decidr.config import DATABASE_PATH, PHASE2_DATA_DIR
from decidr.corpus_search import CorpusResult, CorpusSearchPackage, search_corpus
from decidr.database import connect, initialise_database
from decidr.ingestion import IngestionResult, ingest
from framework.graph_prototype import CONFIG_PATH
from framework.graph_prototype.core import (
    GraphCredibilityConfig,
    GraphCredibilityFramework,
    GraphEdge,
    GraphNode,
    OrganisationalGraph,
)

OUTCOMES = ("Supported", "Contradicted", "Contested", "Insufficient evidence")
PERCENT_RE = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*(?:%|percent\b)", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class NumericCondition:
    value: float
    unit: str
    operator: str | None
    role: str | None


@dataclass(frozen=True, slots=True)
class EvidenceInterpretation:
    evidence_id: str
    source_id: str
    locator: str
    quotation: str
    relationship: str
    mode: str
    confidence: float
    rationale: str
    claim_condition: NumericCondition | None
    evidence_condition: NumericCondition | None
    comparison_result: str | None
    scope_match: bool | None
    temporal_match: bool | None


def _stable_id(prefix: str, *parts: str) -> str:
    digest = sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _normalise_operator(text: str) -> str | None:
    lowered = text.casefold()
    if re.search(r"(?:at least|or greater|or more|>=|not less than)", lowered):
        return ">="
    if re.search(r"(?:above|greater than|more than|>)", lowered):
        return ">"
    if re.search(r"(?:at most|or less|<=|not more than|capped at)", lowered):
        return "<="
    if re.search(r"(?:below|less than|under|<)", lowered):
        return "<"
    return None


def _normalise_role(role: str | None) -> str | None:
    if not role:
        return None
    return re.sub(r"\s+", " ", role.casefold().replace("&", "and")).strip()


def _extract_role(text: str) -> str | None:
    patterns = (
        "Head of Finance and People Ops",
        "Head of Finance & People Ops",
        "Head of Finance",
        "Head of Engineering",
        "Head of Sales",
    )
    lowered = text.casefold()
    for role in patterns:
        if role.casefold() in lowered:
            return role.replace("&", "and")
    return None


def extract_numeric_condition(text: str) -> NumericCondition | None:
    """Extract a percentage threshold/value without guessing absent data."""
    match = PERCENT_RE.search(text)
    if not match:
        return None
    return NumericCondition(
        value=float(match.group("value")),
        unit="percent",
        operator=_normalise_operator(text),
        role=_extract_role(text),
    )


def _meets(actual: float, operator: str, threshold: float) -> bool:
    return {
        ">": actual > threshold,
        ">=": actual >= threshold,
        "<": actual < threshold,
        "<=": actual <= threshold,
    }[operator]


def _source_mode(source_type: str) -> str:
    formal = {"policy", "procedure", "process", "role-desc", "role_description", "decision-table"}
    return "formal" if source_type.casefold() in formal else "observed"


def _source_class(source_type: str) -> str:
    """Map ingestion source names to actual credibility configuration keys."""
    source_type = source_type.casefold()
    if source_type == "policy":
        return "approved_policy"
    if source_type in {"procedure", "process"}:
        return "approved_process"
    if source_type in {"role-desc", "role_description"}:
        return "role_description"
    if source_type in {"system-audit-log", "audit", "audit_events"}:
        return "system_verified"
    if source_type in {"crm", "crm_records", "project_tasks"}:
        return "structured_operational_record"
    if source_type == "meeting":
        return "meeting_record"
    if source_type == "interview":
        return "interview"
    if source_type == "internal_communication":
        return "self_reported_communication"
    return "unknown"


class AssessmentStore:
    """Saif ledger connection plus framework review records."""

    def __init__(self, path: Path = DATABASE_PATH) -> None:
        self.path = Path(path)
        initialise_database(self.path)
        self._initialise_review_tables()

    def _initialise_review_tables(self) -> None:
        with connect(self.path) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS framework_assessments (
                    assessment_id TEXT PRIMARY KEY,
                    claim_text TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    automated_outcome TEXT NOT NULL,
                    automated_confidence TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS framework_reviews (
                    review_id TEXT PRIMARY KEY,
                    assessment_id TEXT NOT NULL REFERENCES framework_assessments(assessment_id)
                        ON DELETE CASCADE,
                    reviewer TEXT NOT NULL,
                    verdict TEXT NOT NULL,
                    confidence TEXT NOT NULL,
                    notes TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS framework_reviews_reviewer_nocase
                    ON framework_reviews(assessment_id, lower(reviewer));
                CREATE TABLE IF NOT EXISTS framework_adjudications (
                    assessment_id TEXT PRIMARY KEY REFERENCES framework_assessments(assessment_id)
                        ON DELETE CASCADE,
                    adjudicator TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    confidence TEXT NOT NULL,
                    notes TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def counts(self) -> dict[str, int]:
        with connect(self.path) as connection:
            return {
                "sources": int(
                    connection.execute(
                        "SELECT COUNT(*) FROM sources WHERE source_id LIKE 'phase2:%'"
                    ).fetchone()[0]
                ),
                "evidence": int(
                    connection.execute(
                        """
                        SELECT COUNT(*)
                        FROM evidence e JOIN sources s ON s.source_id=e.source_id
                        WHERE s.source_id LIKE 'phase2:%'
                        """
                    ).fetchone()[0]
                ),
                "assessments": int(
                    connection.execute("SELECT COUNT(*) FROM framework_assessments").fetchone()[0]
                ),
                "reviews": int(
                    connection.execute("SELECT COUNT(*) FROM framework_reviews").fetchone()[0]
                ),
            }

    def ingest_configured_corpus(self) -> IngestionResult:
        """Ingest only the configured Phase 2 corpus used by this workflow."""
        return ingest(
            {"phase2": PHASE2_DATA_DIR},
            database_path=self.path,
        )

    def retrieve(
        self,
        claim: str,
        *,
        limit: int,
        semantic: bool = True,
        as_of: date | None = None,
    ) -> CorpusSearchPackage:
        with connect(self.path) as connection:
            return search_corpus(
                connection,
                claim,
                limit=limit,
                candidate_limit=max(limit * 3, 20),
                semantic=semantic,
                max_per_source=2,
                as_of=as_of,
                release="phase2",
            )

    def save_assessment(self, payload: dict[str, Any]) -> str:
        created_at = datetime.now(UTC).isoformat()
        assessment_id = _stable_id(
            "ASM",
            payload["claim_text"],
            payload["as_of"],
            "|".join(item["evidence_id"] for item in payload["retrieval"]["results"]),
            created_at,
        )
        payload["assessment_id"] = assessment_id
        with connect(self.path) as connection:
            connection.execute(
                """
                INSERT INTO framework_assessments VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    assessment_id,
                    payload["claim_text"],
                    payload["as_of"],
                    payload["automated_outcome"],
                    payload["automated_confidence"],
                    json.dumps(payload, ensure_ascii=False),
                    created_at,
                ),
            )
        return assessment_id

    def save_review(
        self,
        assessment_id: str,
        reviewer: str,
        verdict: str,
        confidence: str,
        notes: str,
    ) -> None:
        reviewer = reviewer.strip()
        if not reviewer:
            raise ValueError("Reviewer name is required")
        if not notes.strip():
            raise ValueError("An evidence-based explanation is required")
        review_id = _stable_id("REV", assessment_id, reviewer.casefold())
        try:
            with connect(self.path) as connection:
                connection.execute(
                    "INSERT INTO framework_reviews VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        review_id,
                        assessment_id,
                        reviewer,
                        verdict,
                        confidence,
                        notes.strip(),
                        datetime.now(UTC).isoformat(),
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise ValueError(
                "This reviewer has already submitted an immutable review for this assessment."
            ) from error

    def save_adjudication(
        self,
        assessment_id: str,
        adjudicator: str,
        outcome: str,
        confidence: str,
        notes: str,
    ) -> None:
        if not adjudicator.strip():
            raise ValueError("Adjudicator name is required")
        if not notes.strip():
            raise ValueError("An adjudication rationale is required")
        try:
            with connect(self.path) as connection:
                connection.execute(
                    "INSERT INTO framework_adjudications VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        assessment_id,
                        adjudicator.strip(),
                        outcome,
                        confidence,
                        notes.strip(),
                        datetime.now(UTC).isoformat(),
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise ValueError(
                "This assessment already has an immutable adjudication record."
            ) from error

    def register_rows(self) -> list[dict[str, Any]]:
        with connect(self.path) as connection:
            assessments = connection.execute(
                "SELECT * FROM framework_assessments ORDER BY created_at DESC"
            ).fetchall()
            results = []
            for item in assessments:
                reviews = connection.execute(
                    """
                    SELECT * FROM framework_reviews
                    WHERE assessment_id=? ORDER BY reviewer
                    """,
                    (item["assessment_id"],),
                ).fetchall()
                adjudication = connection.execute(
                    "SELECT * FROM framework_adjudications WHERE assessment_id=?",
                    (item["assessment_id"],),
                ).fetchone()
                verdicts = [row["verdict"] for row in reviews]
                if adjudication:
                    status = "Adjudicated final finding"
                    final_outcome = adjudication["outcome"]
                    final_confidence = adjudication["confidence"]
                elif len(reviews) < 2:
                    status = (
                        "Awaiting independent review" if not reviews else "Awaiting second review"
                    )
                    final_outcome = None
                    final_confidence = None
                elif len(set(verdicts)) == 1:
                    status = "Human-reviewed finding"
                    final_outcome = verdicts[0]
                    confidence_order = {
                        "Lower confidence": 0,
                        "Moderate confidence": 1,
                        "Higher confidence": 2,
                    }
                    final_confidence = min(
                        (row["confidence"] for row in reviews),
                        key=lambda value: confidence_order.get(value, 0),
                    )
                else:
                    status = "Needs adjudication"
                    final_outcome = None
                    final_confidence = None
                results.append(
                    {
                        "assessment_id": item["assessment_id"],
                        "claim_text": item["claim_text"],
                        "as_of": item["as_of"],
                        "automated_outcome": item["automated_outcome"],
                        "automated_confidence": item["automated_confidence"],
                        "status": status,
                        "final_outcome": final_outcome,
                        "final_confidence": final_confidence,
                        "human_reviewers": len(reviews),
                        "reviews": [dict(row) for row in reviews],
                        "payload": json.loads(item["payload_json"]),
                    }
                )
        return results


def interpret_evidence(claim: str, result: CorpusResult) -> EvidenceInterpretation:
    """Produce diagnostics without assigning an automatic evidential stance.

    Retrieval relevance, word overlap, a threshold match, or an observed breach cannot
    establish whether an item supports or contradicts a claim. Missing records may be
    identified as qualifications, but all other relationships remain unresolved until a
    reviewer or a separately validated interpreter supplies the judgement.
    """
    evidence_text = result.text
    claim_condition = extract_numeric_condition(claim)
    evidence_condition = extract_numeric_condition(evidence_text)
    lowered_claim = claim.casefold()
    lowered_evidence = evidence_text.casefold()
    missing_record = any(
        marker in lowered_evidence
        for marker in (
            "no linked",
            "no record found",
            "not found",
            "could not locate",
            "record is missing",
        )
    )
    approval_fields_missing = "approv" in lowered_claim and any(
        "approv" in field.casefold() or "sign" in field.casefold()
        for field in result.missing_fields
    )
    comparison_result: str | None = None
    temporal_match = {
        "applicable_to_query_period": True,
        "recorded_in_query_period": True,
        "recorded_by_assessment_date": True,
        "outside_query_period": False,
        "recorded_outside_query_period": False,
    }.get(result.temporal_status)

    if missing_record or approval_fields_missing:
        relationship = "qualify"
        confidence = 1.0
        rationale = (
            "The candidate is relevant but the required record or structured approval field is "
            "missing. Missing evidence is recorded as a gap, not proof of non-occurrence."
        )
    else:
        relationship = "unresolved"
        confidence = 0.0
        rationale = (
            "No automatic support or contradiction relationship was assigned. Retrieval "
            "relevance and word overlap do not establish semantic agreement, business scope, "
            "or whether an observed breach disproves a formal rule."
        )

    if claim_condition and evidence_condition and claim_condition.operator:
        triggered = _meets(
            evidence_condition.value,
            claim_condition.operator,
            claim_condition.value,
        )
        comparison_result = (
            f"{evidence_condition.value:g}% {'meets' if triggered else 'does not meet'} "
            f"the claim condition {claim_condition.operator} {claim_condition.value:g}%."
        )
        required_role = _normalise_role(claim_condition.role or _extract_role(claim))
        observed_role = _normalise_role(result.role or evidence_condition.role)
        role_mismatch = bool(required_role and observed_role and required_role != observed_role)
        if role_mismatch:
            comparison_result += " The named or recorded authority differs from the claim."

    return EvidenceInterpretation(
        evidence_id=result.evidence_id,
        source_id=result.source_id,
        locator=result.locator,
        quotation=result.text,
        relationship=relationship,
        mode=_source_mode(result.source_type),
        confidence=round(confidence, 3),
        rationale=rationale,
        claim_condition=claim_condition,
        evidence_condition=evidence_condition,
        comparison_result=comparison_result,
        scope_match=None,
        temporal_match=temporal_match,
    )


def _build_graph(
    claim: str,
    retrieved: tuple[CorpusResult, ...],
    interpretations: list[EvidenceInterpretation],
) -> GraphCredibilityFramework:
    fact_id = "fact:submitted-claim"
    nodes = [
        GraphNode(
            node_id=fact_id,
            kind="fact",
            label="Submitted claim",
            attributes={"statement": claim, "category": "corpus-assessment", "scope": claim},
        )
    ]
    edges: list[GraphEdge] = []
    for index, (candidate, interpretation) in enumerate(
        zip(retrieved, interpretations, strict=True),
        start=1,
    ):
        document_id = f"document:{candidate.evidence_id}"
        nodes.append(
            GraphNode(
                node_id=document_id,
                kind="document",
                label=candidate.source_title,
                attributes={
                    "type": candidate.source_type,
                    "status": candidate.lifecycle_status,
                    "approval_status": candidate.approval_status,
                    "effective_date": candidate.effective_start_date,
                    "effective_end_date": candidate.effective_end_date,
                    "last_updated": candidate.creation_date,
                    "source_class": _source_class(candidate.source_type),
                    "duplicate_group": candidate.provenance_group,
                },
            )
        )
        if interpretation.relationship not in {"support", "contradict"}:
            continue
        agrees = {"support": True, "contradict": False}.get(interpretation.relationship)
        applicable = interpretation.scope_match is True and interpretation.temporal_match is True
        edge_attributes: dict[str, Any] = {
            "attests_value": interpretation.quotation,
            "agrees": agrees,
            "applicable": applicable,
            "scope_match": interpretation.scope_match is True,
            "directness": (
                1.0
                if candidate.source_type
                in {"system-audit-log", "audit", "audit_events", "crm", "crm_records"}
                else 0.85
            ),
            "specificity": interpretation.confidence,
            "completeness": max(0.25, 1.0 - 0.08 * len(candidate.missing_fields)),
        }
        edges.append(
            GraphEdge(
                edge_id=f"attest:{index}:{candidate.evidence_id}",
                source=document_id,
                target=fact_id,
                relationship=interpretation.mode.upper(),
                attributes=edge_attributes,
            )
        )
    graph = OrganisationalGraph(nodes, edges, version="saif-retrieval-graph-assessment-v1")
    return GraphCredibilityFramework(graph, GraphCredibilityConfig.load(CONFIG_PATH))


def assess_claim(
    store: AssessmentStore,
    claim: str,
    *,
    as_of: date,
    limit: int = 8,
    semantic: bool = True,
    persist: bool = True,
) -> dict[str, Any]:
    """Retrieve candidates and prepare a provisional, human-reviewable assessment."""
    claim = claim.strip()
    if not claim:
        raise ValueError("Claim must not be blank")
    package = store.retrieve(claim, limit=limit, semantic=semantic, as_of=as_of)
    interpretations = [interpret_evidence(claim, item) for item in package.results]
    framework = _build_graph(claim, package.results, interpretations)
    graph_result = framework.evaluate_fact("fact:submitted-claim", as_of=as_of)
    payload: dict[str, Any] = {
        "schema_version": "saif-retrieval-graph-assessment-v1",
        "claim_text": claim,
        "as_of": as_of.isoformat(),
        "status": "retrieval_requires_human_interpretation",
        "automated_outcome": graph_result.overall_outcome,
        "automated_confidence": graph_result.confidence,
        "formal_outcome": graph_result.formal_outcome,
        "observed_outcome": graph_result.observed_outcome,
        "summary": graph_result.summary,
        "retrieval": {
            "query": package.query,
            "candidate_count": package.candidate_count,
            "unique_sources": package.unique_sources,
            "distinct_provenance_groups": package.distinct_provenance_groups,
            "duplicate_results_collapsed": package.duplicate_results_collapsed,
            "source_type_counts": package.source_type_counts,
            "semantic_status": package.semantic_status,
            "query_period_start": package.query_period_start,
            "query_period_end": package.query_period_end,
            "gap_signals": package.gap_signals,
            "results": [asdict(item) for item in package.results],
            "additional_linked_results": [
                asdict(item) for item in package.additional_linked_results
            ],
        },
        "interpretations": [asdict(item) for item in interpretations],
        "credibility": graph_result.model_dump(),
        "limitations": [
            "Saif's retrieval rank measures relevance, not credibility or truth.",
            "No automatic support or contradiction relationship is assigned.",
            (
                "Numeric comparison is diagnostic and does not turn noncompliance into evidence "
                "that a formal rule is false."
            ),
            "Business scope remains unresolved until explicitly judged.",
            "Semantic retrieval falls back safely when the local model is unavailable.",
            (
                "Explicit record identifiers add linked context but do not create support or "
                "contradiction relationships."
            ),
        ],
        "rules_applied": [
            "R1_SAIF_FTS5_BM25_RETRIEVAL",
            "R2_SAIF_RRF_SEMANTIC_WHEN_AVAILABLE",
            "R3_PROVENANCE_DUPLICATE_CONTROL",
            "R4_ASSESSMENT_DATE_TEMPORAL_RERANKING",
            "R5_MISSINGNESS_IS_A_GAP",
            "R6_NUMERIC_COMPARISON_IS_DIAGNOSTIC_ONLY",
            "R7_FORMAL_OBSERVED_SEPARATION",
            "R8_NO_AUTOMATIC_RELATIONSHIP_ASSIGNMENT",
            "R9_HUMAN_REVIEW_REQUIRED_FOR_FINAL_FACT",
            "R10_EXACT_RECORD_IDENTIFIER_LINKING",
            "R11_SECTION_CONTEXT_IS_GROUPED_NOT_INDEPENDENT",
        ],
    }
    payload["assessment_id"] = store.save_assessment(payload) if persist else None
    return json.loads(json.dumps(payload, ensure_ascii=False, allow_nan=False))


def evaluation_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    final = [row for row in rows if row["final_outcome"]]
    return {
        "final_findings": len(final),
        "automated_human_agreement": None,
        "limitation": (
            "Automated/human agreement is not reported because retrieval does not assign "
            "automatic evidential relationships."
        ),
    }
