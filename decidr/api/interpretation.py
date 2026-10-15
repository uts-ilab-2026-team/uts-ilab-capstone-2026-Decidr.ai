"""Shared request model for claim assessment.

Formerly also hosted ``POST /api/corpus/interpret`` (the regex-reader proposal endpoint), retired
with the legacy scorers. Only the request model remains — reused by the graph-engine claim runner
(``automatic_assessment.SaveAutomaticRequest``).
"""

from datetime import date
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

from decidr.infra.targets import AssessmentTarget


class InterpretationProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    claim: str = Field(min_length=1, max_length=10000)
    facet: str | None = Field(default=None, min_length=1, max_length=10000)
    assessment_target: AssessmentTarget = "unspecified"
    as_of: date
    ranked_group_limit: int = Field(default=8, ge=1, le=50, strict=True)
    max_inputs: int = Field(default=12, ge=1, le=50, strict=True)

    @field_validator("claim")
    @classmethod
    def reject_blank_claim(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Claim must not be blank")
        return value

    @field_validator("facet")
    @classmethod
    def reject_blank_facet(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Facet must not be blank")
        return value

    @field_validator("as_of", mode="before")
    @classmethod
    def explicit_iso_date(cls, value):
        if type(value) is date:
            return value
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("as_of must be an explicit YYYY-MM-DD date")
        return date.fromisoformat(value)
