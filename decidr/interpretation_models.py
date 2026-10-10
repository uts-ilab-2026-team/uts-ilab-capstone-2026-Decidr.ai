"""Explicit claim interpretations with exact, verifiable corpus citations."""

from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from decidr.models import Evidence


class InterpretationCitation(BaseModel):
    """A verbatim span from one stored evidence passage."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    evidence_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    locator: str = Field(min_length=1)
    quotation: str = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(ge=1)

    @field_validator("evidence_id", "source_id", "locator", "quotation")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Must not be blank")
        return value

    @model_validator(mode="after")
    def validate_span(self) -> "InterpretationCitation":
        if self.end <= self.start:
            raise ValueError("end must be greater than start")
        if self.end - self.start != len(self.quotation):
            raise ValueError("Span length must equal quotation length")
        return self


class EvidenceInterpretation(BaseModel):
    """A supplied judgement about one facet of a claim."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    claim_text: str = Field(min_length=1)
    facet: str = Field(min_length=1)
    stance: Literal["support", "contradict", "qualify", "context", "unresolved"]
    mode: Literal["formal", "observed", "unresolved"]
    rationale: str = Field(min_length=1)
    citations: tuple[InterpretationCitation, ...] = Field(min_length=1)

    @field_validator("claim_text", "facet", "rationale")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Must not be blank")
        return value


def validate_interpretation(
    interpretation: EvidenceInterpretation,
    evidence: Iterable[Evidence],
    *,
    claim_text: str,
) -> EvidenceInterpretation:
    """Validate claim binding and exact quotation offsets against stored evidence."""
    if interpretation.claim_text != claim_text:
        raise ValueError("Interpretation does not match the submitted claim")

    by_id: dict[str, Evidence] = {}
    for passage in evidence:
        if passage.evidence_id in by_id:
            raise ValueError(f"Duplicate evidence ID: {passage.evidence_id}")
        by_id[passage.evidence_id] = passage

    for citation in interpretation.citations:
        passage = by_id.get(citation.evidence_id)
        if passage is None:
            raise ValueError(f"Unknown evidence ID: {citation.evidence_id}")
        if citation.source_id != passage.source_id:
            raise ValueError("Citation source does not match stored evidence")
        if citation.locator != passage.locator:
            raise ValueError("Citation locator does not match stored evidence")
        if citation.end > len(passage.text):
            raise ValueError("Citation span exceeds stored passage")
        if passage.text[citation.start : citation.end] != citation.quotation:
            raise ValueError("Quotation does not match the original passage")
    return interpretation
