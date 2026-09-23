"""Shared component contracts and cross-approach assessment result schema."""

from datetime import UTC, datetime
from typing import Any

from pydantic import Field

from decidr.models import ClaimOutcome, ConfidenceLevel, StrictModel


class StructuredClaimResult(StrictModel):
    claim_text: str | None = None
    subject: str
    predicate: str
    target_object: str
    process: str | None = None
    scope: str | None = None
    conditions: list[str] = Field(default_factory=list)
    applicable_period: dict[str, str | None] = Field(default_factory=dict)
    evidence_target: str
    proposition_polarity: str = "positive"


class AssessmentResult(StrictModel):
    approach_id: str
    query: str
    structured_claim: StructuredClaimResult
    outcome: ClaimOutcome
    confidence: ConfidenceLevel
    supporting_evidence: list[dict[str, Any]] = Field(default_factory=list)
    contradicting_evidence: list[dict[str, Any]] = Field(default_factory=list)
    qualifying_evidence: list[dict[str, Any]] = Field(default_factory=list)
    contextual_evidence: list[dict[str, Any]] = Field(default_factory=list)
    not_applicable_evidence: list[dict[str, Any]] = Field(default_factory=list)
    dependent_evidence_groups: list[dict[str, Any]] = Field(default_factory=list)
    evidence_gaps: list[str] = Field(default_factory=list)
    rules_applied: list[dict[str, Any]] = Field(default_factory=list)
    explanation: str
    citations: list[dict[str, Any]] = Field(default_factory=list)
    runtime_metadata: dict[str, Any] = Field(default_factory=dict)
    original_question: str | None = None
    confirmed_atomic_claim: str | None = None
    interpretation_method: str = "not_recorded"
    ambiguities: list[str] = Field(default_factory=list)
    safe_employee_guidance: str = ""
    policy_practice_divergence: list[str] = Field(default_factory=list)
    temporal_applicability_notes: list[str] = Field(default_factory=list)
    dependency_duplication_notes: list[str] = Field(default_factory=list)
    recommended_organisational_action: str = ""
    query_conditions: dict[str, Any] = Field(default_factory=dict)
    threshold_reasoning: dict[str, Any] = Field(default_factory=dict)
    direct_answer_condition: str = "declarative"
    matched_candidate_claim: dict[str, Any] | None = None
    divergence_evidence: list[dict[str, Any]] = Field(default_factory=list)
    responsible_role_basis: str | None = None
    responsible_role: str | None = None
    retrieval_component_status: dict[str, str] = Field(default_factory=dict)
    assessment_provenance: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
