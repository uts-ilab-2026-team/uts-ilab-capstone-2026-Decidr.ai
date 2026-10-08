# Adapted from decidr/hybrid.py at commit 90ffff9.
"""Documented reciprocal-rank fusion over common retrieval candidates."""

from dataclasses import dataclass
from typing import Protocol


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
