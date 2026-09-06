import sqlite3

import pytest

from decidr.approach_a import RegisteredClaimParser, run_approach_a
from decidr.models import (
    AtomicClaim,
    ClaimEvidenceLink,
    ClaimOutcome,
    CredibilityAssessment,
    EvidenceMode,
    EvidenceRelationship,
    Source,
)


PROFILE = {
    "approach_id": "approach_a_relational_lexical",
    "configuration_version": "1.1",
    "claim_parser": "frozen_or_manual",
    "retriever": "sqlite_fts5_bm25",
    "retrieval_limit": 30,
    "requires_completed_human_review": True,
    "ruleset_version": "deterministic_v1",
}


def _ledger() -> tuple[sqlite3.Connection, AtomicClaim]:
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        CREATE TABLE claims (claim_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL);
        CREATE TABLE sources (source_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL);
        CREATE TABLE evidence (
            evidence_id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            locator TEXT NOT NULL,
            text_content TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE evidence_fts USING fts5(
            evidence_id UNINDEXED, text_content, tokenize='porter unicode61'
        );
        CREATE TABLE claim_evidence_links (
            link_id TEXT PRIMARY KEY,
            claim_id TEXT NOT NULL,
            evidence_id TEXT NOT NULL,
            reviewer TEXT NOT NULL,
            payload_json TEXT NOT NULL
        );
        CREATE TABLE credibility_assessments (
            assessment_id TEXT PRIMARY KEY,
            link_id TEXT NOT NULL,
            payload_json TEXT NOT NULL
        );
        CREATE TABLE claim_assessments (
            claim_id TEXT NOT NULL,
            reviewer TEXT NOT NULL,
            review_status TEXT NOT NULL
        );
        """
    )
    claim = AtomicClaim(
        claim_id="C1",
        subject="discount",
        predicate="requires",
        object="finance approval",
        claim_type="control",
        claim_text="Discounts require Finance approval.",
    )
    source = Source(
        source_id="S1",
        title="Discount policy",
        original_file_path="POL-01.md",
        source_type="policy",
        lifecycle_status="current",
        checksum="a" * 64,
    )
    link = ClaimEvidenceLink(
        link_id="L1",
        claim_id=claim.claim_id,
        evidence_id="E1",
        relationship=EvidenceRelationship.SUPPORT,
        applicability_reason="The policy directly states the approval requirement.",
        target_match=True,
        scope_match=True,
        condition_match=True,
        temporal_match=True,
        reviewer="reviewer-a",
        review_status="complete",
    )
    credibility = CredibilityAssessment(
        assessment_id="CA1",
        link_id=link.link_id,
        relevance=0.9,
        institutional_authority=0.9,
        directness=0.9,
        temporal_validity=0.9,
        independence=0.9,
        completeness=0.9,
        organisational_applicability=0.9,
        evidence_mode=EvidenceMode.FORMAL_RULE,
        reviewer_justification="Current approved policy with a direct statement.",
    )
    connection.execute(
        "INSERT INTO claims VALUES (?, ?)", (claim.claim_id, claim.model_dump_json())
    )
    connection.execute(
        "INSERT INTO sources VALUES (?, ?)", (source.source_id, source.model_dump_json())
    )
    evidence_text = "Finance approval is required for discounts."
    connection.execute(
        "INSERT INTO evidence VALUES (?, ?, ?, ?)",
        ("E1", source.source_id, "section:rule#block:1", evidence_text),
    )
    connection.execute("INSERT INTO evidence_fts VALUES (?, ?)", ("E1", evidence_text))
    connection.execute(
        "INSERT INTO claim_evidence_links VALUES (?, ?, ?, ?, ?)",
        (link.link_id, claim.claim_id, "E1", link.reviewer, link.model_dump_json()),
    )
    connection.execute(
        "INSERT INTO credibility_assessments VALUES (?, ?, ?)",
        (credibility.assessment_id, link.link_id, credibility.model_dump_json()),
    )
    return connection, claim


def test_registered_claim_parser_accepts_only_exact_registered_claims():
    connection, claim = _ledger()

    assert RegisteredClaimParser(connection).parse("C1") == [claim]
    with pytest.raises(LookupError):
        RegisteredClaimParser(connection).parse("Does a discount need approval?")


def test_baseline_requires_completed_blind_review():
    connection, claim = _ledger()

    with pytest.raises(ValueError, match="locked"):
        run_approach_a(connection, claim.claim_text, claim, "reviewer-a", PROFILE, "fixture")


def test_baseline_uses_human_reviews_and_never_an_llm():
    connection, claim = _ledger()
    connection.execute("INSERT INTO claim_assessments VALUES ('C1', 'reviewer-a', 'complete')")

    result = run_approach_a(
        connection,
        claim.claim_text,
        claim,
        "reviewer-a",
        PROFILE,
        "fixture-fingerprint",
    )

    assert result.outcome == ClaimOutcome.SUPPORTED
    assert result.supporting_evidence[0]["evidence_id"] == "E1"
    assert result.citations == [
        {"evidence_id": "E1", "source_id": "S1", "locator": "section:rule#block:1"}
    ]
    assert result.runtime_metadata["relationship_source"] == "completed_human_review_only"
    assert result.runtime_metadata["automatic_relationship_classification"] is False
    assert result.runtime_metadata["llm_used"] is False
    assert result.runtime_metadata["corpus_fingerprint"] == "fixture-fingerprint"
