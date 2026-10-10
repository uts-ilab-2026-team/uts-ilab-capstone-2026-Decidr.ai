"""Response checks for qualifications, provenance and detached JSON data."""

from dataclasses import asdict, replace
from datetime import date
import json
from pathlib import Path

from framework.config import GraphCredibilityConfig

from decidr.assessment_adapter import PreparedAttestation, assess_prepared_facet
from decidr.assessment_response import serialize_facet_assessment
from decidr.interpretation_models import EvidenceInterpretation, InterpretationCitation
from decidr.retrieval_models import Evidence, Source


def example_result():
    claim = "Written approval is required."
    passage = Evidence(
        evidence_id="example-evidence",
        source_id="example-source",
        locator="paragraph:1",
        text=claim,
        source_type="policy",
        extraction_method="test",
    )
    source = Source(
        source_id=passage.source_id,
        title="Example policy",
        original_file_path="example.md",
        source_type="policy",
        checksum="a" * 64,
        ingestion_status="ingested",
        lifecycle_status="current",
        approval_status="Approved",
        effective_start_date=date(2025, 1, 1),
    )
    interpretation = EvidenceInterpretation(
        claim_text=claim,
        facet=claim,
        stance="support",
        mode="formal",
        rationale="Synthetic supplied interpretation for response testing.",
        citations=(
            InterpretationCitation(
                evidence_id=passage.evidence_id,
                source_id=source.source_id,
                locator=passage.locator,
                quotation=claim,
                start=0,
                end=len(claim),
            ),
        ),
    )
    prepared = PreparedAttestation(
        interpretation=interpretation,
        source=source,
        origin_id=source.source_id,
        source_class="approved_policy",
        approval_key="approved",
        scope_matches=True,
        temporal_matches=True,
        authority_verified=True,
        directness=1.0,
        specificity=1.0,
        completeness=1.0,
        judgement_basis="Synthetic assumptions; not human adjudication.",
        origin_basis="One synthetic source.",
    )
    qualification = replace(
        prepared,
        interpretation=interpretation.model_copy(
            update={
                "stance": "qualify",
                "rationale": "Synthetic non-decisive input for retention testing.",
            }
        ),
        scope_matches=None,
    )
    config_path = Path(__file__).resolve().parents[1] / "framework/data/credibility.json"
    config = GraphCredibilityConfig(**json.loads(config_path.read_text()))
    return assess_prepared_facet(
        claim_text=claim,
        facet=claim,
        as_of=date(2026, 6, 17),
        prepared=[prepared, qualification],
        evidence=[passage],
        config=config,
    )


def test_response_retains_core_trace_and_non_decisive_citations():
    result = example_result()
    payload = serialize_facet_assessment(result)
    restored = json.loads(json.dumps(payload, allow_nan=False))

    assert restored == payload
    assert payload["claim_text"] == result.claim_text
    assert payload["facet"] == result.facet
    assert payload["as_of"] == "2026-06-17"
    assert payload["assessment_scope"] == "facet"
    assert payload["interpretation_basis"] == "supplied_judgements"
    assert payload["assessment"] == json.loads(json.dumps(asdict(result.assessment)))
    assert len(payload["inputs"]) == 2
    for actual, original in zip(payload["inputs"], result.inputs, strict=True):
        assert actual["input_id"] == original.input_id
        assert actual["interpretation"] == original.interpretation.model_dump(mode="json")
        assert actual["source"] == original.source.model_dump(mode="json")
        assert actual["supplied_judgements"] == original.supplied_judgements
        assert actual["reasons"] == list(original.reasons)

    assert payload["inputs"][0]["admitted_to_framework"] is True
    qualifier = payload["inputs"][1]
    assert qualifier["interpretation"]["stance"] == "qualify"
    assert qualifier["admitted_to_framework"] is False
    assert qualifier["edge_id"] is None
    assert qualifier["reasons"]
    assert payload["limitations"] == list(result.limitations)


def test_response_mutation_does_not_change_adapter_result():
    result = example_result()
    payload = serialize_facet_assessment(result)
    payload["inputs"][0]["source"]["title"] = "Changed"
    payload["inputs"][0]["interpretation"]["citations"][0]["quotation"] = "Changed"
    payload["inputs"][0]["supplied_judgements"]["judgement_basis"] = "Changed"
    payload["assessment"]["rules_applied"].clear()
    payload["limitations"].clear()

    fresh = serialize_facet_assessment(result)
    assert fresh["inputs"][0]["source"]["title"] == "Example policy"
    assert fresh["inputs"][0]["interpretation"]["citations"][0]["quotation"] == result.claim_text
    assert fresh["inputs"][0]["supplied_judgements"]["judgement_basis"] != "Changed"
    assert fresh["assessment"]["rules_applied"]
    assert fresh["limitations"]


def test_admission_is_not_misrepresented_as_materiality():
    result = example_result()
    edge = result.assessment.evidence[0]
    assessment = replace(
        result.assessment,
        evidence=(replace(edge, material=False, materiality_score=0.1),),
    )
    # Isolated serialization fixture, not a new framework assessment.
    payload = serialize_facet_assessment(replace(result, assessment=assessment))

    assert payload["inputs"][0]["admitted_to_framework"] is True
    assert payload["assessment"]["evidence"][0]["material"] is False
    assert payload["assessment"]["evidence"][0]["materiality_score"] == 0.1
