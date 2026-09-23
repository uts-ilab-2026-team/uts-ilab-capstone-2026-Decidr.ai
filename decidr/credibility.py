"""Transparent credibility-framework rules for reviewed evidence.

The framework evaluates whether one evidence item is useful for a claim.  It does
not estimate the probability that the claim is true.  Claim outcomes and
confidence remain separate and are delegated to the existing reasoning engine.
"""

from pathlib import Path

from decidr.models import (
    ClaimEvidenceLink,
    CredibilityAssessment,
    EvidenceRelationship,
    EvidenceTarget,
)
from decidr.reasoning import (
    ReasoningConfig,
    ReasoningResult,
    ReviewedEvidence,
    assess_claim,
    credibility_value,
    load_reasoning_config,
)

CREDIBILITY_DIMENSIONS = (
    "relevance",
    "institutional_authority",
    "directness",
    "temporal_validity",
    "independence",
    "completeness",
    "organisational_applicability",
)

CREDIBILITY_QUESTIONS = {
    "relevance": "How directly does the item address the atomic claim?",
    "institutional_authority": ("Does the issuer have the required remit and approval status?"),
    "directness": "Is this a primary record or direct statement rather than a remote summary?",
    "temporal_validity": "Do the source version and effective period align with the claim?",
    "independence": "Does the item provide a genuinely separate evidential origin?",
    "completeness": "Does the item cover the material elements needed for the judgement?",
    "organisational_applicability": (
        "Does the item apply to the named organisation, process and conditions?"
    ),
}


class CredibilityFrameworkError(ValueError):
    """Raised when framework inputs are incomplete or internally inconsistent."""


class CredibilityFramework:
    """Apply the agreed applicability gate and materiality calculation."""

    def __init__(self, config: ReasoningConfig | None = None) -> None:
        self.config = config or ReasoningConfig()
        self._validate_config()

    @classmethod
    def from_json(cls, path: Path) -> "CredibilityFramework":
        """Load a version-controlled framework configuration from JSON."""
        return cls(load_reasoning_config(path))

    def _validate_config(self) -> None:
        keys = set(self.config.dimension_weights)
        expected = set(CREDIBILITY_DIMENSIONS)
        if keys != expected:
            missing = sorted(expected - keys)
            extra = sorted(keys - expected)
            raise CredibilityFrameworkError(
                f"Credibility weights must cover exactly seven dimensions; "
                f"missing={missing}, extra={extra}"
            )
        if not 0 <= self.config.materiality_threshold <= 1:
            raise CredibilityFrameworkError("Materiality threshold must be between 0 and 1")
        if any(weight < 0 for weight in self.config.dimension_weights.values()):
            raise CredibilityFrameworkError("Credibility dimension weights cannot be negative")
        if sum(self.config.dimension_weights.values()) <= 0:
            raise CredibilityFrameworkError("Credibility dimension weights must total above zero")

    def evaluate_evidence(
        self,
        link: ClaimEvidenceLink,
        assessment: CredibilityAssessment,
    ) -> dict[str, object]:
        """Return a plain, serialisable decision trace for one evidence item.

        Failed applicability checks stop the item before credibility scoring.  A
        passing item receives a transparent weighted-average materiality score.
        The result deliberately contains no claim verdict or claim confidence.
        """
        if link.link_id != assessment.link_id:
            raise CredibilityFrameworkError(
                "The credibility assessment must refer to the reviewed claim-evidence link"
            )

        applicability = {
            "target_match": link.target_match,
            "scope_match": link.scope_match,
            "condition_match": link.condition_match,
            "temporal_match": link.temporal_match,
        }
        failed = [name for name, passed in applicability.items() if not passed]
        if link.relationship == EvidenceRelationship.NOT_APPLICABLE and not failed:
            raise CredibilityFrameworkError(
                "A not-applicable relationship requires at least one failed applicability check"
            )
        if failed or link.relationship == EvidenceRelationship.NOT_APPLICABLE:
            return {
                "link_id": link.link_id,
                "applicable": False,
                "failed_applicability_checks": failed,
                "materiality_score": None,
                "materiality_threshold": self.config.materiality_threshold,
                "material": False,
                "dimension_breakdown": [],
                "rule_id": "CF1_APPLICABILITY_GATE",
                "explanation": (
                    "Evidence was excluded before credibility scoring because the "
                    "applicability gate did not pass."
                ),
            }

        values = {
            dimension: float(getattr(assessment, dimension))
            for dimension in CREDIBILITY_DIMENSIONS
        }
        total_weight = sum(self.config.dimension_weights.values())
        breakdown = [
            {
                "dimension": dimension,
                "question": CREDIBILITY_QUESTIONS[dimension],
                "value": values[dimension],
                "weight": self.config.dimension_weights[dimension],
                "weighted_contribution": (
                    values[dimension] * self.config.dimension_weights[dimension] / total_weight
                ),
            }
            for dimension in CREDIBILITY_DIMENSIONS
        ]
        score = credibility_value(assessment, self.config)
        material = score >= self.config.materiality_threshold
        return {
            "link_id": link.link_id,
            "applicable": True,
            "failed_applicability_checks": [],
            "materiality_score": score,
            "materiality_threshold": self.config.materiality_threshold,
            "material": material,
            "dimension_breakdown": breakdown,
            "rule_id": "CF2_MATERIALITY_THRESHOLD",
            "explanation": (
                "The applicable evidence item meets the materiality threshold."
                if material
                else (
                    "The applicable evidence item remains in the audit record but is not decisive."
                )
            ),
        }

    def assess_claim(
        self,
        reviewed: list[ReviewedEvidence],
        *,
        expected_evidence_gaps: list[str] | None = None,
        evidence_target: EvidenceTarget | None = None,
    ) -> ReasoningResult:
        """Apply four-outcome reasoning while keeping confidence separate."""
        return assess_claim(
            reviewed,
            expected_evidence_gaps=expected_evidence_gaps,
            config=self.config,
            evidence_target=evidence_target,
        )
