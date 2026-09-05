"""Synthetic behavioral challenge suite; never reported as research performance."""

from dataclasses import asdict, dataclass

from decidr.models import (
    ClaimOutcome,
    CredibilityAssessment,
    EvidenceMode,
    EvidenceRelationship,
)
from decidr.reasoning import ReasoningConfig, ReviewedEvidence, assess_claim


@dataclass(frozen=True, slots=True)
class ChallengeResult:
    challenge_id: str
    name: str
    passed: bool
    observed: str
    expected_principle: str
    fixture_type: str = "synthetic_behavioral_fixture"


def _evidence(
    identifier: str,
    relationship: EvidenceRelationship,
    *,
    mode: EvidenceMode = EvidenceMode.OTHER,
    duplicate_group: str | None = None,
    lifecycle_status: str = "current",
    target: bool = True,
    scope: bool = True,
    condition: bool = True,
    temporal: bool = True,
    value: float = 0.8,
) -> ReviewedEvidence:
    credibility = CredibilityAssessment(
        assessment_id=f"CA-{identifier}",
        link_id=f"L-{identifier}",
        relevance=value,
        institutional_authority=value,
        directness=value,
        temporal_validity=value,
        independence=value,
        completeness=value,
        organisational_applicability=value,
        evidence_mode=mode,
        reviewer_justification="Synthetic challenge input.",
    )
    return ReviewedEvidence(
        evidence_id=f"E-{identifier}",
        source_id=f"S-{identifier}",
        locator=f"synthetic:{identifier}",
        relationship=relationship,
        target_match=target,
        scope_match=scope,
        condition_match=condition,
        temporal_match=temporal,
        credibility=credibility,
        duplicate_group=duplicate_group,
        lifecycle_status=lifecycle_status,
    )


def run_challenges() -> list[ChallengeResult]:
    """Run the ten required deterministic challenge principles."""
    results: list[ChallengeResult] = []

    duplicate = assess_claim(
        [
            _evidence("dup-1", EvidenceRelationship.SUPPORT, duplicate_group="copy"),
            _evidence("dup-2", EvidenceRelationship.SUPPORT, duplicate_group="copy"),
        ]
    )
    results.append(
        ChallengeResult(
            "CH-01",
            "duplicated copied evidence",
            len(duplicate.applicable) == 1 and duplicate.outcome == ClaimOutcome.SUPPORTED,
            f"{len(duplicate.applicable)} independent; {duplicate.outcome.value}",
            "Duplicates do not increase independent corroboration.",
        )
    )

    before = assess_claim([_evidence("decisive", EvidenceRelationship.SUPPORT)])
    after = assess_claim([])
    results.append(
        ChallengeResult(
            "CH-02",
            "removal of decisive evidence",
            before.outcome == ClaimOutcome.SUPPORTED
            and after.outcome == ClaimOutcome.INSUFFICIENT,
            f"{before.outcome.value} -> {after.outcome.value}",
            "Removing the sole decisive item exposes insufficient evidence.",
        )
    )

    superseded = assess_claim(
        [_evidence("old", EvidenceRelationship.CONTRADICT, lifecycle_status="superseded")]
    )
    results.append(
        ChallengeResult(
            "CH-03",
            "superseded source replacement",
            superseded.outcome == ClaimOutcome.INSUFFICIENT and not superseded.applicable,
            superseded.outcome.value,
            "Superseded evidence does not silently override current evidence.",
        )
    )

    semantic_mismatch = assess_claim(
        [_evidence("similar", EvidenceRelationship.NOT_APPLICABLE, scope=False)]
    )
    results.append(
        ChallengeResult(
            "CH-04",
            "semantically similar but inapplicable passage",
            semantic_mismatch.outcome == ClaimOutcome.INSUFFICIENT,
            semantic_mismatch.outcome.value,
            "Semantic similarity cannot bypass applicability.",
        )
    )

    divergence = assess_claim(
        [
            _evidence("policy", EvidenceRelationship.SUPPORT, mode=EvidenceMode.FORMAL_RULE),
            _evidence(
                "practice", EvidenceRelationship.CONTRADICT, mode=EvidenceMode.OBSERVED_PRACTICE
            ),
        ]
    )
    results.append(
        ChallengeResult(
            "CH-05",
            "policy and observed practice conflict",
            divergence.outcome == ClaimOutcome.CONTESTED
            and divergence.traces[2]["details"]["divergence_visible"] is True,
            divergence.outcome.value,
            "Policy-practice divergence remains visible and contested.",
        )
    )

    missing = assess_claim([], ["Expected operational record absent."])
    results.append(
        ChallengeResult(
            "CH-06",
            "absence of expected operational record",
            missing.outcome == ClaimOutcome.INSUFFICIENT and bool(missing.gaps),
            missing.outcome.value,
            "Missing records create a gap, not automatic contradiction.",
        )
    )

    wrong_role = assess_claim([_evidence("role", EvidenceRelationship.SUPPORT, target=False)])
    results.append(
        ChallengeResult(
            "CH-07",
            "evidence concerning wrong role",
            wrong_role.outcome == ClaimOutcome.INSUFFICIENT,
            wrong_role.outcome.value,
            "Evidence about another role is excluded.",
        )
    )

    outside_period = assess_claim(
        [_evidence("period", EvidenceRelationship.CONTRADICT, temporal=False)]
    )
    results.append(
        ChallengeResult(
            "CH-08",
            "evidence outside claim period",
            outside_period.outcome == ClaimOutcome.INSUFFICIENT,
            outside_period.outcome.value,
            "Evidence outside the applicable period is excluded.",
        )
    )

    exception = assess_claim(
        [
            _evidence("rule", EvidenceRelationship.SUPPORT, mode=EvidenceMode.FORMAL_RULE),
            _evidence(
                "exception", EvidenceRelationship.CONTRADICT, mode=EvidenceMode.OBSERVED_PRACTICE
            ),
        ]
    )
    results.append(
        ChallengeResult(
            "CH-09",
            "informal exception versus approved rule",
            exception.outcome == ClaimOutcome.CONTESTED,
            exception.outcome.value,
            "An informal exception does not erase the approved rule or observed practice.",
        )
    )

    marginal = [_evidence("marginal", EvidenceRelationship.SUPPORT, value=0.6)]
    sensitivity = {
        threshold: assess_claim(
            marginal, config=ReasoningConfig(materiality_threshold=threshold)
        ).outcome
        for threshold in (0.5, 0.7)
    }
    results.append(
        ChallengeResult(
            "CH-10",
            "threshold sensitivity",
            sensitivity[0.5] != sensitivity[0.7],
            f"0.5={sensitivity[0.5].value}; 0.7={sensitivity[0.7].value}",
            "Material threshold sensitivity is exposed rather than hidden.",
        )
    )
    return results


def challenge_export() -> list[dict[str, object]]:
    return [asdict(item) for item in run_challenges()]
