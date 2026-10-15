"""Live demo CLI for the end-to-end claim assessment pipeline."""

from __future__ import annotations

from typing import TYPE_CHECKING

from decidr.assess_claim.assess import assess_claim
from decidr.assess_claim.confidence import _reconcile_confidence
from decidr.assess_claim.payload import to_payload
from decidr.claim_interpreter import ProviderError
from decidr.finding_shim import DEFAULT_AS_OF, _strip_release

if TYPE_CHECKING:
    from decidr.assess_claim.types import ClaimAssessment


# A spread chosen to land on DIFFERENT verdicts: a formal rule (expect Supported), a general
# practice claim, a universal "all ..." claim (hard to fully support -> often Insufficient/Contested),
# and a single recorded event. Set DECIDR_ASSESS_CLAIM to run just one of your own instead.
_DEMO_CLAIMS = [
    "Discounts above 15% require Finance (Head of Finance & People Ops) approval before the deal is closed.",
    "New customer onboarding follows a standard 6-week implementation process owned by the Customer Success & Delivery team.",
    "All urgent new-business deals with discounts of 15% or greater were closed without prior Finance approval.",
    "DEAL-014 actually closed on 2 July 2025 without any prior Finance approval.",
]


def _print_result(result: ClaimAssessment) -> None:
    facet_conf, claim_score, claim_tier = _reconcile_confidence(result)
    via_by_code: dict[str, set[str]] = {}
    for passage in result.passages:
        via_by_code.setdefault(_strip_release(passage["source_id"]), set()).add(
            passage["retrieved_via"]
        )

    print(f"\nclaim : {result.claim_text}")
    print(
        f"target: {result.split.get('target')}   split: {result.split['semantic_validation']['status']}"
    )
    retrieval = result.retrieval
    procs = retrieval.get("processes_matched") or ["(none)"]
    counts = retrieval.get("counts", {})
    print(
        f"retrieval: process={', '.join(procs)}  governed={retrieval.get('governed_docs') or '[]'}  "
        f"related={retrieval.get('related_docs') or '[]'}  "
        f"graph_governed={counts.get('graph_governed', 0)} "
        f"graph_related={counts.get('graph_related', 0)} keyword={counts.get('keyword', 0)} "
        f"semantic={counts.get('semantic', 0)} hybrid={counts.get('hybrid', 0)}"
    )
    print(
        f"passages considered: {len(result.passages)}   findings: {len(result.reading.get('findings', []))}"
    )
    for facet in result.verdict.facets:
        flag = "" if facet.decisive else "  (undecisive - excluded)"
        score, tier = facet_conf[facet.facet]
        print(f"  facet {facet.facet:6} {facet.outcome:22} {tier} (score={score}){flag}")
        assessment = result.facet_assessments.get(facet.facet)
        for edge in assessment.evidence if assessment else []:
            score = "n/a" if edge.materiality_score is None else f"{edge.materiality_score:.3f}"
            doc = edge.document_id.replace("document:", "")
            via = "/".join(sorted(via_by_code.get(doc, {"?"})))
            print(
                f"        - {doc} [{edge.mode}] material={edge.material} score={score} via={via}"
            )
    print(
        f"  => WHOLE CLAIM: {result.verdict.overall_outcome}  |  {claim_tier} (score={claim_score})"
    )
    if result.notes:
        for note in result.notes:
            print(f"     note: {note}")


def main() -> None:
    import json
    import os

    from decidr.claim_interpreter import get_provider

    try:
        provider = get_provider()
    except ProviderError as error:
        print(f"no local provider available: {error}")
        return

    override = os.environ.get("DECIDR_ASSESS_CLAIM")
    claims = [override] if override else _DEMO_CLAIMS
    as_of = DEFAULT_AS_OF

    results = []
    for index, claim in enumerate(claims, start=1):
        print(f"\n{'=' * 90}\n[{index}/{len(claims)}] assessing")
        result = assess_claim(claim, provider, as_of=as_of)
        _print_result(result)
        results.append(result)

    print(f"\n{'=' * 90}\nsummary")
    for result in results:
        _, claim_score, claim_tier = _reconcile_confidence(result)
        print(
            f"  {result.verdict.overall_outcome:22} {claim_tier:20} "
            f"score={claim_score:<6} {result.claim_text[:60]}"
        )

    # One full payload (the last claim) so the UI shape is visible.
    print(f"\n{'=' * 90}\n--- frontend payload for the last claim (JSON) ---")
    print(json.dumps(to_payload(results[-1]), indent=2))
