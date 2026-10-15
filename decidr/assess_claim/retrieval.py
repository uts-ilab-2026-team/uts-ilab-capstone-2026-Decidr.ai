"""Retrieval — small in-memory FTS index over the already-ingested corpus, plus the
reader-finding converter."""

from __future__ import annotations

import re
import sqlite3

import networkx as nx

from decidr.finding_shim import CorpusSnapshot, LlmFinding, _strip_release
from decidr.graph.graph import OrganisationalGraph
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


def _skeleton_codes(skeleton: OrganisationalGraph) -> set[str]:
    """The document codes that have a node in the backbone (the only scoreable sources)."""
    return {
        nid.split(":", 1)[1]
        for nid, kind in skeleton.graph.nodes(data="kind")
        if kind == "document"
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
    # Load any pre-indexed embeddings so retrieval reuses them instead of re-embedding per claim.
    from decidr.semantic import preload_cached_vectors

    preload_cached_vectors(connection)
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
    for nid, data in skeleton.graph.nodes(data=True):
        if data.get("kind") != "process":
            continue
        label_tokens = _content_tokens(data["label"]) - _PROCESS_STOP
        overlap = len(claim_tokens & label_tokens)
        if overlap > 0:
            scored.append((overlap, nid, data["label"]))
    if not scored:
        return []
    best = max(score for score, _, _ in scored)
    return [(node_id, label) for score, node_id, label in scored if score == best]


def _governs_map(skeleton: OrganisationalGraph) -> dict[str, list[str]]:
    """process node id -> the document codes that GOVERN it."""
    graph = skeleton.graph
    mapping: dict[str, list[str]] = {}
    for nid, kind in graph.nodes(data="kind"):
        if kind != "process":
            continue
        codes = [
            source.replace("document:", "")
            for source, _, rel in graph.in_edges(nid, data="relationship")
            if rel == "GOVERNS"
        ]
        if codes:
            mapping[nid] = codes
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
    ``"graph_governed"`` / ``"graph_related"`` (surfaced by graph guidance) or, for search-sourced
    passages, the honest fused lane: ``"keyword"`` (lexical only), ``"semantic"`` (found by meaning
    only), or ``"hybrid"`` (both lanes). Graph-guidance only ever ADDS governing docs; it never
    restricts the search, so evidence with no process edge (CRM, logs, interviews) stays reachable.
    """
    from decidr.hybrid import search_corpus
    from decidr.semantic import get_embedder

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
    # Build the optional semantic embedder once (None -> lexical-only) and reuse it across
    # every query, so the local model is probed a single time per assessment.
    embedder = get_embedder()
    best_rank: dict[str, int] = {}
    # Which fused lane(s) surfaced each candidate, aggregated across queries, so provenance stays
    # honest: a passage found by meaning is tagged "semantic", not flattened to "keyword".
    lane_hits: dict[str, set[str]] = {}
    for query in queries:
        if not query or not query.strip():
            continue
        result = search_corpus(connection, query, limit=_RETRIEVAL_LIMIT, embedder=embedder)
        for candidate in result.candidates:
            rank = getattr(candidate, "rank", len(evidence_by_id))
            best_rank[candidate.evidence_id] = min(
                rank, best_rank.get(candidate.evidence_id, rank)
            )
            retrieval = getattr(candidate, "retrieval", None)
            if retrieval is not None:
                hits = lane_hits.setdefault(candidate.evidence_id, set())
                if retrieval.lexical_rank is not None:
                    hits.add("lexical")
                if retrieval.semantic_rank is not None:
                    hits.add("semantic")
    keyword_ids = sorted(best_rank, key=lambda eid: best_rank[eid])

    def _search_via(evidence_id: str) -> str:
        """Honest lane label for a search-sourced passage: lexical-only, semantic-only, or both."""
        hits = lane_hits.get(evidence_id, set())
        if "semantic" in hits and "lexical" in hits:
            return "hybrid"
        if hits == {"semantic"}:
            return "semantic"
        return "keyword"  # lexical-only, or a reference-only candidate with no fused rank

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
            via = _search_via(evidence_id)
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
            "semantic": sum(p["retrieved_via"] == "semantic" for p in passages),
            "hybrid": sum(p["retrieved_via"] == "hybrid" for p in passages),
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
