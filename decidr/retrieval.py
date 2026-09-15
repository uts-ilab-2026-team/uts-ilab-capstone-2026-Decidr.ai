"""Retrieval process contracts and pipeline boilerplate.

This module defines the boundary between organisational knowledge inputs and the
credibility framework. Retrieval implementation is intentionally deferred.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol


class RetrievalMode(StrEnum):
    """Candidate retrieval modes reserved for later experiments."""

    LEXICAL = "lexical"
    SEMANTIC = "semantic"
    HYBRID = "hybrid"
    GRAPH_AWARE = "graph_aware"


@dataclass(frozen=True, slots=True)
class RetrievalQuery:
    """Structured request accepted by the future retrieval pipeline."""

    text: str
    top_k: int = 10
    mode: RetrievalMode = RetrievalMode.LEXICAL
    entity_ids: tuple[str, ...] = ()
    fact_categories: tuple[str, ...] = ()
    include_superseded: bool = True


@dataclass(frozen=True, slots=True)
class EvidenceCandidate:
    """Candidate evidence returned for later applicability and credibility review."""

    document_id: str
    locator: str
    text: str
    score: float | None = None
    fact_statement: str | None = None
    fact_category: str | None = None
    matched_entity_ids: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


class RetrievalBackend(Protocol):
    """Interface to be implemented by lexical, semantic, or graph-aware backends."""

    name: str

    def retrieve(self, query: RetrievalQuery) -> list[EvidenceCandidate]:
        """Return ranked candidates without making credibility decisions."""
        ...


def retrieve_candidates(
    query: RetrievalQuery,
    *,
    backends: tuple[RetrievalBackend, ...] = (),
) -> list[EvidenceCandidate]:
    """Run candidate retrieval after the team selects and implements the backends."""
    raise NotImplementedError(
        "Retrieval boilerplate only: backend selection and ranking are not implemented."
    )
