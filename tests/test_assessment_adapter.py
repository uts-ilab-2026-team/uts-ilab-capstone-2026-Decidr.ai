"""Synthetic integration checks; not interpretation-accuracy measurements."""

from dataclasses import replace
from datetime import date

import pytest

from decidr.assessment_adapter import PreparedAttestation, assess_prepared_facet
from decidr.interpretation_models import EvidenceInterpretation, InterpretationCitation
from decidr.retrieval_models import Evidence, Source
from framework.config import GraphCredibilityConfig
from framework.constants import CREDIBILITY_DIMENSIONS

DAY = date(2026, 7, 31)
CLAIM = "Release requires approval before deployment."
FACET = "Approval before deployment"


@pytest.fixture
def config():
    return GraphCredibilityConfig(
        config_version="synthetic-adapter-test",
        materiality_threshold=0.2,
        conflict_ratio=0.5,
        dimension_weights={name: 1.0 for name in CREDIBILITY_DIMENSIONS},
        source_class_weights={"policy": 1.0},
        approval_weights={"approved": 1.0},
        lifecycle_multipliers={"current": 1.0, "draft": 0.2},
        undated_weight=0.5, stale_weight=0.5, recency_years=5,
    )


def make_item(name="a", stance="support", origin=None):
    text = "Approval is required before deployment."
    passage = Evidence(
        evidence_id=f"ev:{name}", source_id=f"source:{name}",
        locator="paragraph:1", text=text, source_type="policy",
        extraction_method="synthetic",
    )
    source = Source(
        source_id=passage.source_id, title=f"Policy {name}",
        original_file_path=f"{name}.md", source_type="policy",
        checksum="a" * 64, ingestion_status="ingested",
        lifecycle_status="current", approval_status="Approved",
        effective_start_date=date(2026, 1, 1),
    )
    citation = InterpretationCitation(
        evidence_id=passage.evidence_id, source_id=passage.source_id,
        locator=passage.locator, quotation=text, start=0, end=len(text),
    )
    interpretation = EvidenceInterpretation(
        claim_text=CLAIM, facet=FACET, stance=stance, mode="formal",
        rationale="Synthetic supplied judgement.", citations=(citation,),
    )
    item = PreparedAttestation(
        interpretation=interpretation, source=source,
        origin_id=origin or f"origin:{name}", source_class="policy",
        approval_key="approved", scope_matches=True, temporal_matches=True,
        authority_verified=True, directness=1.0, specificity=1.0,
        completeness=1.0, judgement_basis="Synthetic fixture assumptions.",
        origin_basis="Synthetic origin declaration.",
    )
    return item, passage


def run(config, pairs):
    return assess_prepared_facet(
        claim_text=CLAIM, facet=FACET, as_of=DAY, config=config,
        prepared=[item for item, _ in pairs],
        evidence=[passage for _, passage in pairs],
    )


@pytest.mark.parametrize("stances,expected", [
    ([], "Insufficient evidence"),
    (["support"], "Supported"),
    (["contradict"], "Contradicted"),
    (["support", "contradict"], "Contested"),
])
def test_all_framework_outcomes(config, stances, expected):
    pairs = [make_item(str(i), stance) for i, stance in enumerate(stances)]
    result = run(config, pairs)
    assert result.assessment.overall_outcome == expected
    assert result.claim_text == CLAIM
    assert result.assessment.statement == FACET


@pytest.mark.parametrize("stance", ["context", "qualify", "unresolved"])
def test_non_decisive_inputs_remain_visible_without_votes(config, stance):
    result = run(config, [make_item(stance=stance)])
    assert result.assessment.evidence == ()
    assert result.inputs[0].edge_id is None
    assert result.inputs[0].interpretation.stance == stance
    assert result.inputs[0].reasons


@pytest.mark.parametrize("field", [
    "scope_matches", "temporal_matches", "authority_verified",
])
@pytest.mark.parametrize("value", [None, False])
def test_uncertain_or_failed_gate_does_not_score(config, field, value):
    item, passage = make_item()
    result = run(config, [(replace(item, **{field: value}), passage)])
    assert result.assessment.evidence == ()
    assert any(field in reason for reason in result.inputs[0].reasons)


def test_wrong_claim_or_facet_is_rejected(config):
    item, passage = make_item()
    for field in ("claim_text", "facet"):
        changed = item.interpretation.model_copy(update={field: "Different"})
        with pytest.raises(ValueError):
            run(config, [(replace(item, interpretation=changed), passage)])


def test_changed_passage_is_rejected(config):
    item, passage = make_item()
    changed = passage.model_copy(update={"text": "Different stored text."})
    with pytest.raises(ValueError):
        run(config, [(item, changed)])


@pytest.mark.parametrize("updates", [
    {"effective_start_date": date(2026, 8, 1)},
    {"effective_end_date": date(2026, 7, 30)},
    {"superseded_date": DAY},
    {"superseded_date": date(2026, 7, 30)},
    {"lifecycle_status": "draft"},
])
def test_source_constraints_override_supplied_eligibility(config, updates):
    item, passage = make_item()
    item = replace(item, source=item.source.model_copy(update=updates))
    result = run(config, [(item, passage)])
    assert result.assessment.evidence == ()
    assert result.inputs[0].reasons


def test_repeated_origin_preserves_contested_outcome(config):
    pairs = [
        make_item("a", "support", "shared"),
        make_item("b", "contradict"),
    ]
    baseline = run(config, pairs)
    repeated = run(config, pairs + [
        make_item("c", "support", "shared"),
        make_item("d", "support", "shared"),
    ])
    assert baseline.assessment.overall_outcome == "Contested"
    assert repeated.assessment.overall_outcome == "Contested"
    assert len(repeated.inputs) == 4


def test_citations_and_inputs_are_preserved(config):
    item, passage = make_item()
    before = item.source.model_dump()
    result = run(config, [(item, passage)])
    assert result.inputs[0].interpretation == item.interpretation
    assert result.inputs[0].source == item.source
    assert result.inputs[0].edge_id == result.assessment.evidence[0].edge_id
    assert result.assessment.evidence[0].attests_value == passage.text
    assert item.source.model_dump() == before


def test_multiple_citations_do_not_create_multiple_votes(config):
    item, first = make_item()
    second = first.model_copy(update={"evidence_id": "ev:second", "locator": "paragraph:2"})
    citation = item.interpretation.citations[0].model_copy(update={
        "evidence_id": second.evidence_id, "locator": second.locator,
    })
    interpretation = item.interpretation.model_copy(update={
        "citations": (*item.interpretation.citations, citation),
    })
    result = assess_prepared_facet(
        claim_text=CLAIM, facet=FACET, as_of=DAY, config=config,
        prepared=[replace(item, interpretation=interpretation)],
        evidence=[first, second],
    )
    assert len(result.assessment.evidence) == 1
    assert len(result.inputs[0].interpretation.citations) == 2
