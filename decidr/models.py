"""Validated domain models for claims, sources, evidence, and assessments."""

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    """Base model that rejects misspelled or unsupported fields."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EvidenceRelationship(StrEnum):
    SUPPORT = "support"
    CONTRADICT = "contradict"
    QUALIFY = "qualify"
    CONTEXTUAL = "contextual"
    NOT_APPLICABLE = "not_applicable"


class ClaimOutcome(StrEnum):
    SUPPORTED = "Supported"
    CONTRADICTED = "Contradicted"
    CONTESTED = "Contested"
    INSUFFICIENT = "Insufficient evidence"


class ConfidenceLevel(StrEnum):
    HIGHER = "Higher confidence"
    MODERATE = "Moderate confidence"
    LOWER = "Lower confidence"
    NOT_CALCULATED = "Not calculated"


class EvidenceMode(StrEnum):
    FORMAL_RULE = "formal_rule"
    OBSERVED_PRACTICE = "observed_practice"
    OTHER = "other"


class EvidenceTarget(StrEnum):
    PRESCRIBED_RULE = "prescribed_rule"
    ROUTINE_PRACTICE = "routine_practice"
    SPECIFIC_EVENT = "specific_event"
    SYSTEM_RECORD = "system_record"


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


class AtomicClaim(StrictModel):
    claim_id: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    predicate: str = Field(min_length=1)
    object: str = Field(min_length=1)
    process: str | None = None
    scope: str | None = None
    conditions: list[str] = Field(default_factory=list)
    applicable_start_date: date | None = None
    applicable_end_date: date | None = None
    claim_type: str = Field(min_length=1)
    evidence_target: EvidenceTarget | None = None
    claim_text: str = Field(min_length=1)
    atomicity_status: str = "not_checked"
    ambiguity_notes: str | None = None
    evaluation_split: str = Field(default="development", pattern="^(development|held_out)$")
    inclusion_status: str = Field(default="included", pattern="^(included|excluded)$")
    exclusion_reason: str | None = None
    original_claim_text: str | None = None
    parent_claim_id: str | None = None
    portfolio_status: str = Field(
        default="draft",
        pattern="^(draft|candidate_revised_awaiting_final_human_approval|approved_and_frozen|versioned_amendment)$",
    )
    portfolio_version: str | None = None

    @model_validator(mode="after")
    def validate_claim(self) -> "AtomicClaim":
        if (
            self.applicable_start_date
            and self.applicable_end_date
            and self.applicable_start_date > self.applicable_end_date
        ):
            raise ValueError("applicable_start_date must not follow applicable_end_date")
        if self.inclusion_status == "excluded" and not self.exclusion_reason:
            raise ValueError("excluded claims require an exclusion_reason")
        if self.portfolio_status == "approved_and_frozen" and not self.portfolio_version:
            raise ValueError("frozen claims require a portfolio_version")
        return self


class ClaimEvidenceLink(StrictModel):
    link_id: str = Field(min_length=1)
    claim_id: str = Field(min_length=1)
    evidence_id: str = Field(min_length=1)
    relationship: EvidenceRelationship
    applicability_reason: str = Field(min_length=1)
    target_match: bool
    scope_match: bool
    condition_match: bool
    temporal_match: bool
    relationship_confidence: str | None = None
    reviewer: str = Field(min_length=1)
    method: str = Field(default="human_review", min_length=1)
    review_status: str = "draft"
    notes: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    modified_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_applicability(self) -> "ClaimEvidenceLink":
        applicable = all(
            (self.target_match, self.scope_match, self.condition_match, self.temporal_match)
        )
        if self.relationship == EvidenceRelationship.NOT_APPLICABLE and applicable:
            raise ValueError("not_applicable requires at least one failed applicability dimension")
        return self


class CredibilityAssessment(StrictModel):
    assessment_id: str = Field(min_length=1)
    link_id: str = Field(min_length=1)
    relevance: float = Field(ge=0, le=1)
    institutional_authority: float = Field(ge=0, le=1)
    directness: float = Field(ge=0, le=1)
    temporal_validity: float = Field(ge=0, le=1)
    independence: float = Field(ge=0, le=1)
    completeness: float = Field(ge=0, le=1)
    organisational_applicability: float = Field(ge=0, le=1)
    evidence_mode: EvidenceMode
    limitations: list[str] = Field(default_factory=list)
    dimension_values: dict[str, float | str | bool] = Field(default_factory=dict)
    reviewer_justification: str = Field(min_length=1)


class ClaimAssessment(StrictModel):
    assessment_id: str = Field(min_length=1)
    claim_id: str = Field(min_length=1)
    reviewer: str = Field(min_length=1)
    outcome: ClaimOutcome
    confidence: ConfidenceLevel = ConfidenceLevel.NOT_CALCULATED
    uncertainty_explanation: str = Field(min_length=1)
    explanation: str = Field(min_length=1)
    review_status: str = "draft"
    assessed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Adjudication(StrictModel):
    adjudication_id: str = Field(min_length=1)
    claim_id: str = Field(min_length=1)
    reviewer_a: str = Field(min_length=1)
    reviewer_b: str = Field(min_length=1)
    adjudicator: str = Field(min_length=1)
    preserve_disagreement: bool = False
    final_outcome: ClaimOutcome | None = None
    final_confidence: ConfidenceLevel | None = None
    rationale: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_adjudication(self) -> "Adjudication":
        if self.reviewer_a == self.reviewer_b:
            raise ValueError("Adjudication requires two distinct reviewers")
        if self.preserve_disagreement and self.final_outcome is not None:
            raise ValueError("A preserved disagreement must not assert a final outcome")
        if not self.preserve_disagreement and self.final_outcome is None:
            raise ValueError("Resolved adjudication requires a final outcome")
        return self


class EvaluationError(StrictModel):
    error_id: str = Field(min_length=1)
    claim_id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    component: str = Field(min_length=1)
    description: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)
    reviewer: str = Field(min_length=1)
    resolution_status: str = "open"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
