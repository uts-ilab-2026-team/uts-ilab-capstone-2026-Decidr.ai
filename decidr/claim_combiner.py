"""Combine per-facet assessments into one whole-claim verdict (Phase 2c, §7.4).

A claim is split into facets (e.g. approval_requirement / approval_timing /
discount_condition); each is scored independently by the engine. This merges those
facet outcomes with a tiny, deterministic, auditable precedence. It does NOT re-score
anything and deliberately does not reuse ``canonical_assessment``.

Semantics: facets are treated as **conjunctive** — the claim holds only if every
facet holds. Precedence (first match wins):

    1. any facet Contradicted          -> Contradicted      (a sub-claim is refuted)
    2. any facet Contested             -> Contested         (a sub-claim is in conflict)
    3. any facet Insufficient evidence -> Insufficient evidence  (a required part is a gap)
    4. all facets Supported            -> Supported

Confidence = the LOWEST facet confidence (a claim is only as sure as its weakest part).
Missing/insufficient evidence yields Insufficient, never Contradicted (rule GCF7).

Demo (no Ollama):
    uv run python -m decidr.claim_combiner
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from decidr.graph.models import FactAssessment

_OUTCOME_PRECEDENCE = ("Contradicted", "Contested", "Insufficient evidence", "Supported")
_CONFIDENCE_RANK = {"Lower confidence": 0, "Moderate confidence": 1, "Higher confidence": 2}


@dataclass(frozen=True, slots=True)
class FacetVerdict:
    facet: str
    outcome: str
    confidence: str
    decisive: bool = True  # False when the split flagged this facet 'undecisive'


@dataclass(frozen=True, slots=True)
class ClaimVerdict:
    claim_text: str
    overall_outcome: str
    confidence: str
    facets: tuple[FacetVerdict, ...]
    rules_applied: tuple[str, ...]


def _combine_outcomes(outcomes: list[str]) -> tuple[str, str]:
    """Return (overall_outcome, rule_label) by first-match precedence."""
    present = set(outcomes)
    for outcome in _OUTCOME_PRECEDENCE[:-1]:  # Contradicted / Contested / Insufficient
        if outcome in present:
            return outcome, f"any facet {outcome} -> {outcome}"
    return "Supported", "all facets Supported -> Supported"


def _lowest_confidence(confidences: list[str]) -> str:
    return min(confidences, key=lambda c: _CONFIDENCE_RANK.get(c, 0))


def combine(
    assessments: Mapping[str, FactAssessment],
    *,
    claim_text: str,
    non_decisive: frozenset[str] = frozenset(),
) -> ClaimVerdict:
    """Merge per-facet ``FactAssessment``s into one whole-claim ``ClaimVerdict``.

    ``non_decisive`` names facets the splitter flagged 'undecisive' (a subjective
    split disagreement). They are shown in the breakdown but EXCLUDED from the
    outcome/confidence decision, so a spurious over-split cannot drag the claim down.
    """
    if not assessments:
        return ClaimVerdict(
            claim_text,
            "Insufficient evidence",
            "Lower confidence",
            (),
            ("no facets assessed -> Insufficient evidence",),
        )
    facets = tuple(
        FacetVerdict(name, a.overall_outcome, a.confidence, decisive=name not in non_decisive)
        for name, a in assessments.items()
    )
    decisive = [f for f in facets if f.decisive]
    if not decisive:
        # Every facet was flagged; nothing reliable to decide on.
        return ClaimVerdict(
            claim_text,
            "Insufficient evidence",
            "Lower confidence",
            facets,
            (
                "CLAIM_COMBINER_V1_CONJUNCTIVE",
                "all facets flagged undecisive -> Insufficient evidence",
            ),
        )
    overall, rule = _combine_outcomes([f.outcome for f in decisive])
    confidence = _lowest_confidence([f.confidence for f in decisive])
    rules = [
        "CLAIM_COMBINER_V1_CONJUNCTIVE",
        rule,
        f"confidence = lowest decisive-facet confidence -> {confidence}",
    ]
    skipped = [f.facet for f in facets if not f.decisive]
    if skipped:
        rules.append(f"excluded undecisive facets (not required): {', '.join(skipped)}")
    return ClaimVerdict(claim_text, overall, confidence, facets, tuple(rules))


# --------------------------------------------------------------------------- #
# Demo / self-test                                                            #
# --------------------------------------------------------------------------- #


def main() -> None:
    from dataclasses import replace
    from pathlib import Path

    from decidr.backbone_assessment import assess_on_backbone, load_skeleton
    from decidr.finding_shim import finding_from_result_json, load_corpus_snapshot
    from decidr.graph import CONFIG_PATH
    from decidr.graph.config import GraphCredibilityConfig

    config = GraphCredibilityConfig.load(CONFIG_PATH)
    snapshot = load_corpus_snapshot()
    skeleton = load_skeleton()

    fixture = (
        Path(__file__).resolve().parents[1]
        / "evaluation/interpretation/runs"
        / "llama31-pilot-v2-20261009T130632838321Z"
        / "C01-01--approval_requirement"
        / "result.json"
    )
    base = finding_from_result_json(fixture)

    # Facet 1: the requirement is supported by POL-01.
    requirement = assess_on_backbone(
        [base],
        facet="approval_requirement",
        claim_text=base.claim_text,
        snapshot=snapshot,
        skeleton=skeleton,
        config=config,
    )
    # Facet 2: valid authority — but the only evidence names Diane, who lacks the role,
    # so this facet comes back Insufficient (a gap, not a contradiction).
    diane = replace(
        base,
        actor_person_id="person:diane-okafor",
        expected_role_id="role:head-of-finance-people-ops",
        mode="observed",
    )
    authority = assess_on_backbone(
        [diane],
        facet="valid_authority",
        claim_text=base.claim_text,
        snapshot=snapshot,
        skeleton=skeleton,
        config=config,
    )

    verdict = combine(
        {"approval_requirement": requirement, "valid_authority": authority},
        claim_text=base.claim_text,
    )

    print(f"claim: {verdict.claim_text}\n")
    for facet in verdict.facets:
        print(f"  facet {facet.facet:22} -> {facet.outcome}  ({facet.confidence})")
    print(f"\n  WHOLE CLAIM: {verdict.overall_outcome}  |  {verdict.confidence}")
    print("  rules:")
    for rule in verdict.rules_applied:
        print(f"    - {rule}")


if __name__ == "__main__":
    main()
