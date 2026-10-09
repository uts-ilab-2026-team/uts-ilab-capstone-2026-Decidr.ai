# Adapted from decidr/hybrid.py at commit 90ffff9.
"""Documented reciprocal-rank fusion over common retrieval candidates."""

from dataclasses import dataclass
from typing import Protocol

from decidr.retrieval_models import Evidence


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
            item.source_id, item.locator, item.text
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
