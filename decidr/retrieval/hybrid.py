# Adapted from decidr/hybrid.py at commit 90ffff9.
"""Documented reciprocal-rank fusion over common retrieval candidates."""

from dataclasses import dataclass, replace
import sqlite3
from typing import Protocol

from decidr.corpus.models import Evidence
from decidr.retrieval.lexical import (
    RecordReference,
    find_record_references,
    lexical_search_text,
    record_identifiers,
)
from decidr.retrieval.semantic import Embedder, semantic_search_text


class RankedResult(Protocol):
    evidence_id: str
    source_id: str
    locator: str
    text: str
    rank: int


@dataclass(frozen=True, slots=True)
class HybridResult:
    evidence_id: str
    source_id: str
    locator: str
    text: str
    rank: int
    combined_score: float
    lexical_rank: int | None
    semantic_rank: int | None


def reciprocal_rank_fusion(
    lexical: list[RankedResult], semantic: list[RankedResult], limit: int = 20, k: int = 60
) -> list[HybridResult]:
    """Fuse rankings once per evidence ID, preventing duplicate result inflation."""
    if k <= 0:
        raise ValueError("RRF k must be positive")
    records: dict[str, dict[str, object]] = {}
    for method, results in (("lexical", lexical), ("semantic", semantic)):
        for item in results:
            record = records.setdefault(
                item.evidence_id,
                {
                    "source_id": item.source_id,
                    "locator": item.locator,
                    "text": item.text,
                    "lexical_rank": None,
                    "semantic_rank": None,
                    "score": 0.0,
                },
            )
            rank_key = f"{method}_rank"
            if record[rank_key] is None:
                record[rank_key] = item.rank
                record["score"] = float(record["score"]) + 1 / (k + item.rank)
    ordered = sorted(records.items(), key=lambda item: (-float(item[1]["score"]), item[0]))
    return [
        HybridResult(
            evidence_id=evidence_id,
            source_id=str(record["source_id"]),
            locator=str(record["locator"]),
            text=str(record["text"]),
            rank=rank,
            combined_score=float(record["score"]),
            lexical_rank=record["lexical_rank"],
            semantic_rank=record["semantic_rank"],
        )
        for rank, (evidence_id, record) in enumerate(ordered[:limit], start=1)
    ]


@dataclass(frozen=True, slots=True)
class EvidenceGroup:
    """One ranked section or record, with individually traceable passages."""

    rank: int
    lead_result: RankedResult
    matched_evidence_ids: tuple[str, ...]
    passages: tuple[Evidence, ...]


def group_ranked_evidence(
    results: list[RankedResult],
    evidence: list[Evidence],
    *,
    limit: int = 20,
) -> list[EvidenceGroup]:
    """Group an ordered candidate ranking before applying the display limit.

    A group's position comes from its best-ranked passage, without summing
    scores. Additional section passages provide context, not independent
    matches or evidence of support. Supply the complete candidate ranking;
    grouping cannot recover candidates removed by an earlier cutoff.
    """
    if type(limit) is not int or limit < 0:
        raise ValueError("limit must be a non-negative integer")
    if not results or limit == 0:
        return []

    def key(item: Evidence) -> tuple[str, str, str]:
        if (
            item.extraction_method.startswith("markdown_")
            and item.section
            and item.heading
            and item.row_identifier is None
        ):
            return ("section", item.source_id, item.section)
        return ("record", item.source_id, item.evidence_id)

    by_id: dict[str, Evidence] = {}
    sections: dict[tuple[str, str, str], list[Evidence]] = {}
    for item in evidence:
        if item.evidence_id in by_id:
            raise ValueError(f"Duplicate evidence ID: {item.evidence_id}")
        by_id[item.evidence_id] = item
        sections.setdefault(key(item), []).append(item)

    leads: dict[tuple[str, str, str], RankedResult] = {}
    matches: dict[tuple[str, str, str], list[str]] = {}
    seen: set[str] = set()

    for result in sorted(results, key=lambda item: (item.rank, item.evidence_id)):
        item = by_id.get(result.evidence_id)
        if item is None:
            raise ValueError(f"Missing evidence: {result.evidence_id}")
        if (result.source_id, result.locator, result.text) != (
            item.source_id,
            item.locator,
            item.text,
        ):
            raise ValueError(f"Result does not match evidence: {result.evidence_id}")
        if item.evidence_id in seen:
            continue
        seen.add(item.evidence_id)
        group_key = key(item)
        leads.setdefault(group_key, result)
        matches.setdefault(group_key, []).append(item.evidence_id)

    grouped = []
    for group_key, lead in list(leads.items())[:limit]:
        passages = sorted(
            sections[group_key],
            key=lambda item: (
                item.paragraph if item.paragraph is not None else float("inf"),
                item.locator,
                item.evidence_id,
            ),
        )
        grouped.append(
            EvidenceGroup(
                rank=len(grouped) + 1,
                lead_result=lead,
                matched_evidence_ids=tuple(matches[group_key]),
                passages=tuple(item.model_copy(deep=True) for item in passages),
            )
        )
    return grouped


@dataclass(frozen=True, slots=True)
class CorpusCandidate:
    """A candidate with separate retrieval and identifier provenance.

    rank is the candidate ordering used for grouping. Reference-only candidates
    follow retrieved candidates and have retrieval=None, not a relevance score.
    """

    evidence_id: str
    source_id: str
    locator: str
    text: str
    rank: int
    retrieval: HybridResult | None
    record_references: tuple[RecordReference, ...]


@dataclass(frozen=True, slots=True)
class CorpusSearchResult:
    """Ranked selection plus linked groups outside that selection."""

    ranked_groups: tuple[EvidenceGroup, ...]
    additional_linked_groups: tuple[EvidenceGroup, ...]
    candidates: tuple[CorpusCandidate, ...]


def search_corpus(
    connection: sqlite3.Connection,
    query: str,
    *,
    limit: int = 8,
    embedder: Embedder | None = None,
) -> CorpusSearchResult:
    """Search the indexed corpus and preserve explicit record connections.

    limit controls ranked groups, not the number of additional linked groups.
    Every explicit connection is retained in one of the two group collections.
    Full passage rankings are used before grouping for the current small corpus.
    Queries naming record identifiers display only groups explicitly linked to
    those identifiers. General queries retain whole-corpus relevance ranking.
    Reference-only groups remain additional linked evidence.

    Lexical-only search does not write. Optional semantic search uses the
    existing embedding cache; the caller controls its transaction. Semantic
    errors propagate rather than silently changing the retrieval method.

    Results are retrieval candidates, not support/contradiction decisions.
    """
    if type(limit) is not int or limit < 0:
        raise ValueError("limit must be a non-negative integer")

    empty = CorpusSearchResult((), (), ())
    query = query.strip()
    if not query or limit == 0:
        return empty

    evidence = [
        Evidence.model_validate_json(row[0])
        for row in connection.execute("SELECT payload_json FROM evidence ORDER BY evidence_id")
    ]
    if not evidence:
        return empty

    by_id = {item.evidence_id: item for item in evidence}
    references = find_record_references(query, evidence)
    references_by_id: dict[str, list[RecordReference]] = {}
    for reference in references:
        references_by_id.setdefault(reference.evidence_id, []).append(reference)

    lexical = lexical_search_text(connection, query, limit=len(evidence))
    semantic = (
        semantic_search_text(connection, query, embedder, limit=len(evidence))
        if embedder is not None
        else []
    )
    fused = reciprocal_rank_fusion(lexical, semantic, limit=len(evidence))
    retrieval_by_id = {item.evidence_id: item for item in fused}

    # Validate both retrieval channels before fusion can mask a stale citation.
    for result in [*lexical, *semantic]:
        original = by_id.get(result.evidence_id)
        if original is None or (result.source_id, result.locator, result.text) != (
            original.source_id,
            original.locator,
            original.text,
        ):
            raise ValueError(
                f"Retrieval result does not match stored evidence: {result.evidence_id}"
            )

    ordered_ids = [item.evidence_id for item in fused]
    ordered_ids.extend(sorted(set(references_by_id) - set(retrieval_by_id)))

    candidates = []
    for rank, identifier in enumerate(ordered_ids, start=1):
        item = by_id[identifier]
        candidates.append(
            CorpusCandidate(
                evidence_id=identifier,
                source_id=item.source_id,
                locator=item.locator,
                text=item.text,
                rank=rank,
                retrieval=retrieval_by_id.get(identifier),
                record_references=tuple(references_by_id.get(identifier, ())),
            )
        )

    groups = group_ranked_evidence(candidates, evidence, limit=len(evidence))
    if record_identifiers(query):
        # An explicit entity anchors the search. Keyword overlap alone must not
        # introduce unrelated records; keep section context only for linked groups.
        groups = [
            group
            for group in groups
            if any(p.evidence_id in references_by_id for p in group.passages)
        ]
    retrieved_groups = [
        group for group in groups if group.lead_result.evidence_id in retrieval_by_id
    ]
    # Explicit record connections affect display priority, not relevance scores
    # or credibility. Stable sorting preserves retrieval order within each tier.
    # Check all section members, including context passages.
    retrieved_groups.sort(
        key=lambda group: (
            not any(passage.evidence_id in references_by_id for passage in group.passages)
        )
    )
    ranked_groups = tuple(
        replace(group, rank=position)
        for position, group in enumerate(retrieved_groups[:limit], start=1)
    )
    selected_ids = {group.lead_result.evidence_id for group in ranked_groups}
    additional_linked_groups = tuple(
        group
        for group in groups
        if group.lead_result.evidence_id not in selected_ids
        and any(identifier in references_by_id for identifier in group.matched_evidence_ids)
    )

    return CorpusSearchResult(ranked_groups, additional_linked_groups, tuple(candidates))
