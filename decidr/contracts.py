"""Shared component contracts and cross-approach assessment result schema."""

from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import Field

from decidr.models import AtomicClaim, ClaimOutcome, ConfidenceLevel, StrictModel


class ClaimParser(Protocol):
    def parse(self, query: str) -> list[AtomicClaim]: ...


class Retriever(Protocol):
    def retrieve(self, claim: AtomicClaim, limit: int = 20) -> list[Any]: ...


class Reranker(Protocol):
    def rerank(self, claim: AtomicClaim, results: list[Any]) -> list[Any]: ...


class GraphExpander(Protocol):
    def expand(self, claim: AtomicClaim, results: list[Any], depth: int = 1) -> list[Any]: ...


class RelationshipSuggester(Protocol):
    def suggest(self, claim: AtomicClaim, evidence: list[Any]) -> list[Any]: ...


class OutcomeReasoner(Protocol):
    def reason(self, claim: AtomicClaim, evidence: list[Any]) -> Any: ...


class ExplanationGenerator(Protocol):
    def generate(self, claim: AtomicClaim, result: Any) -> str: ...


class CitationValidator(Protocol):
    def validate(self, explanation: str, package: list[Any], outcome: ClaimOutcome) -> Any: ...


class StructuredClaimResult(StrictModel):
    subject: str
    predicate: str
    target_object: str
    scope: str | None = None
    conditions: list[str] = Field(default_factory=list)
    applicable_period: dict[str, str | None] = Field(default_factory=dict)
    evidence_target: str


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
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
