"""SQLite evidence-ledger initialisation."""

import json
from pathlib import Path
import sqlite3

from decidr.models import (
    Adjudication,
    AtomicClaim,
    ClaimAssessment,
    ClaimEvidenceLink,
    CredibilityAssessment,
    EvaluationError,
    Evidence,
    Source,
)

SCHEMA_VERSION = 5


def connect(path: Path) -> sqlite3.Connection:
    """Open a ledger connection with referential integrity enabled."""
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialise_database(path: Path) -> None:
    """Create the versioned evidence-ledger schema idempotently."""
    with connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS sources (
                source_id TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                checksum TEXT NOT NULL,
                original_file_path TEXT NOT NULL UNIQUE,
                ingestion_status TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_sources_checksum ON sources(checksum);
            CREATE TABLE IF NOT EXISTS evidence (
                evidence_id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL REFERENCES sources(source_id),
                locator TEXT NOT NULL,
                text_content TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                UNIQUE(source_id, locator)
            );
            CREATE TABLE IF NOT EXISTS claims (
                claim_id TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                evaluation_split TEXT NOT NULL CHECK(evaluation_split IN ('development','held_out')),
                inclusion_status TEXT NOT NULL CHECK(inclusion_status IN ('included','excluded'))
            );
            CREATE TABLE IF NOT EXISTS claim_versions (
                portfolio_version TEXT NOT NULL,
                claim_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(portfolio_version, claim_id)
            );
            CREATE TABLE IF NOT EXISTS claim_evidence_links (
                link_id TEXT PRIMARY KEY,
                claim_id TEXT NOT NULL REFERENCES claims(claim_id),
                evidence_id TEXT NOT NULL REFERENCES evidence(evidence_id),
                reviewer TEXT NOT NULL,
                relationship TEXT NOT NULL CHECK(relationship IN
                    ('support','contradict','qualify','contextual','not_applicable')),
                payload_json TEXT NOT NULL,
                UNIQUE(claim_id, evidence_id, reviewer)
            );
            CREATE TABLE IF NOT EXISTS credibility_assessments (
                assessment_id TEXT PRIMARY KEY,
                link_id TEXT NOT NULL REFERENCES claim_evidence_links(link_id),
                reviewer TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS claim_assessments (
                assessment_id TEXT PRIMARY KEY,
                claim_id TEXT NOT NULL REFERENCES claims(claim_id),
                reviewer TEXT NOT NULL,
                outcome TEXT NOT NULL CHECK(outcome IN
                    ('Supported','Contradicted','Contested','Insufficient evidence')),
                confidence TEXT NOT NULL,
                review_status TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                UNIQUE(claim_id, reviewer)
            );
            CREATE TABLE IF NOT EXISTS rule_traces (
                trace_id TEXT PRIMARY KEY,
                assessment_id TEXT NOT NULL REFERENCES claim_assessments(assessment_id),
                sequence_number INTEGER NOT NULL,
                rule_id TEXT NOT NULL,
                affected_evidence_json TEXT NOT NULL,
                details_json TEXT NOT NULL,
                UNIQUE(assessment_id, sequence_number)
            );
            CREATE TABLE IF NOT EXISTS audit_events (
                audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                actor TEXT NOT NULL,
                action TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                changed_fields_json TEXT NOT NULL,
                occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS evidence_fts USING fts5(
                evidence_id UNINDEXED,
                text_content,
                tokenize='porter unicode61'
            );
            CREATE TABLE IF NOT EXISTS embedding_cache (
                evidence_id TEXT NOT NULL REFERENCES evidence(evidence_id),
                model_name TEXT NOT NULL,
                model_version TEXT NOT NULL,
                content_checksum TEXT NOT NULL,
                vector_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(evidence_id, model_name, model_version)
            );
            CREATE TABLE IF NOT EXISTS adjudications (
                adjudication_id TEXT PRIMARY KEY,
                claim_id TEXT NOT NULL REFERENCES claims(claim_id),
                reviewer_a TEXT NOT NULL,
                reviewer_b TEXT NOT NULL,
                adjudicator TEXT NOT NULL,
                preserve_disagreement INTEGER NOT NULL CHECK(preserve_disagreement IN (0,1)),
                final_outcome TEXT,
                final_confidence TEXT,
                rationale TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(claim_id, reviewer_a, reviewer_b)
            );
            CREATE TABLE IF NOT EXISTS evaluation_errors (
                error_id TEXT PRIMARY KEY,
                claim_id TEXT NOT NULL REFERENCES claims(claim_id),
                category TEXT NOT NULL,
                component TEXT NOT NULL,
                reviewer TEXT NOT NULL,
                resolution_status TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS retrieval_runs (
                run_id TEXT PRIMARY KEY,
                claim_id TEXT NOT NULL REFERENCES claims(claim_id),
                method TEXT NOT NULL CHECK(method IN ('lexical','semantic','hybrid')),
                query_text TEXT NOT NULL,
                configuration_json TEXT NOT NULL,
                model_name TEXT,
                model_version TEXT,
                latency_ms REAL NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS retrieval_results (
                run_id TEXT NOT NULL REFERENCES retrieval_runs(run_id),
                evidence_id TEXT NOT NULL REFERENCES evidence(evidence_id),
                rank INTEGER NOT NULL,
                component_scores_json TEXT NOT NULL,
                PRIMARY KEY(run_id, evidence_id)
            );
            """
        )
        connection.executemany(
            "INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)",
            [(version,) for version in range(1, SCHEMA_VERSION + 1)],
        )


def upsert_source(connection: sqlite3.Connection, source: Source) -> None:
    """Insert or refresh a source record without creating duplicates."""
    connection.execute(
        """
        INSERT INTO sources(
            source_id, payload_json, checksum, original_file_path, ingestion_status
        ) VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(source_id) DO UPDATE SET
            payload_json=excluded.payload_json,
            checksum=excluded.checksum,
            original_file_path=excluded.original_file_path,
            ingestion_status=excluded.ingestion_status,
            updated_at=CURRENT_TIMESTAMP
        """,
        (
            source.source_id,
            source.model_dump_json(),
            source.checksum,
            source.original_file_path,
            source.ingestion_status,
        ),
    )


def upsert_source_evidence(
    connection: sqlite3.Connection, source_id: str, evidence: list[Evidence]
) -> None:
    """Insert or refresh extracted units while preserving reviewed evidence identities."""
    connection.executemany(
        """
        INSERT INTO evidence(
            evidence_id, source_id, locator, text_content, payload_json
        ) VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(evidence_id) DO UPDATE SET
            locator=excluded.locator,
            text_content=excluded.text_content,
            payload_json=excluded.payload_json
        """,
        [
            (
                item.evidence_id,
                item.source_id,
                item.locator,
                item.text,
                item.model_dump_json(),
            )
            for item in evidence
        ],
    )
    connection.executemany(
        "DELETE FROM evidence_fts WHERE evidence_id = ?",
        [(item.evidence_id,) for item in evidence],
    )
    connection.executemany(
        "INSERT INTO evidence_fts(evidence_id, text_content) VALUES (?, ?)",
        [(item.evidence_id, item.text) for item in evidence],
    )


def replace_source_evidence(
    connection: sqlite3.Connection,
    source_id: str,
    evidence: list[Evidence],
) -> None:
    """Atomically replace a source's complete passage snapshot."""
    if any(item.source_id != source_id for item in evidence):
        raise ValueError("Every passage must belong to the supplied source")
    if (
        connection.execute("SELECT 1 FROM sources WHERE source_id = ?", (source_id,)).fetchone()
        is None
    ):
        raise ValueError(f"Unknown source: {source_id}")

    connection.execute("SAVEPOINT replace_source_passages")
    try:
        connection.execute(
            """DELETE FROM evidence_fts WHERE evidence_id IN (
                SELECT evidence_id FROM evidence WHERE source_id = ?
            )""",
            (source_id,),
        )
        connection.execute("DELETE FROM evidence WHERE source_id = ?", (source_id,))
        connection.executemany(
            """INSERT INTO evidence(
                evidence_id, source_id, locator, text_content, payload_json
            ) VALUES (?, ?, ?, ?, ?)""",
            [
                (
                    item.evidence_id,
                    item.source_id,
                    item.locator,
                    item.text,
                    item.model_dump_json(),
                )
                for item in evidence
            ],
        )
        connection.executemany(
            "INSERT INTO evidence_fts(evidence_id, text_content) VALUES (?, ?)",
            [(item.evidence_id, item.text) for item in evidence],
        )
    except BaseException:
        connection.execute("ROLLBACK TO SAVEPOINT replace_source_passages")
        connection.execute("RELEASE SAVEPOINT replace_source_passages")
        raise
    else:
        connection.execute("RELEASE SAVEPOINT replace_source_passages")


def save_claim(connection: sqlite3.Connection, claim: AtomicClaim) -> None:
    """Create or update a validated claim."""
    existing_row = connection.execute(
        "SELECT payload_json FROM claims WHERE claim_id = ?", (claim.claim_id,)
    ).fetchone()
    if existing_row is not None:
        existing = AtomicClaim.model_validate_json(existing_row[0])
        if existing.portfolio_status == "approved_and_frozen":
            if existing.model_dump(mode="json") != claim.model_dump(mode="json"):
                raise ValueError(
                    f"{claim.claim_id} is frozen in {existing.portfolio_version}; "
                    "create an explicit versioned amendment instead"
                )
            return
    connection.execute(
        """
        INSERT INTO claims(claim_id, payload_json, evaluation_split, inclusion_status)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(claim_id) DO UPDATE SET
            payload_json=excluded.payload_json,
            evaluation_split=excluded.evaluation_split,
            inclusion_status=excluded.inclusion_status
        """,
        (
            claim.claim_id,
            claim.model_dump_json(),
            claim.evaluation_split,
            claim.inclusion_status,
        ),
    )
    record_audit(
        connection,
        actor="system",
        action="claim_saved",
        entity_type="claim",
        entity_id=claim.claim_id,
        changed_fields=claim.model_dump(mode="json"),
    )
    if claim.portfolio_version:
        connection.execute(
            """
            INSERT OR IGNORE INTO claim_versions(portfolio_version, claim_id, payload_json, status)
            VALUES (?, ?, ?, ?)
            """,
            (
                claim.portfolio_version,
                claim.claim_id,
                claim.model_dump_json(),
                claim.portfolio_status,
            ),
        )


def activate_frozen_portfolio_version(
    connection: sqlite3.Connection,
    claims: list[AtomicClaim],
    *,
    previous_version: str,
    reason: str,
    author: str,
    evaluation_validity_impact: str,
) -> None:
    """Archive the prior immutable payloads and activate an explicitly approved version."""
    if not claims or not all(
        claim.portfolio_status == "approved_and_frozen" and claim.portfolio_version
        for claim in claims
    ):
        raise ValueError("Every activated portfolio claim must be approved and frozen")
    if not all(value.strip() for value in (reason, author, evaluation_validity_impact)):
        raise ValueError("Version activation requires reason, author and validity impact")
    new_versions = {claim.portfolio_version for claim in claims}
    if len(new_versions) != 1 or previous_version in new_versions:
        raise ValueError("Activation requires one new portfolio version")
    for claim in claims:
        existing_row = connection.execute(
            "SELECT payload_json FROM claims WHERE claim_id=?", (claim.claim_id,)
        ).fetchone()
        if existing_row is not None:
            existing = AtomicClaim.model_validate_json(existing_row[0])
            if existing.portfolio_version != previous_version:
                raise ValueError(f"Unexpected predecessor version for {claim.claim_id}")
            connection.execute(
                "INSERT OR IGNORE INTO claim_versions VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)",
                (previous_version, claim.claim_id, existing_row[0], existing.portfolio_status),
            )
        connection.execute(
            """
            INSERT INTO claims(claim_id, payload_json, evaluation_split, inclusion_status)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(claim_id) DO UPDATE SET
                payload_json=excluded.payload_json,
                evaluation_split=excluded.evaluation_split,
                inclusion_status=excluded.inclusion_status
            """,
            (
                claim.claim_id,
                claim.model_dump_json(),
                claim.evaluation_split,
                claim.inclusion_status,
            ),
        )
        connection.execute(
            "INSERT OR IGNORE INTO claim_versions VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)",
            (
                claim.portfolio_version,
                claim.claim_id,
                claim.model_dump_json(),
                claim.portfolio_status,
            ),
        )
    record_audit(
        connection,
        actor=author,
        action="approved_portfolio_version_activated",
        entity_type="portfolio",
        entity_id=next(iter(new_versions)),
        changed_fields={
            "previous_version": previous_version,
            "reason": reason,
            "affected_claims": [claim.claim_id for claim in claims],
            "evaluation_validity_impact": evaluation_validity_impact,
        },
    )


def save_versioned_claim_amendment(
    connection: sqlite3.Connection,
    original_claim_id: str,
    amended_claim: AtomicClaim,
    *,
    reason: str,
    author: str,
    affected_claims: list[str],
    evaluation_validity_impact: str,
) -> None:
    """Create a new claim record while preserving an immutable frozen predecessor."""
    if not all(
        value.strip()
        for value in (
            reason,
            author,
            evaluation_validity_impact,
            amended_claim.portfolio_version or "",
        )
    ):
        raise ValueError(
            "Versioned amendments require reason, author, version and validity impact"
        )
    if not affected_claims or original_claim_id not in affected_claims:
        raise ValueError("affected_claims must include the frozen predecessor")
    original_row = connection.execute(
        "SELECT payload_json FROM claims WHERE claim_id = ?", (original_claim_id,)
    ).fetchone()
    if original_row is None:
        raise ValueError(f"Unknown frozen predecessor: {original_claim_id}")
    original = AtomicClaim.model_validate_json(original_row[0])
    if original.portfolio_status != "approved_and_frozen":
        raise ValueError("Only frozen claims use the versioned amendment workflow")
    if amended_claim.claim_id == original_claim_id:
        raise ValueError(
            "An amendment must use a new claim_id and must not overwrite the predecessor"
        )
    if amended_claim.portfolio_status != "versioned_amendment":
        raise ValueError("Amended claim must have portfolio_status='versioned_amendment'")
    save_claim(connection, amended_claim)
    record_audit(
        connection,
        actor=author,
        action="frozen_claim_versioned_amendment_created",
        entity_type="claim",
        entity_id=amended_claim.claim_id,
        changed_fields={
            "predecessor": original_claim_id,
            "reason": reason,
            "affected_claims": affected_claims,
            "evaluation_validity_impact": evaluation_validity_impact,
            "new_portfolio_version": amended_claim.portfolio_version,
        },
    )


def reset_test_records(connection: sqlite3.Connection) -> dict[str, int]:
    """Delete only explicitly test-namespaced assessments and links, preserving study data."""
    counts = {}
    operations = (
        (
            "rule_traces",
            "assessment_id IN (SELECT assessment_id FROM claim_assessments WHERE reviewer LIKE 'test:%')",
        ),
        ("credibility_assessments", "reviewer LIKE 'test:%'"),
        ("claim_assessments", "reviewer LIKE 'test:%'"),
        ("claim_evidence_links", "reviewer LIKE 'test:%'"),
    )
    for table, condition in operations:
        before = connection.total_changes
        connection.execute(f"DELETE FROM {table} WHERE {condition}")
        counts[table] = connection.total_changes - before
    record_audit(
        connection,
        actor="system:test-mode",
        action="test_records_reset",
        entity_type="test_namespace",
        entity_id="test:%",
        changed_fields=counts,
    )
    return counts


def save_link(connection: sqlite3.Connection, link: ClaimEvidenceLink) -> None:
    """Save one reviewer's claim-evidence judgement independently."""
    completed = connection.execute(
        "SELECT 1 FROM claim_assessments WHERE claim_id=? AND reviewer=? AND review_status='complete'",
        (link.claim_id, link.reviewer),
    ).fetchone()
    if completed is not None:
        raise ValueError("Completed reviewer assessments are locked")
    connection.execute(
        """
        INSERT INTO claim_evidence_links(
            link_id, claim_id, evidence_id, reviewer, relationship, payload_json
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(link_id) DO UPDATE SET
            relationship=excluded.relationship,
            payload_json=excluded.payload_json
        """,
        (
            link.link_id,
            link.claim_id,
            link.evidence_id,
            link.reviewer,
            link.relationship.value,
            link.model_dump_json(),
        ),
    )
    record_audit(
        connection,
        actor=link.reviewer,
        action="claim_evidence_review_saved",
        entity_type="claim_evidence_link",
        entity_id=link.link_id,
        changed_fields=link.model_dump(mode="json"),
    )


def save_credibility(connection: sqlite3.Connection, item: CredibilityAssessment) -> None:
    """Persist explicit credibility dimensions for a reviewed link."""
    reviewer = connection.execute(
        "SELECT reviewer FROM claim_evidence_links WHERE link_id = ?", (item.link_id,)
    ).fetchone()
    if reviewer is None:
        raise ValueError(f"Unknown link_id: {item.link_id}")
    connection.execute(
        """
        INSERT INTO credibility_assessments(assessment_id, link_id, reviewer, payload_json)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(assessment_id) DO UPDATE SET payload_json=excluded.payload_json
        """,
        (item.assessment_id, item.link_id, reviewer[0], item.model_dump_json()),
    )
    record_audit(
        connection,
        actor=reviewer[0],
        action="credibility_assessment_saved",
        entity_type="credibility_assessment",
        entity_id=item.assessment_id,
        changed_fields=item.model_dump(mode="json"),
    )


def save_claim_assessment(
    connection: sqlite3.Connection,
    assessment: ClaimAssessment,
    traces: list[dict[str, object]],
) -> None:
    """Persist an outcome and its reconstructable ordered rule trace."""
    existing = connection.execute(
        "SELECT review_status FROM claim_assessments WHERE claim_id=? AND reviewer=?",
        (assessment.claim_id, assessment.reviewer),
    ).fetchone()
    if existing is not None and existing[0] == "complete":
        raise ValueError("Completed reviewer assessments are locked")
    connection.execute(
        """
        INSERT INTO claim_assessments(
            assessment_id, claim_id, reviewer, outcome, confidence, review_status, payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(assessment_id) DO UPDATE SET
            outcome=excluded.outcome,
            confidence=excluded.confidence,
            review_status=excluded.review_status,
            payload_json=excluded.payload_json
        """,
        (
            assessment.assessment_id,
            assessment.claim_id,
            assessment.reviewer,
            assessment.outcome.value,
            assessment.confidence.value,
            assessment.review_status,
            assessment.model_dump_json(),
        ),
    )
    connection.execute(
        "DELETE FROM rule_traces WHERE assessment_id = ?", (assessment.assessment_id,)
    )
    connection.executemany(
        """
        INSERT INTO rule_traces(
            trace_id, assessment_id, sequence_number, rule_id,
            affected_evidence_json, details_json
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (
                f"{assessment.assessment_id}:trace:{index}",
                assessment.assessment_id,
                index,
                trace["rule_id"],
                json.dumps(trace.get("evidence_ids", [])),
                json.dumps(trace.get("details", {})),
            )
            for index, trace in enumerate(traces, start=1)
        ],
    )
    record_audit(
        connection,
        actor=assessment.reviewer,
        action="claim_assessment_saved",
        entity_type="claim_assessment",
        entity_id=assessment.assessment_id,
        changed_fields={
            "outcome": assessment.outcome.value,
            "confidence": assessment.confidence.value,
            "review_status": assessment.review_status,
            "rule_trace_count": len(traces),
        },
    )


def save_adjudication(connection: sqlite3.Connection, item: Adjudication) -> None:
    """Persist an adjudicator's resolution or explicit preservation of disagreement."""
    connection.execute(
        """
        INSERT INTO adjudications(
            adjudication_id, claim_id, reviewer_a, reviewer_b, adjudicator,
            preserve_disagreement, final_outcome, final_confidence, rationale, payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(adjudication_id) DO UPDATE SET
            adjudicator=excluded.adjudicator,
            preserve_disagreement=excluded.preserve_disagreement,
            final_outcome=excluded.final_outcome,
            final_confidence=excluded.final_confidence,
            rationale=excluded.rationale,
            payload_json=excluded.payload_json
        """,
        (
            item.adjudication_id,
            item.claim_id,
            item.reviewer_a,
            item.reviewer_b,
            item.adjudicator,
            int(item.preserve_disagreement),
            item.final_outcome.value if item.final_outcome else None,
            item.final_confidence.value if item.final_confidence else None,
            item.rationale,
            item.model_dump_json(),
        ),
    )
    record_audit(
        connection,
        actor=item.adjudicator,
        action="adjudication_saved",
        entity_type="adjudication",
        entity_id=item.adjudication_id,
        changed_fields=item.model_dump(mode="json"),
    )


def save_evaluation_error(connection: sqlite3.Connection, item: EvaluationError) -> None:
    """Persist a per-claim error-taxonomy record for qualitative analysis."""
    connection.execute(
        """
        INSERT INTO evaluation_errors(
            error_id, claim_id, category, component, reviewer,
            resolution_status, payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(error_id) DO UPDATE SET
            category=excluded.category,
            component=excluded.component,
            reviewer=excluded.reviewer,
            resolution_status=excluded.resolution_status,
            payload_json=excluded.payload_json
        """,
        (
            item.error_id,
            item.claim_id,
            item.category,
            item.component,
            item.reviewer,
            item.resolution_status,
            item.model_dump_json(),
        ),
    )
    record_audit(
        connection,
        actor=item.reviewer,
        action="evaluation_error_saved",
        entity_type="evaluation_error",
        entity_id=item.error_id,
        changed_fields=item.model_dump(mode="json"),
    )


def record_audit(
    connection: sqlite3.Connection,
    actor: str,
    action: str,
    entity_type: str,
    entity_id: str,
    changed_fields: dict[str, object],
) -> None:
    """Append a structured mutation event."""
    connection.execute(
        """
        INSERT INTO audit_events(actor, action, entity_type, entity_id, changed_fields_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (actor, action, entity_type, entity_id, json.dumps(changed_fields, default=str)),
    )


def save_retrieval_run(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    claim_id: str,
    method: str,
    query_text: str,
    configuration: dict[str, object],
    latency_ms: float,
    results: list[dict[str, object]],
    model_name: str | None = None,
    model_version: str | None = None,
) -> None:
    """Persist retrieval provenance, component scores, ranks, and latency."""
    connection.execute(
        """
        INSERT INTO retrieval_runs(
            run_id, claim_id, method, query_text, configuration_json,
            model_name, model_version, latency_ms
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            claim_id,
            method,
            query_text,
            json.dumps(configuration),
            model_name,
            model_version,
            latency_ms,
        ),
    )
    connection.executemany(
        """
        INSERT INTO retrieval_results(run_id, evidence_id, rank, component_scores_json)
        VALUES (?, ?, ?, ?)
        """,
        [
            (
                run_id,
                result["evidence_id"],
                result["rank"],
                json.dumps(result.get("component_scores", {})),
            )
            for result in results
        ],
    )
    record_audit(
        connection,
        actor="system",
        action="retrieval_run_created",
        entity_type="retrieval_run",
        entity_id=run_id,
        changed_fields={"method": method, "result_count": len(results)},
    )
