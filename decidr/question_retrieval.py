"""Retrieval-first context for experimental interpretation-2.0 Stage 2A."""

from collections.abc import Callable
from dataclasses import dataclass
import json
import sqlite3
from time import perf_counter
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from decidr.hybrid import HybridResult, reciprocal_rank_fusion
from decidr.retrieval import RetrievalResult, SearchQuery, lexical_text_search
from decidr.semantic import (
    Embedder,
    SemanticResult,
    SentenceTransformerEmbedder,
    semantic_text_search,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class RetrievedContextLimits(StrictModel):
    max_passages: int = Field(default=5, ge=1, le=20)
    max_characters_per_passage: int = Field(default=800, ge=100, le=8000)
    max_total_passage_characters: int = Field(default=4000, ge=100, le=40000)


class RetrievedContextPassage(StrictModel):
    evidence_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    title_or_locator: str = Field(min_length=1)
    source_type: str = Field(min_length=1)
    lifecycle_status: str = Field(min_length=1)
    effective_start_date: str | None = None
    effective_end_date: str | None = None
    retrieval_rank: int = Field(ge=1)
    lexical_rank: int | None = Field(default=None, ge=1)
    semantic_rank: int | None = Field(default=None, ge=1)
    text: str = Field(min_length=1)


class RetrievedContextPackage(StrictModel):
    passages: list[RetrievedContextPassage]
    passage_characters: int = Field(ge=0)

    @model_validator(mode="after")
    def consistent_character_count(self):
        if self.passage_characters != sum(len(item.text) for item in self.passages):
            raise ValueError("Retrieved-context character count is inconsistent")
        identities = [(item.source_id, item.evidence_id) for item in self.passages]
        if len(identities) != len(set(identities)):
            raise ValueError("Retrieved context contains duplicate evidence identities")
        return self


@dataclass(frozen=True, slots=True)
class NeutralRetrievalRun:
    query: SearchQuery
    lexical: tuple[RetrievalResult, ...]
    semantic: tuple[SemanticResult, ...]
    combined: tuple[HybridResult, ...]
    execution_order: tuple[str, ...]
    component_status: dict[str, str]
    component_latency_ms: dict[str, float]


EmbedderFactory = Callable[[str], Embedder]


class RawQuestionRetriever:
    """Always run lexical retrieval before optional, failure-isolated semantics."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        semantic_enabled: bool = False,
        embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2",
        embedder_factory: EmbedderFactory | None = None,
    ) -> None:
        self.connection = connection
        self.semantic_enabled = semantic_enabled
        self.embedding_model = embedding_model
        self.embedder_factory = embedder_factory or SentenceTransformerEmbedder

    def retrieve(self, question: str, limit: int = 20) -> NeutralRetrievalRun:
        query = SearchQuery(question)
        order: list[str] = []
        latency: dict[str, float] = {}
        started = perf_counter()
        lexical = lexical_text_search(self.connection, query, limit=max(limit, 30))
        latency["lexical"] = round((perf_counter() - started) * 1000, 2)
        order.append("lexical")
        statuses = {"lexical": "available", "semantic": "disabled by configuration"}
        semantic: list[SemanticResult] = []
        if self.semantic_enabled:
            started = perf_counter()
            order.append("semantic")
            try:
                embedder = self.embedder_factory(self.embedding_model)
                semantic = semantic_text_search(
                    self.connection, query, embedder, limit=max(limit, 30)
                )
                statuses["semantic"] = "available (configured local model used)"
            except Exception as error:  # noqa: BLE001 - optional component is isolated
                statuses["semantic"] = (
                    f"configured but unavailable: {type(error).__name__}: {error}"
                )
            latency["semantic"] = round((perf_counter() - started) * 1000, 2)
        started = perf_counter()
        combined = reciprocal_rank_fusion(lexical, semantic, limit=limit)
        latency["fusion"] = round((perf_counter() - started) * 1000, 2)
        order.append("fusion")
        statuses["fusion"] = "available"
        return NeutralRetrievalRun(
            query=query,
            lexical=tuple(lexical),
            semantic=tuple(semantic),
            combined=tuple(combined),
            execution_order=tuple(order),
            component_status=statuses,
            component_latency_ms=latency,
        )


def _sentence_clip(text: str, limit: int) -> str:
    value = text.strip()
    if len(value) <= limit:
        return value
    candidate = value[:limit]
    boundaries = [
        index + 1
        for index, character in enumerate(candidate)
        if character in ".!?" and (index + 1 == len(candidate) or candidate[index + 1].isspace())
    ]
    if boundaries:
        return candidate[: boundaries[-1]].rstrip()
    whitespace = candidate.rfind(" ")
    return candidate[:whitespace].rstrip() if whitespace > 0 else candidate


def build_retrieved_context(
    connection: sqlite3.Connection,
    run: NeutralRetrievalRun,
    limits: RetrievedContextLimits | None = None,
) -> RetrievedContextPackage:
    """Build the metadata-allowlisted, deterministic model context."""
    limits = limits or RetrievedContextLimits()
    passages: list[RetrievedContextPassage] = []
    remaining = limits.max_total_passage_characters
    for result in run.combined:
        if len(passages) == limits.max_passages or remaining <= 0:
            break
        row = connection.execute(
            """
            SELECT s.payload_json, e.locator
            FROM evidence e JOIN sources s ON s.source_id=e.source_id
            WHERE e.evidence_id=?
            """,
            (result.evidence_id,),
        ).fetchone()
        if not row:
            continue
        source: dict[str, Any] = json.loads(row[0])
        available = min(limits.max_characters_per_passage, remaining)
        clipped = _sentence_clip(result.text, available)
        if not clipped:
            continue
        passages.append(
            RetrievedContextPassage(
                evidence_id=result.evidence_id,
                source_id=result.source_id,
                title_or_locator=source.get("title") or row[1],
                source_type=source["source_type"],
                lifecycle_status=source.get("lifecycle_status", "unknown"),
                effective_start_date=source.get("effective_start_date"),
                effective_end_date=source.get("effective_end_date"),
                retrieval_rank=result.rank,
                lexical_rank=result.lexical_rank,
                semantic_rank=result.semantic_rank,
                text=clipped,
            )
        )
        remaining -= len(clipped)
    total = sum(len(item.text) for item in passages)
    return RetrievedContextPackage(passages=passages, passage_characters=total)


__all__ = [
    "NeutralRetrievalRun",
    "RawQuestionRetriever",
    "RetrievedContextLimits",
    "RetrievedContextPackage",
    "RetrievedContextPassage",
    "build_retrieved_context",
]
