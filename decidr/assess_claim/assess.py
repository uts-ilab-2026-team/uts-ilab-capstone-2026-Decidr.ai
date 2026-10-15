"""The pipeline — natural-language claim -> whole-claim credibility verdict (Phase 3c core)."""

from __future__ import annotations

from datetime import date

from decidr.assess_claim.retrieval import (
    _build_index,
    _finding_to_llm,
    _retrieve_passages,
    _skeleton_codes,
)
from decidr.assess_claim.types import ClaimAssessment
from decidr.backbone.assessment import assess_on_backbone, load_skeleton
from decidr.claim_interpreter import Provider, ProviderError
from decidr.claims.combiner import combine
from decidr.claims.split import split_claim
from decidr.graph import CONFIG_PATH
from decidr.graph.config import GraphCredibilityConfig
from decidr.graph.graph import OrganisationalGraph
from decidr.graph.models import FactAssessment
from decidr.reading.fast_reader import evaluate_evidence_fast
from decidr.reading.finding_shim import (
    DEFAULT_AS_OF,
    CorpusSnapshot,
    LlmFinding,
    _strip_release,
    load_corpus_snapshot,
)


def assess_claim(
    claim: str,
    provider: Provider,
    *,
    as_of: date = DEFAULT_AS_OF,
    snapshot: CorpusSnapshot | None = None,
    skeleton: OrganisationalGraph | None = None,
    config: GraphCredibilityConfig | None = None,
) -> ClaimAssessment:
    """Run a claim end to end and return a whole-claim verdict plus every intermediate."""
    config = config or GraphCredibilityConfig.load(CONFIG_PATH)
    snapshot = snapshot or load_corpus_snapshot()
    skeleton = skeleton or load_skeleton()
    notes: list[str] = []

    # 1. Split into facets (robust: never raises for a label disagreement; degrades instead).
    split = split_claim(claim, as_of, provider)
    non_decisive = frozenset(
        component["id"]
        for component in split["components"]
        if component.get("label_status") == "undecisive"
    )
    if split["semantic_validation"]["status"] != "validated":
        notes.append(f"claim split {split['semantic_validation']['status']}")

    # 2. Retrieve candidate passages for the claim + facets. Index ONLY backbone documents,
    #    so non-evidence sources (demo scripts, prototypes, README) can never be retrieved.
    scoreable_codes = _skeleton_codes(skeleton)
    evidence_by_id = {
        passage.evidence_id: passage
        for passages in snapshot.evidence_by_source.values()
        for passage in passages
    }
    connection = _build_index(snapshot, scoreable_codes)
    try:
        passages, retrieval = _retrieve_passages(
            connection, claim, split, snapshot, skeleton, evidence_by_id
        )
    finally:
        connection.close()

    # 3. ONE batched read over all passages x all facets. Degrade (not crash) on a read failure.
    reading: dict = {"findings": []}
    if passages:
        try:
            reading = evaluate_evidence_fast(split, claim, passages, as_of, provider)
        except ProviderError as error:
            notes.append(f"evidence read failed, treated as no evidence: {error}")
    else:
        notes.append("retrieval returned no candidate passages")

    # 4. Group findings by facet and convert to the shim's finding shape. Safety net: drop any
    #    finding that cites a source outside the skeleton (so one stray citation can never abort a
    #    facet). With step 2 filtering retrieval this should not fire, but it keeps scoring robust.
    findings_by_facet: dict[str, list[LlmFinding]] = {}
    for raw in reading.get("findings", []):
        if _strip_release(raw.get("source_id", "")) not in scoreable_codes:
            notes.append(f"dropped finding citing non-evidence source {raw.get('source_id')!r}")
            continue
        try:
            llm = _finding_to_llm(raw, claim, snapshot)
        except (KeyError, ValueError) as error:
            notes.append(f"dropped a malformed finding: {error}")
            continue
        findings_by_facet.setdefault(raw["component_id"], []).append(llm)

    # 5. Score each facet on the real backbone (empty findings -> a genuine gap, Insufficient).
    assessments: dict[str, FactAssessment] = {}
    for component in split["components"]:
        facet = component["id"]
        facet_findings = findings_by_facet.get(facet, [])
        try:
            assessments[facet] = assess_on_backbone(
                facet_findings,
                facet=facet,
                claim_text=claim,
                snapshot=snapshot,
                skeleton=skeleton,
                config=config,
                as_of=as_of,
            )
        except (ValueError, ProviderError) as error:
            notes.append(f"facet {facet} could not be scored, treated as a gap: {error}")

    # 6. Merge facets into one whole-claim verdict (undecisive facets excluded from the decision).
    verdict = combine(assessments, claim_text=claim, non_decisive=non_decisive)

    return ClaimAssessment(
        claim_text=claim,
        as_of=as_of,
        verdict=verdict,
        facet_assessments=assessments,
        split=split,
        reading=reading,
        passages=passages,
        retrieval=retrieval,
        notes=notes,
    )
