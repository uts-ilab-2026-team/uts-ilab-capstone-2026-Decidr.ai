"""Regression tests for the selectively integrated retrieval safeguards."""

from datetime import date
from hashlib import sha256
from pathlib import Path

import pytest

from decidr.assessment_adapter import PreparedAttestation, assess_prepared_facet
from decidr.corpus_search import search_corpus
from decidr.database import (
    connect,
    initialise_database,
    replace_source_evidence,
    upsert_source,
)
from decidr.ingestion import build_source, ingest
from decidr.interpretation_models import (
    EvidenceInterpretation,
    InterpretationCitation,
    validate_interpretation,
)
from decidr.models import Evidence, Source
from decidr.retrieval import find_record_references
from framework.graph_prototype import CONFIG_PATH
from framework.graph_prototype.core import (
    GraphCredibilityConfig,
    GraphCredibilityFramework,
    GraphEdge,
    GraphNode,
    OrganisationalGraph,
)


def _source(source_id: str = "phase2:POL-01") -> Source:
    return Source(
        source_id=source_id,
        title="Approval policy",
        original_file_path=f"{source_id}.md",
        source_type="policy",
        effective_start_date=date(2026, 1, 1),
        last_updated_date=date(2026, 1, 1),
        lifecycle_status="current",
        approval_status="approved",
        ingestion_status="registered",
        checksum=sha256(source_id.encode()).hexdigest(),
    )


def _evidence(
    evidence_id: str,
    source: Source,
    text: str,
    *,
    locator: str,
    section: str | None = None,
    row_identifier: str | None = None,
    related_record: str | None = None,
) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        source_id=source.source_id,
        locator=locator,
        text=text,
        source_type=source.source_type,
        section=section,
        heading=section,
        row_identifier=row_identifier,
        extraction_method="markdown_heading_blocks_v1" if section else "csv_dict_row_v1",
        structured_metadata={"record": {"related_record": related_record}},
    )


def test_document_header_metadata_does_not_leak_from_body(tmp_path: Path) -> None:
    path = tmp_path / "POL-01.md"
    path.write_text(
        "# Approval policy\n\n"
        "- **Approval Status:** Approved\n"
        "- **Effective Date:** 2026-01-01\n\n"
        "## Historical note\n\n"
        "- **Approval Status:** Draft\n"
        "- **Effective Date:** 2022-01-01\n",
        encoding="utf-8",
    )
    source = build_source(path, tmp_path, "phase2")
    assert source.lifecycle_status == "current"
    assert source.effective_start_date == date(2026, 1, 1)
    assert {entry["value"] for entry in source.header_evidence} == {
        "Approved",
        "2026-01-01",
    }


def test_conflicting_repeated_header_value_remains_unresolved(tmp_path: Path) -> None:
    path = tmp_path / "POL-02.md"
    path.write_text(
        "# Policy\n- **Approval Status:** Approved\n- **Approval Status:** Draft\n\nBody.\n",
        encoding="utf-8",
    )
    source = build_source(path, tmp_path, "phase2")
    assert source.approval_status is None
    assert source.lifecycle_status == "unknown"
    assert any(item["field"] == "approval_status" for item in source.metadata_conflicts)


def test_incomplete_ingestion_does_not_publish_partial_snapshot(tmp_path: Path) -> None:
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "POL-01.md").write_text("# Policy\n\nFinance approval is required.\n")
    database = tmp_path / "ledger.sqlite3"
    ingest({"phase2": root}, database)
    before = database.read_bytes()
    (root / "bad.csv").write_bytes(b"\xff\xfe\x00")
    with pytest.raises(ValueError, match="not updated"):
        ingest({"phase2": root}, database)
    assert database.read_bytes() == before


def test_atomic_source_replacement_removes_stale_passages(tmp_path: Path) -> None:
    database = tmp_path / "ledger.sqlite3"
    initialise_database(database)
    source = _source()
    old = _evidence("EV-old", source, "old text", locator="old")
    new = _evidence("EV-new", source, "new text", locator="new")
    with connect(database) as connection:
        upsert_source(connection, source)
        replace_source_evidence(connection, source.source_id, [old])
        replace_source_evidence(connection, source.source_id, [new])
        rows = connection.execute("SELECT evidence_id FROM evidence").fetchall()
    assert [row[0] for row in rows] == ["EV-new"]


def test_exact_record_references_distinguish_reference_types() -> None:
    source = _source("phase2:AUD-01")
    passages = [
        _evidence(
            "EV-self",
            source,
            "Audit event AUD-0111 was created.",
            locator="row:1",
            row_identifier="AUD-0111",
        ),
        _evidence(
            "EV-related",
            source,
            "A related incident exists.",
            locator="row:2",
            related_record="AUD-0111",
        ),
        _evidence(
            "EV-text",
            source,
            "The meeting discussed AUD-0111.",
            locator="row:3",
        ),
    ]
    references = find_record_references("Review AUD-0111", passages)
    assert {item.relationship for item in references} == {
        "record_itself",
        "structured_reference",
        "textual_mention",
    }


def test_markdown_retrieval_groups_section_context_without_claiming_independence(
    tmp_path: Path,
) -> None:
    database = tmp_path / "ledger.sqlite3"
    initialise_database(database)
    source = _source()
    passages = [
        _evidence(
            "EV-1",
            source,
            "Finance approval applies to new-business discounts.",
            locator="heading:Approval#block:001",
            section="Approval",
        ),
        _evidence(
            "EV-2",
            source,
            "Written approval is required before Closed Won.",
            locator="heading:Approval#block:002",
            section="Approval",
        ),
    ]
    with connect(database) as connection:
        upsert_source(connection, source)
        replace_source_evidence(connection, source.source_id, passages)
        package = search_corpus(
            connection,
            "Finance written approval Closed Won",
            semantic=False,
        )
    assert len(package.results) == 1
    assert len(package.results[0].passages) == 2
    assert package.results[0].provenance_group == source.source_id


def test_citation_validation_rejects_modified_quotation() -> None:
    source = _source()
    passage = _evidence(
        "EV-1",
        source,
        "Finance approval is required.",
        locator="heading:Approval#block:001",
    )
    valid = EvidenceInterpretation(
        claim_text="Finance approval is required.",
        facet="approval requirement",
        stance="support",
        mode="formal",
        rationale="The policy states the requirement.",
        citations=(
            InterpretationCitation(
                evidence_id=passage.evidence_id,
                source_id=passage.source_id,
                locator=passage.locator,
                quotation="Finance approval",
                start=0,
                end=16,
            ),
        ),
    )
    assert validate_interpretation(valid, [passage], claim_text=valid.claim_text) is valid
    altered = valid.model_copy(
        update={
            "citations": (valid.citations[0].model_copy(update={"quotation": "Finance Approval"}),)
        }
    )
    with pytest.raises(ValueError, match="Quotation does not match"):
        validate_interpretation(altered, [passage], claim_text=valid.claim_text)


def test_facet_adapter_only_scores_explicit_eligible_judgement() -> None:
    source = _source()
    passage = _evidence(
        "EV-1",
        source,
        "Finance approval is required.",
        locator="heading:Approval#block:001",
    )
    interpretation = EvidenceInterpretation(
        claim_text="Finance approval is required.",
        facet="approval requirement",
        stance="support",
        mode="formal",
        rationale="Reviewer matched the policy statement to the facet.",
        citations=(
            InterpretationCitation(
                evidence_id=passage.evidence_id,
                source_id=passage.source_id,
                locator=passage.locator,
                quotation=passage.text,
                start=0,
                end=len(passage.text),
            ),
        ),
    )
    result = assess_prepared_facet(
        claim_text=interpretation.claim_text,
        facet=interpretation.facet,
        as_of=date(2026, 7, 31),
        prepared=[
            PreparedAttestation(
                interpretation=interpretation,
                source=source,
                origin_id="origin:policy",
                source_class="approved_policy",
                approval_key="approved",
                scope_matches=True,
                temporal_matches=True,
                authority_verified=True,
                directness=1.0,
                specificity=1.0,
                completeness=1.0,
                judgement_basis="Independent human review.",
                origin_basis="Original policy document.",
            )
        ],
        evidence=[passage],
        config=GraphCredibilityConfig.load(CONFIG_PATH),
    )
    assert result.assessment.formal_outcome == "Supported"
    assert result.inputs[0].edge_id == "edge:1"


def test_effective_period_is_an_applicability_gate() -> None:
    nodes = [
        GraphNode("fact", "fact", "Claim", {"statement": "Claim"}),
        GraphNode(
            "document:expired",
            "document",
            "Expired policy",
            {
                "status": "current",
                "approval_status": "approved",
                "source_class": "approved_policy",
                "effective_date": "2024-01-01",
                "effective_end_date": "2025-12-31",
            },
        ),
    ]
    edges = [
        GraphEdge(
            "edge:expired",
            "document:expired",
            "fact",
            "FORMAL",
            {
                "attests_value": "Claim",
                "agrees": True,
                "applicable": True,
                "scope_match": True,
                "directness": 1.0,
                "specificity": 1.0,
                "completeness": 1.0,
            },
        )
    ]
    framework = GraphCredibilityFramework(
        OrganisationalGraph(nodes, edges, version="test"),
        GraphCredibilityConfig.load(CONFIG_PATH),
    )
    result = framework.evaluate_fact("fact", as_of=date(2026, 7, 31))
    assert result.evidence[0].applicable is False
    assert result.overall_outcome == "Insufficient evidence"
