"""Validated source and passage records for corpus retrieval.

Adapted from decidr/models.py at retrieval commit 90ffff9.
Graph nodes and assessment records remain in framework.models.
"""

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    """Base model that rejects misspelled or unsupported fields."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Source(StrictModel):
    source_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    original_file_path: str = Field(min_length=1)
    source_type: str = Field(min_length=1)
    organisational_function: str | None = None
    responsible_person_or_role: str | None = None
    author_or_system: str | None = None
    creation_date: date | None = None
    last_updated_date: date | None = None
    superseded_date: date | None = None
    effective_start_date: date | None = None
    effective_end_date: date | None = None
    version: str | None = None
    approval_status: str | None = None
    formality_level: str | None = None
    lifecycle_status: str = "unknown"
    predecessor_source_id: str | None = None
    successor_source_id: str | None = None
    derived_from_source_id: str | None = None
    duplicate_group: str | None = None
    ingestion_status: str = "registered"
    exclusion_reason: str | None = None
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    metadata_notes: str | None = None
    metadata_provenance: dict[str, str] = Field(default_factory=dict)
    metadata_version: str | None = None
    header_evidence: list[dict[str, Any]] = Field(default_factory=list)
    approval_clauses: list[dict[str, Any]] = Field(default_factory=list)
    metadata_conflicts: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_dates(self) -> "Source":
        if (
            self.effective_start_date
            and self.effective_end_date
            and self.effective_start_date > self.effective_end_date
        ):
            raise ValueError("effective_start_date must not follow effective_end_date")
        if self.exclusion_reason and self.ingestion_status != "excluded":
            raise ValueError("exclusion_reason requires ingestion_status='excluded'")
        return self


class Evidence(StrictModel):
    evidence_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    locator: str = Field(min_length=1)
    text: str = Field(min_length=1)
    source_type: str = Field(min_length=1)
    page: int | None = Field(default=None, ge=1)
    section: str | None = None
    heading: str | None = None
    paragraph: int | None = Field(default=None, ge=1)
    row_identifier: str | None = None
    process: str | None = None
    actor: str | None = None
    role: str | None = None
    system: str | None = None
    relevant_start_date: date | None = None
    relevant_end_date: date | None = None
    version: str | None = None
    extraction_method: str = Field(min_length=1)
    parent_evidence_id: str | None = None
    provenance_links: list[str] = Field(default_factory=list)
    structured_metadata: dict[str, Any] = Field(default_factory=dict)
