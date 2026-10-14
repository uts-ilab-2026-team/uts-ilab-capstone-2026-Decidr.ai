"""Translate one LLM reading ("finding") into fields the graph engine can score.

The shim does NO judging. It provides the pure field table (`_map_quality`) that maps an LLM
finding's stance/mode/source_type onto the engine's attestation scalars, and the verbatim-quote
resolver (`_find_passage`) that binds a quotation to its stored passage. The scoring itself is
done by ``decidr.backbone_assessment`` (fact + FORMAL/OBSERVED overlay on the real skeleton →
``evaluate_fact``); this module only supplies the per-edge fields.

Run the bundled demo (one recorded llama fixture, no Ollama needed):
    uv run python -m decidr.finding_shim
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from framework import CONFIG_PATH
from framework.config import GraphCredibilityConfig

from decidr.backbone_graph import DATA_DIR, SOURCE_CLASS_BY_TYPE, _approval_key
from decidr.constants import DEFAULT_AS_OF  # noqa: F401  (re-exported for existing importers)
from decidr.ingestion import ingest
from decidr.retrieval_models import Evidence, Source

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
# 2. Verbatim-quote resolver (binds a finding's quotation to a stored passage)  #
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


# --------------------------------------------------------------------------- #
# Demo / self-test — shows the field mapping; scoring lives in backbone_assessment
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
    source = snapshot.sources_by_code[finding.source_code]
    passage, start, end = _find_passage(
        snapshot.evidence_by_source.get(source.source_id, []), finding.quotation
    )
    quality = _map_quality(finding, source, config)

    print("LLM finding:")
    print(f"  claim : {finding.claim_text}")
    print(f"  facet : {finding.facet}")
    print(f"  stance: {finding.stance}   mode: {finding.mode}")
    print(f"  source: {finding.source_code}")
    print(f"  quote : {finding.quotation[:80]}...")
    print("\nmapped engine fields (the shim's output):")
    print(f"  source_class      = {quality['source_class']}")
    print(f"  approval_key      = {quality['approval_key']}")
    print(f"  mode (-> edge)    = {finding.mode.upper()}")
    print(f"  agrees            = {finding.stance == 'support'}")
    print(
        f"  directness/spec/comp = "
        f"{quality['directness']}/{quality['specificity']}/{quality['completeness']}"
    )
    print(f"  matched passage   = {passage.evidence_id} ({passage.source_id}) [{start}:{end}]")
    print("\n(scoring: see `python -m decidr.backbone_assessment` — fact overlay on the skeleton)")


if __name__ == "__main__":
    main()
