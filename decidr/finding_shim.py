"""Translate one LLM reading ("finding") into a graph attestation the engine can score.

This is the shim (Phase 2a): LLM finding -> PreparedAttestation -> assess_prepared_facet
-> framework engine. It does NO judging — it only maps the LLM's fields onto the
attestation shape and resolves the cited document/passage against the live corpus so
citation-binding (exact-substring check) passes.

Two layers, kept separate on purpose:
  1. _map_quality(): the pure field table (stance/mode/source_type -> engine fields).
  2. resolve_and_prepare(): finds our Source + Evidence passage for the finding, so the
     adapter's verbatim-quote check succeeds even though fixtures use a different release id.

Run the bundled demo (one recorded llama fixture, no Ollama needed):
    uv run python -m decidr.finding_shim
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path

from framework import CONFIG_PATH
from framework.config import GraphCredibilityConfig

from decidr.assessment_adapter import FacetAssessmentResult, PreparedAttestation, assess_prepared_facet
from decidr.backbone_graph import DATA_DIR, SOURCE_CLASS_BY_TYPE, _approval_key
from decidr.ingestion import ingest
from decidr.interpretation_models import EvidenceInterpretation, InterpretationCitation
from decidr.retrieval_models import Evidence, Source

DEFAULT_AS_OF = date(2026, 7, 31)  # dataset is read "as at 31 July 2026"


# --------------------------------------------------------------------------- #
# The LLM finding (just the fields the shim consumes)                          #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class LlmFinding:
    claim_text: str
    facet: str
    stance: str  # support | contradict | qualify | context | unresolved
    mode: str  # formal | observed | unresolved
    rationale: str
    source_code: str  # e.g. "POL-01" (release prefix stripped)
    quotation: str
    # Optional richer signals (present in general-assessment findings, absent in the
    # interpretation fixtures). None -> engine-safe default applied in _map_quality.
    scope_fit: bool | None = None
    time_fit: bool | None = None
    directness: float | None = None
    # Person-level authority (for backbone_resolution). Set when the finding names an
    # approver/actor; both are graph node ids, e.g. "person:diane-okafor" / "role:head-...".
    actor_person_id: str | None = None
    expected_role_id: str | None = None


def finding_from_result_json(path: Path) -> LlmFinding:
    """Parse one recorded pilot `result.json` into an LlmFinding."""
    data = json.loads(path.read_text(encoding="utf-8"))
    interp = data["interpretation"]
    citation = interp["citations"][0]
    return LlmFinding(
        claim_text=interp["claim_text"],
        facet=interp["facet"],
        stance=interp["stance"],
        mode=interp["mode"],
        rationale=interp["rationale"],
        source_code=_strip_release(citation["source_id"]),
        quotation=citation["quotation"],
    )


# --------------------------------------------------------------------------- #
# Corpus snapshot (resolve a finding's document + passage against our corpus)  #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class CorpusSnapshot:
    sources_by_code: dict[str, Source]
    evidence_by_source: dict[str, list[Evidence]]


def _strip_release(source_id: str) -> str:
    return source_id.split(":", 1)[1] if ":" in source_id else source_id


def load_corpus_snapshot(data_dir: Path = DATA_DIR, *, release: str = "phase1") -> CorpusSnapshot:
    result = ingest({release: data_dir})
    sources_by_code: dict[str, Source] = {}
    evidence_by_source: dict[str, list[Evidence]] = {}
    for source in result.sources:
        sources_by_code[_strip_release(source.source_id)] = source
    for passage in result.evidence:
        evidence_by_source.setdefault(passage.source_id, []).append(passage)
    return CorpusSnapshot(sources_by_code, evidence_by_source)


# --------------------------------------------------------------------------- #
# 1. The field table (pure mapping, no corpus access)                          #
# --------------------------------------------------------------------------- #

_STANCE = {"support", "contradict", "qualify", "context", "unresolved"}
_MODE = {"formal", "observed", "unresolved"}


def _map_quality(finding: LlmFinding, source: Source, config: GraphCredibilityConfig) -> dict:
    """The shim 'table': LLM finding + source metadata -> PreparedAttestation scalars."""
    if finding.stance not in _STANCE:
        raise ValueError(f"unknown stance {finding.stance!r}")
    if finding.mode not in _MODE:
        raise ValueError(f"unknown mode {finding.mode!r}")
    source_class = SOURCE_CLASS_BY_TYPE.get(source.source_type, "unknown")
    approval_key = _approval_key(source.approval_status, source.lifecycle_status or "")
    if source_class not in config.source_class_weights:
        raise ValueError(f"source_class {source_class!r} not configured")
    if approval_key not in config.approval_weights:
        raise ValueError(f"approval_key {approval_key!r} not configured")
    decisive = finding.stance in {"support", "contradict"}
    return {
        "source_class": source_class,
        "approval_key": approval_key,
        # None -> True default: fixtures omit scope/time; richer findings supply them.
        "scope_matches": True if finding.scope_fit is None else finding.scope_fit,
        "temporal_matches": True if finding.time_fit is None else finding.time_fit,
        # Formal document rule carries its own authority; person-level resolution is Phase 2b.
        "authority_verified": True if finding.mode == "formal" else None,
        "directness": 1.0 if finding.directness is None else finding.directness,
        "specificity": 1.0,
        "completeness": 1.0 if decisive else 0.5,
        "origin_basis": "source-level origin from ingestion",
        "judgement_basis": finding.rationale,
    }


# --------------------------------------------------------------------------- #
# 2. Resolve + build the PreparedAttestation                                   #
# --------------------------------------------------------------------------- #


def _find_passage(passages: list[Evidence], quotation: str) -> tuple[Evidence, int, int]:
    """Return the passage containing the exact quotation, plus its (start, end) offsets."""
    for passage in passages:
        index = passage.text.find(quotation)
        if index != -1:
            return passage, index, index + len(quotation)
    raise ValueError(
        f"quotation not found verbatim in any passage of the cited source "
        f"(quotation starts: {quotation[:60]!r})"
    )


def resolve_and_prepare(
    finding: LlmFinding, snapshot: CorpusSnapshot, config: GraphCredibilityConfig
) -> tuple[PreparedAttestation, Evidence]:
    """Match the finding to our Source + Evidence and build one PreparedAttestation."""
    source = snapshot.sources_by_code.get(finding.source_code)
    if source is None:
        raise ValueError(f"no corpus source for code {finding.source_code!r}")
    passages = snapshot.evidence_by_source.get(source.source_id, [])
    passage, start, end = _find_passage(passages, finding.quotation)

    citation = InterpretationCitation(
        evidence_id=passage.evidence_id,
        source_id=passage.source_id,
        locator=passage.locator,
        quotation=finding.quotation,
        start=start,
        end=end,
    )
    interpretation = EvidenceInterpretation(
        claim_text=finding.claim_text,
        facet=finding.facet,
        stance=finding.stance,
        mode=finding.mode,
        rationale=finding.rationale,
        citations=(citation,),
    )
    quality = _map_quality(finding, source, config)
    prepared = PreparedAttestation(
        interpretation=interpretation,
        source=source,
        origin_id=str(source.duplicate_group or source.source_id),
        **quality,
    )
    return prepared, passage


def assess_finding(
    finding: LlmFinding,
    snapshot: CorpusSnapshot,
    config: GraphCredibilityConfig,
    *,
    as_of: date = DEFAULT_AS_OF,
) -> FacetAssessmentResult:
    """Full shim path for a single finding: resolve -> prepare -> engine."""
    prepared, passage = resolve_and_prepare(finding, snapshot, config)
    return assess_prepared_facet(
        claim_text=finding.claim_text,
        facet=finding.facet,
        as_of=as_of,
        prepared=[prepared],
        evidence=[passage],
        config=config,
    )


def assess_findings(
    findings: Iterable[LlmFinding],
    snapshot: CorpusSnapshot,
    config: GraphCredibilityConfig,
    *,
    facet: str,
    claim_text: str,
    as_of: date = DEFAULT_AS_OF,
) -> FacetAssessmentResult:
    """Assess several findings for ONE facet together (one Fact, many attestations)."""
    prepared = []
    passages = []
    for finding in findings:
        item, passage = resolve_and_prepare(finding, snapshot, config)
        prepared.append(item)
        passages.append(passage)
    return assess_prepared_facet(
        claim_text=claim_text,
        facet=facet,
        as_of=as_of,
        prepared=prepared,
        evidence=passages,
        config=config,
    )


# --------------------------------------------------------------------------- #
# Demo / self-test                                                             #
# --------------------------------------------------------------------------- #

_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "evaluation/interpretation/runs"
    / "llama31-pilot-v2-20261009T130632838321Z"
    / "C01-01--approval_requirement"
    / "result.json"
)


def main() -> None:
    config = GraphCredibilityConfig.load(CONFIG_PATH)
    snapshot = load_corpus_snapshot()
    finding = finding_from_result_json(_FIXTURE)

    print("LLM finding:")
    print(f"  claim : {finding.claim_text}")
    print(f"  facet : {finding.facet}")
    print(f"  stance: {finding.stance}   mode: {finding.mode}")
    print(f"  source: {finding.source_code}")
    print(f"  quote : {finding.quotation[:80]}...")

    prepared, passage = resolve_and_prepare(finding, snapshot, config)
    print("\nmapped PreparedAttestation:")
    print(f"  source_class      = {prepared.source_class}")
    print(f"  approval_key      = {prepared.approval_key}")
    print(f"  mode (-> edge)    = {prepared.interpretation.mode.upper()}")
    print(f"  agrees            = {prepared.interpretation.stance == 'support'}")
    print(f"  directness/spec/comp = {prepared.directness}/{prepared.specificity}/{prepared.completeness}")
    print(f"  matched passage   = {passage.evidence_id} ({passage.source_id})")

    result = assess_finding(finding, snapshot, config)
    a = result.assessment
    print("\nengine verdict:")
    print(f"  formal_outcome   = {a.formal_outcome}")
    print(f"  observed_outcome = {a.observed_outcome}")
    print(f"  overall_outcome  = {a.overall_outcome}")
    print(f"  confidence       = {a.confidence}")
    if a.evidence:
        edge = a.evidence[0]
        print(f"  scored edge      = material={edge.material} score={edge.materiality_score:.3f}")


if __name__ == "__main__":
    main()
