"""End-to-end: natural-language claim -> whole-claim credibility verdict (Phase 3c core).

This is the single path wired together for the first time. It chains the pieces that were
each proven on their own:

    claim text
      -> claim_split.split_claim            (split into facets; 2 LLM calls, robust/degrades)
      -> retrieve passages                  (in-memory FTS index over the ingested corpus)
      -> fast_reader.evaluate_evidence_fast (ONE batched read: passages x facets -> findings)
      -> _finding_to_llm (converter)        (reader finding dict -> LlmFinding for the shim)
      -> backbone_assessment.assess_on_backbone  (score each facet on the REAL org skeleton)
      -> claim_combiner.combine             (merge facets -> one verdict; trace; undecisive excluded)

Nothing here re-scores or re-judges: the LLM only *reads* (stance + verbatim citation), the
deterministic graph engine does all the scoring. Everything degrades instead of crashing — a
read failure yields an Insufficient verdict with a note, never an exception to the caller.

`to_payload()` returns a plain JSON-safe dict: the exact shape a UI can render.

Live run (needs a local Ollama model; ~2-3 LLM calls, seconds):
    DECIDR_ASSESSMENT_PROVIDER=ollama DECIDR_ASSESSMENT_MODEL=qwen3.5:9b \
        uv run python -m decidr.assess_claim
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import re
import sqlite3

from framework import CONFIG_PATH
from framework.config import GraphCredibilityConfig
from framework.graph import OrganisationalGraph
from framework.models import FactAssessment
import networkx as nx

from decidr.backbone_assessment import assess_on_backbone, load_skeleton
from decidr.claim_combiner import ClaimVerdict, combine
from decidr.claim_interpreter import Provider, ProviderError
from decidr.claim_split import split_claim
from decidr.fast_reader import evaluate_evidence_fast
from decidr.finding_shim import (
    DEFAULT_AS_OF,
    CorpusSnapshot,
    LlmFinding,
    _strip_release,
    load_corpus_snapshot,
)
from decidr.retrieval_models import Evidence
from decidr.retrieval_store import SCHEMA, replace_source_evidence, upsert_source

# Reader relationship vocab -> shim stance vocab.
_STANCE_FROM_RELATIONSHIP = {
    "supports": "support",
    "contradicts": "contradict",
    "qualifies": "qualify",
    "context": "context",
    "unresolved": "unresolved",
}
# Source types whose content is a FORMAL statement (a rule/policy); everything else is
# evidence of practice -> OBSERVED. (source_type vocabulary: backbone_graph.SOURCE_CLASS_BY_TYPE.)
_FORMAL_SOURCE_TYPES = {"policy", "procedure"}
_RETRIEVAL_LIMIT = 8  # ranked groups per keyword query
_MAX_PASSAGES = 10  # cap distinct passages fed to the single batched read
_GOVERNED_PER_DOC = 2  # passages taken from each governing document
_MAX_GOVERNED = 4  # formal-lane cap for graph-governed docs
_MAX_RELATED = 3  # formal-lane cap for one-hop RELATED-expanded docs
# Generic words in process labels that should not drive a claim->process match.
_PROCESS_STOP = {"customer", "process", "review", "request", "intake", "risk", "new"}
# Targets where the GOVERNING DOCUMENT is itself the evidence (so graph-guidance helps). For
# event/observed/state/report targets the governing policy is only context — the evidence lives
# in records/logs, so we do NOT force governing docs in and let the observed lane fill naturally.
_RULE_TARGETS = {"formal_requirement", "formal_authority", "value_accuracy"}


# --------------------------------------------------------------------------- #
# Result container                                                             #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ClaimAssessment:
    """Everything produced for one claim, for inspection or serialisation."""

    claim_text: str
    as_of: date
    verdict: ClaimVerdict
    facet_assessments: dict[str, FactAssessment]
    split: dict
    reading: dict
    passages: list[dict]
    retrieval: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Retrieval — small in-memory FTS index over the already-ingested corpus       #
# --------------------------------------------------------------------------- #


def _skeleton_codes(skeleton: OrganisationalGraph) -> set[str]:
    """The document codes that have a node in the backbone (the only scoreable sources)."""
    return {
        node_id.split(":", 1)[1] for node_id in skeleton.nodes if node_id.startswith("document:")
    }


def _build_index(
    snapshot: CorpusSnapshot, allowed_codes: set[str] | None = None
) -> sqlite3.Connection:
    """Index the ingested snapshot in memory so ``search_corpus`` can run (no corpus.db needed).

    ``allowed_codes`` restricts the index to backbone documents, so non-evidence sources
    (demo scripts, prototypes, README — ``annotation``/``technical`` types never in the
    skeleton) can never be retrieved, read, or scored. You can only retrieve what you can score.
    """
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA)
    for code, source in snapshot.sources_by_code.items():
        if allowed_codes is not None and code not in allowed_codes:
            continue
        upsert_source(connection, source)
        replace_source_evidence(
            connection, source.source_id, snapshot.evidence_by_source.get(source.source_id, [])
        )
    return connection


def _content_tokens(text: str) -> set[str]:
    """Lowercase alphabetic words (>=4 chars), crudely singularised, for overlap matching."""
    tokens = set()
    for word in re.findall(r"[a-z]+", text.lower()):
        if len(word) < 4:
            continue
        tokens.add(word[:-1] if word.endswith("s") and len(word) > 4 else word)
    return tokens


def _match_processes(
    claim_tokens: set[str], skeleton: OrganisationalGraph
) -> list[tuple[str, str]]:
    """Pick the process node(s) whose label best overlaps the claim. Empty if nothing matches."""
    scored: list[tuple[int, str, str]] = []
    for node in skeleton.nodes.values():
        if not node.node_id.startswith("process:"):
            continue
        label_tokens = _content_tokens(node.label) - _PROCESS_STOP
        overlap = len(claim_tokens & label_tokens)
        if overlap > 0:
            scored.append((overlap, node.node_id, node.label))
    if not scored:
        return []
    best = max(score for score, _, _ in scored)
    return [(node_id, label) for score, node_id, label in scored if score == best]


def _governs_map(skeleton: OrganisationalGraph) -> dict[str, list[str]]:
    """process node id -> the document codes that GOVERN it."""
    mapping: dict[str, list[str]] = {}
    for edge in skeleton.edges.values():
        if edge.relationship == "GOVERNS":
            mapping.setdefault(edge.target, []).append(edge.source.replace("document:", ""))
    return mapping


def _related_view(skeleton: OrganisationalGraph) -> nx.MultiDiGraph:
    """A directed RELATED-only view of the skeleton (so ``.successors`` walks only stated links)."""
    graph = skeleton.graph
    related_edges = [
        (source, target, key)
        for source, target, key, relationship in graph.edges(keys=True, data="relationship")
        if relationship == "RELATED"
    ]
    return graph.edge_subgraph(related_edges)


def _related_codes(governed_codes: list[str], skeleton: OrganisationalGraph) -> list[str]:
    """One directed hop over RELATED: codes a governing doc declares, excluding the governing set.

    Walks ``nx.MultiDiGraph.successors`` on a RELATED-only view, so it follows only the links a
    document itself states (a process doc declares none -> expands to nothing) and never chains a
    second hop.
    """
    view = _related_view(skeleton)
    governed_set = set(governed_codes)
    expanded: list[str] = []
    for code in governed_codes:
        node_id = f"document:{code}"
        if node_id not in view:
            continue
        for target in view.successors(node_id):
            neighbour = target.replace("document:", "")
            if neighbour not in governed_set and neighbour not in expanded:
                expanded.append(neighbour)
    return expanded


def _governed_passages(
    governed_codes: list[str],
    claim_tokens: set[str],
    snapshot: CorpusSnapshot,
) -> list[str]:
    """Top passages (by claim overlap) from each governing doc, capped per-doc and overall.

    Guarantees each governing document is represented: if no passage overlaps the claim wording,
    the document's first passage is still included (this is the whole point of graph guidance —
    surfacing the authoritative doc even when it is worded differently from the claim).
    """
    chosen: list[str] = []
    for code in governed_codes:
        source = snapshot.sources_by_code.get(code)
        if source is None:
            continue
        passages = snapshot.evidence_by_source.get(source.source_id, [])
        if not passages:
            continue
        ranked = sorted(
            passages, key=lambda p: len(claim_tokens & _content_tokens(p.text)), reverse=True
        )
        top = [p for p in ranked if claim_tokens & _content_tokens(p.text)][:_GOVERNED_PER_DOC]
        if not top:
            top = ranked[:1]  # represent the doc even with no lexical overlap
        chosen.extend(p.evidence_id for p in top)
    return chosen[:_MAX_GOVERNED]


def _passage_dict(passage: Evidence, retrieved_via: str) -> dict:
    return {
        "evidence_id": passage.evidence_id,
        "source_id": passage.source_id,
        "text": passage.text,
        "locator": passage.locator,
        "heading": passage.heading,
        "retrieved_via": retrieved_via,
    }


def _retrieve_passages(
    connection: sqlite3.Connection,
    claim: str,
    split: dict,
    snapshot: CorpusSnapshot,
    skeleton: OrganisationalGraph,
    evidence_by_id: dict[str, Evidence],
) -> tuple[list[dict], dict]:
    """Lane-balanced retrieval: feed the FORMAL and OBSERVED lanes independently.

    The engine scores formal (what a rule says) and observed (what records show) in two separate
    lanes, then combines them. Retrieval must not let one lane starve the other, so it reserves a
    budget for each lane and fills them from their own ranked candidates. Graph-guidance (pulling a
    process's GOVERNS documents) is applied ONLY for rule-type targets — where the governing policy
    IS the evidence — and feeds the formal lane; for event/observed targets the governing policy is
    only context, so we don't force it and let the observed records fill naturally.

    Returns (passages, retrieval_meta). Each passage carries ``retrieved_via`` =
    ``"graph_governed"`` or ``"keyword"``. Graph-guidance only ever ADDS governing docs; it never
    restricts keyword search, so evidence with no process edge (CRM, logs, interviews) stays reachable.
    """
    from decidr.hybrid import search_corpus

    facet_text = " ".join(component.get("text", "") for component in split.get("components", []))
    claim_tokens = _content_tokens(f"{claim} {facet_text}")
    rule_target = split.get("target") in _RULE_TARGETS

    # Graph-governed (formal lane only, rule-type targets only): claim -> process -> GOVERNS docs.
    processes = _match_processes(claim_tokens, skeleton) if rule_target else []
    governs = _governs_map(skeleton)
    governed_codes: list[str] = []
    for process_id, _label in processes:
        for code in governs.get(process_id, []):
            if code not in governed_codes:
                governed_codes.append(code)
    governed_ids = _governed_passages(governed_codes, claim_tokens, snapshot)[:_MAX_GOVERNED]

    # One directed RELATED hop out of the governing docs (rule-type targets only): pull the docs a
    # governing policy itself declares related (e.g. POL-01 -> POL-06), so the reader sees them too.
    related_codes = _related_codes(governed_codes, skeleton) if rule_target else []
    related_ids = [
        eid
        for eid in _governed_passages(related_codes, claim_tokens, snapshot)
        if eid not in set(governed_ids)
    ][:_MAX_RELATED]

    # Keyword search across the whole (skeleton-only) index.
    queries = list(
        dict.fromkeys(
            [
                claim,
                *split.get("search_queries", [])[:3],
                *(component["text"] for component in split.get("components", [])),
            ]
        )
    )
    best_rank: dict[str, int] = {}
    for query in queries:
        if not query or not query.strip():
            continue
        result = search_corpus(connection, query, limit=_RETRIEVAL_LIMIT)
        for candidate in result.candidates:
            rank = getattr(candidate, "rank", len(evidence_by_id))
            best_rank[candidate.evidence_id] = min(
                rank, best_rank.get(candidate.evidence_id, rank)
            )
    keyword_ids = sorted(best_rank, key=lambda eid: best_rank[eid])

    # Split candidates into lanes by source type (policy/procedure = formal, else observed).
    def _is_formal(evidence_id: str) -> bool:
        passage = evidence_by_id.get(evidence_id)
        return passage is not None and passage.source_type in _FORMAL_SOURCE_TYPES

    governed_set = set(governed_ids)
    related_set = set(related_ids)
    graph_formal_set = governed_set | related_set
    formal_pool = [
        *governed_ids,
        *related_ids,
        *(e for e in keyword_ids if _is_formal(e) and e not in graph_formal_set),
    ]
    observed_pool = [e for e in keyword_ids if not _is_formal(e)]

    # Allocate the budget: up to half to each lane, then let either fill any leftover so a thin
    # lane never wastes slots. Observed is guaranteed at least (total - formal_taken) slots.
    half = _MAX_PASSAGES // 2
    formal_take = formal_pool[:half]
    observed_take = observed_pool[: _MAX_PASSAGES - len(formal_take)]
    chosen = [*formal_take, *observed_take]
    if len(chosen) < _MAX_PASSAGES:
        leftover = [e for e in (*formal_pool, *observed_pool) if e not in set(chosen)]
        chosen.extend(leftover[: _MAX_PASSAGES - len(chosen)])

    passages: list[dict] = []
    seen: set[str] = set()
    for evidence_id in chosen:
        passage = evidence_by_id.get(evidence_id)
        if passage is None or evidence_id in seen:
            continue
        if evidence_id in governed_set:
            via = "graph_governed"
        elif evidence_id in related_set:
            via = "graph_related"
        else:
            via = "keyword"
        passages.append(_passage_dict(passage, via))
        seen.add(evidence_id)

    retrieval_meta = {
        "target": split.get("target"),
        "graph_guided": rule_target,
        "processes_matched": [label for _id, label in processes],
        "governed_docs": governed_codes,
        "related_docs": related_codes,
        "counts": {
            "graph_governed": sum(p["retrieved_via"] == "graph_governed" for p in passages),
            "graph_related": sum(p["retrieved_via"] == "graph_related" for p in passages),
            "keyword": sum(p["retrieved_via"] == "keyword" for p in passages),
        },
        "lanes": {
            "formal": sum(1 for p in passages if _is_formal(p["evidence_id"])),
            "observed": sum(1 for p in passages if not _is_formal(p["evidence_id"])),
        },
    }
    return passages, retrieval_meta


# --------------------------------------------------------------------------- #
# Converter: one reader finding (dict) -> one LlmFinding the shim can consume   #
# --------------------------------------------------------------------------- #


def _tristate(value: str | None) -> bool | None:
    return {"yes": True, "no": False}.get(value or "unknown", None)


def _finding_to_llm(finding: dict, claim: str, snapshot: CorpusSnapshot) -> LlmFinding:
    """Map a ``fast_reader`` finding onto the shim's ``LlmFinding`` shape.

    mode (FORMAL vs OBSERVED) is derived from the cited source's *type*: a rule document
    states something formally; anything else is evidence of practice.
    """
    stance = _STANCE_FROM_RELATIONSHIP.get(finding["relationship"], "unresolved")
    source_code = _strip_release(finding["source_id"])
    source = snapshot.sources_by_code.get(source_code)
    source_type = source.source_type if source is not None else ""
    mode = "formal" if source_type in _FORMAL_SOURCE_TYPES else "observed"
    return LlmFinding(
        claim_text=claim,
        facet=finding["component_id"],
        stance=stance,
        mode=mode,
        rationale=finding.get("reason", ""),
        source_code=source_code,
        quotation=finding["quotation"],
        scope_fit=_tristate(finding.get("scope_fit")),
        time_fit=_tristate(finding.get("time_fit")),
        directness=1.0 if finding.get("directness") == "direct" else 0.5,
    )


# --------------------------------------------------------------------------- #
# The pipeline                                                                 #
# --------------------------------------------------------------------------- #


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


# --------------------------------------------------------------------------- #
# Frontend payload — a plain JSON-safe dict                                    #
# --------------------------------------------------------------------------- #


def _score(value: float | None) -> float | None:
    return None if value is None else round(value, 3)


def _group_evidence(
    assessment: FactAssessment | None, via_by_code: dict[str, set[str]]
) -> list[dict]:
    """Group edges by (source, mode) into one entry per document, each listing its passages.

    Edges from the SAME document are different *passages* of that document — distinct evidence,
    but one source. We collapse them to a single source entry (so the UI shows one row per
    document) and append every passage underneath, keeping each quote, stance and score.
    ``retrieved_via`` records how this source reached the reader (graph_governed / keyword / both).
    """
    if assessment is None:
        return []
    grouped: dict[tuple[str, str], dict] = {}
    for edge in assessment.evidence:
        source = edge.document_id.replace("document:", "")
        key = (source, edge.mode)
        entry = grouped.setdefault(
            key,
            {
                "source": source,
                "title": edge.document_title,
                "mode": edge.mode,
                "source_class": edge.source_class,
                "lifecycle_status": edge.lifecycle_status,
                "retrieved_via": sorted(via_by_code.get(source, set())),
                "material": False,
                "best_score": None,
                "passages": [],
            },
        )
        entry["passages"].append(
            {
                "quote": edge.attests_value,
                "stance": edge.stance,
                "applicable": edge.applicable,
                "material": edge.material,
                "score": _score(edge.materiality_score),
                "limitations": list(edge.limitations),
                "trace": list(edge.trace),
            }
        )
        entry["material"] = entry["material"] or edge.material
        if edge.materiality_score is not None:
            best = entry["best_score"]
            entry["best_score"] = (
                edge.materiality_score if best is None else max(best, edge.materiality_score)
            )
    for entry in grouped.values():
        entry["best_score"] = _score(entry["best_score"])
    return list(grouped.values())


def to_payload(result: ClaimAssessment) -> dict:
    """Serialise a ClaimAssessment into the shape a UI consumes (JSON-safe)."""
    predicate_by_id = {c["id"]: c.get("predicate", "") for c in result.split["components"]}
    text_by_id = {c["id"]: c.get("text", "") for c in result.split["components"]}
    decisive_facets = {f.facet: f.decisive for f in result.verdict.facets}

    # Map each source code -> how its passages were retrieved, from the tagged passage list.
    via_by_code: dict[str, set[str]] = {}
    for passage in result.passages:
        code = _strip_release(passage["source_id"])
        via_by_code.setdefault(code, set()).add(passage["retrieved_via"])

    facets = []
    for facet in result.verdict.facets:
        assessment = result.facet_assessments.get(facet.facet)
        facets.append(
            {
                "facet": facet.facet,
                "predicate": predicate_by_id.get(facet.facet, ""),
                "summary": text_by_id.get(facet.facet, ""),
                "outcome": facet.outcome,
                "confidence": facet.confidence,
                "decisive": decisive_facets.get(facet.facet, True),
                "evidence": _group_evidence(assessment, via_by_code),
            }
        )

    return {
        "claim": result.claim_text,
        "as_of": str(result.as_of),
        "overall_outcome": result.verdict.overall_outcome,
        "confidence": result.verdict.confidence,
        "target": result.split.get("target"),
        "split_status": result.split["semantic_validation"]["status"],
        "facets": facets,
        "rules_applied": list(result.verdict.rules_applied),
        "retrieval": result.retrieval,
        "passages_considered": len(result.passages),
        "findings_count": len(result.reading.get("findings", [])),
        "notes": result.notes,
    }


# --------------------------------------------------------------------------- #
# Live demo                                                                    #
# --------------------------------------------------------------------------- #


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
        f"graph_governed={counts.get('graph_governed', 0)} keyword={counts.get('keyword', 0)}"
    )
    print(
        f"passages considered: {len(result.passages)}   findings: {len(result.reading.get('findings', []))}"
    )
    for facet in result.verdict.facets:
        flag = "" if facet.decisive else "  (undecisive - excluded)"
        print(f"  facet {facet.facet:6} {facet.outcome:22} {facet.confidence}{flag}")
        assessment = result.facet_assessments.get(facet.facet)
        for edge in assessment.evidence if assessment else []:
            score = "n/a" if edge.materiality_score is None else f"{edge.materiality_score:.3f}"
            doc = edge.document_id.replace("document:", "")
            via = "/".join(sorted(via_by_code.get(doc, {"?"})))
            print(
                f"        - {doc} [{edge.mode}] material={edge.material} score={score} via={via}"
            )
    print(f"  => WHOLE CLAIM: {result.verdict.overall_outcome}  |  {result.verdict.confidence}")
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
    as_of = date(2026, 7, 31)

    results = []
    for index, claim in enumerate(claims, start=1):
        print(f"\n{'=' * 90}\n[{index}/{len(claims)}] assessing")
        result = assess_claim(claim, provider, as_of=as_of)
        _print_result(result)
        results.append(result)

    print(f"\n{'=' * 90}\nsummary")
    for result in results:
        print(
            f"  {result.verdict.overall_outcome:22} {result.verdict.confidence:20} {result.claim_text[:60]}"
        )

    # One full payload (the last claim) so the UI shape is visible.
    print(f"\n{'=' * 90}\n--- frontend payload for the last claim (JSON) ---")
    print(json.dumps(to_payload(results[-1]), indent=2))


if __name__ == "__main__":
    main()
