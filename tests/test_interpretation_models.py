"""Provenance and claim-binding checks for interpretation records."""

import pytest
from pydantic import ValidationError

from decidr.interpretation_models import (
    EvidenceInterpretation,
    InterpretationCitation,
    validate_interpretation,
)
from decidr.retrieval_models import Evidence


CLAIM = "Every release requires written approval."
QUOTE = "Written approval is required."


@pytest.fixture
def passage():
    return Evidence(
        evidence_id="ev-example",
        source_id="source-example",
        locator="section:release",
        text=f"{QUOTE} Urgent releases sometimes proceed first.",
        source_type="interview",
        extraction_method="markdown_paragraph",
    )


def make_interpretation(passage, **changes):
    payload = {
        "claim_text": CLAIM,
        "facet": "Written approval requirement",
        "stance": "support",
        "mode": "formal",
        "rationale": "The quoted sentence states the requirement.",
        "citations": (
            InterpretationCitation(
                evidence_id=passage.evidence_id,
                source_id=passage.source_id,
                locator=passage.locator,
                quotation=QUOTE,
                start=0,
                end=len(QUOTE),
            ),
        ),
    }
    payload.update(changes)
    return EvidenceInterpretation(**payload)


def test_valid_interpretation_preserves_original_evidence(passage):
    before = passage.model_dump()
    item = make_interpretation(passage)
    result = validate_interpretation(item, [passage], claim_text=CLAIM)
    assert result == item
    assert result.citations[0].quotation == QUOTE
    assert passage.model_dump() == before


def test_related_claim_cannot_reuse_interpretation(passage):
    item = make_interpretation(passage)
    with pytest.raises(ValueError, match="submitted claim"):
        validate_interpretation(
            item,
            [passage],
            claim_text="Releases can proceed without written approval.",
        )


@pytest.mark.parametrize(
    "field,value,error",
    [
        ("evidence_id", "missing", "Unknown evidence"),
        ("source_id", "other-source", "source does not match"),
        ("locator", "other-location", "locator does not match"),
        ("quotation", "X" * len(QUOTE), "Quotation does not match"),
    ],
)
def test_rejects_invented_citation_details(passage, field, value, error):
    original = make_interpretation(passage)
    citation = original.citations[0].model_dump()
    citation[field] = value
    item = make_interpretation(
        passage, citations=(InterpretationCitation(**citation),)
    )
    with pytest.raises(ValueError, match=error):
        validate_interpretation(item, [passage], claim_text=CLAIM)


def test_rejects_out_of_bounds_span(passage):
    citation = InterpretationCitation(
        evidence_id=passage.evidence_id,
        source_id=passage.source_id,
        locator=passage.locator,
        quotation=QUOTE,
        start=len(passage.text),
        end=len(passage.text) + len(QUOTE),
    )
    item = make_interpretation(passage, citations=(citation,))
    with pytest.raises(ValueError, match="exceeds stored passage"):
        validate_interpretation(item, [passage], claim_text=CLAIM)


def test_unassessed_is_not_silently_qualification(passage):
    payload = make_interpretation(passage).model_dump()
    del payload["stance"]
    with pytest.raises(ValidationError):
        EvidenceInterpretation.model_validate(payload)
    with pytest.raises(ValidationError):
        make_interpretation(passage, stance=None)
    assert make_interpretation(passage, stance="unresolved").stance == "unresolved"


def test_requires_citations_and_explanation(passage):
    with pytest.raises(ValidationError):
        make_interpretation(passage, citations=())
    with pytest.raises(ValidationError):
        make_interpretation(passage, rationale="   ")


def test_retrieval_score_is_not_an_interpretation_field(passage):
    with pytest.raises(ValidationError):
        make_interpretation(passage, retrieval_score=0.99)


def test_duplicate_evidence_ids_are_rejected(passage):
    with pytest.raises(ValueError, match="Duplicate evidence"):
        validate_interpretation(
            make_interpretation(passage),
            [passage, passage.model_copy(deep=True)],
            claim_text=CLAIM,
        )


def test_same_passage_can_describe_rule_and_practice(passage):
    formal = make_interpretation(passage)
    quotation = "Urgent releases sometimes proceed first."
    start = passage.text.index(quotation)
    observed = make_interpretation(
        passage,
        facet="Whether approval always precedes release",
        stance="qualify",
        mode="observed",
        rationale="The speaker describes urgent releases preceding approval.",
        citations=(
            InterpretationCitation(
                evidence_id=passage.evidence_id,
                source_id=passage.source_id,
                locator=passage.locator,
                quotation=quotation,
                start=start,
                end=start + len(quotation),
            ),
        ),
    )
    for item in (formal, observed):
        validate_interpretation(item, [passage], claim_text=CLAIM)
    assert formal.mode != observed.mode
    assert formal.citations[0].quotation != observed.citations[0].quotation
