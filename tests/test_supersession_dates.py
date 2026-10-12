"""Supersession boundaries remain distinct from inclusive effective end dates."""

from datetime import date

from framework import CONFIG_PATH, GraphCredibilityFramework, GraphFactsRegister
from framework.config import GraphCredibilityConfig
from framework.errors import GraphValidationError
from framework.graph import OrganisationalGraph
from framework.models import GraphEdge, GraphNode
import pytest

from decidr.assessment_adapter import PreparedAttestation, assess_prepared_facet
from decidr.interpretation_models import EvidenceInterpretation, InterpretationCitation
from decidr.retrieval_models import Evidence, Source


def engine(*documents):
    nodes = [GraphNode("fact:test", "fact", "Approval required")]
    edges = []
    for index, changes in enumerate(documents):
        nodes.append(
            GraphNode(
                f"document:{index}",
                "document",
                "Policy",
                {
                    "source_class": "approved_policy",
                    "approval_status": "approved",
                    "status": "superseded",
                    "effective_date": "2024-01-01",
                    "superseded_date": "2025-01-01",
                    **changes,
                },
            )
        )
        edges.append(
            GraphEdge(
                f"edge:{index}",
                f"document:{index}",
                "fact:test",
                "FORMAL",
                {
                    "attests_value": "Approval required",
                    "agrees": True,
                    "independence_verified": True,
                    "independence_basis": "Synthetic origins stipulated independent of other groups.",
                    "directness": 1.0,
                    "specificity": 1.0,
                    "completeness": 1.0,
                },
            )
        )
    return GraphCredibilityFramework(
        OrganisationalGraph(nodes, edges, version="supersession-test"),
        GraphCredibilityConfig.load(CONFIG_PATH),
    )


@pytest.mark.parametrize(
    "when,eligible",
    [
        ("2023-12-31", False),
        ("2024-01-01", True),
        ("2024-12-31", True),
        ("2025-01-01", False),
        ("2025-01-02", False),
    ],
)
def test_supersession_boundary_and_export(when, eligible):
    framework = engine({})
    register = GraphFactsRegister(framework, as_of=date.fromisoformat(when))
    record = register.get("fact:test")
    evidence = record.evidence[0]
    assert evidence.applicable is eligible
    assert evidence.material is eligible
    assert evidence.lifecycle_status == "superseded"
    assert framework.graph.document("document:0").attributes["superseded_date"] == "2025-01-01"
    assert "effective_end_date" not in framework.graph.document("document:0").attributes
    if when == "2025-01-01":
        assert "boundary inclusion is unspecified" in register.to_json()
    if not eligible:
        assert evidence.materiality_score is None


def test_historical_scoring_and_corroboration_match_current_sources():
    when = date(2024, 12, 31)
    historical = engine({}, {}).evaluate_fact("fact:test", as_of=when)
    current = engine({"status": "current"}, {"status": "current"}).evaluate_fact(
        "fact:test", as_of=when
    )
    assert historical.evidence[0].materiality_score == current.evidence[0].materiality_score
    assert historical.evidence[0].dimensions["corroboration"] == 0.75


def test_missing_start_does_not_restore_historical_lifecycle():
    result = engine({"effective_date": None}).evaluate_fact("fact:test", as_of=date(2024, 12, 31))
    assert result.overall_outcome == "Insufficient evidence"
    assert not any("Historical lifecycle" in line for line in result.evidence[0].trace)


@pytest.mark.parametrize(
    "end,when,eligible",
    [
        ("2024-12-30", "2024-12-30", True),
        ("2024-12-30", "2024-12-31", False),
        ("2025-01-01", "2025-01-01", False),
        ("2025-02-01", "2025-01-02", False),
    ],
)
def test_both_boundaries_must_be_satisfied(end, when, eligible):
    result = engine({"effective_end_date": end}).evaluate_fact(
        "fact:test", as_of=date.fromisoformat(when)
    )
    assert result.evidence[0].applicable is eligible


@pytest.mark.parametrize("value", ["not-a-date", "2025-02-30", "20250101", 20250101])
def test_malformed_supersession_date_is_rejected(value):
    with pytest.raises(GraphValidationError, match="superseded_date"):
        engine({"superseded_date": value})


def test_excluded_source_does_not_add_corroboration():
    when = date(2025, 1, 1)
    current = {"status": "current", "superseded_date": None}
    baseline = engine(current).evaluate_fact("fact:test", as_of=when)
    expanded = engine(current, {}).evaluate_fact("fact:test", as_of=when)
    assert baseline.evidence[0].materiality_score == expanded.evidence[0].materiality_score
    assert not expanded.evidence[1].applicable


@pytest.mark.parametrize(
    "when,admitted", [("2024-12-31", True), ("2025-01-01", False), ("2025-01-02", False)]
)
def test_adapter_carries_boundary_and_preserves_citations(when, admitted):
    text = "Approval required"
    passage = Evidence(
        evidence_id="e",
        source_id="s",
        locator="paragraph:1",
        text=text,
        source_type="policy",
        extraction_method="synthetic",
    )
    source = Source(
        source_id="s",
        title="Policy",
        original_file_path="policy.md",
        source_type="policy",
        checksum="a" * 64,
        ingestion_status="ingested",
        lifecycle_status="superseded",
        approval_status="Approved",
        effective_start_date=date(2024, 1, 1),
        superseded_date=date(2025, 1, 1),
    )
    interpretation = EvidenceInterpretation(
        claim_text=text,
        facet=text,
        stance="support",
        mode="formal",
        rationale="Supplied judgement",
        citations=(
            InterpretationCitation(
                evidence_id="e",
                source_id="s",
                locator=passage.locator,
                quotation=text,
                start=0,
                end=len(text),
            ),
        ),
    )
    item = PreparedAttestation(
        interpretation=interpretation,
        source=source,
        origin_id="s",
        source_class="approved_policy",
        approval_key="approved",
        scope_matches=True,
        temporal_matches=True,
        authority_verified=True,
        directness=1.0,
        specificity=1.0,
        completeness=1.0,
        judgement_basis="Synthetic",
        origin_basis="Synthetic",
    )
    result = assess_prepared_facet(
        claim_text=text,
        facet=text,
        as_of=date.fromisoformat(when),
        config=GraphCredibilityConfig.load(CONFIG_PATH),
        prepared=[item],
        evidence=[passage],
    )
    assert (result.inputs[0].edge_id is not None) is admitted
    assert result.inputs[0].source.superseded_date == source.superseded_date
    assert result.inputs[0].source.effective_end_date is None
    assert result.inputs[0].interpretation.citations == interpretation.citations
    if admitted:
        assert result.assessment.overall_outcome == "Supported"
        assert result.assessment.evidence[0].materiality_score == pytest.approx(0.9375)
    else:
        assert result.inputs[0].reasons
        assert result.assessment.overall_outcome == "Insufficient evidence"
