"""Optional local semantic retrieval with auditable embedding caching."""

from dataclasses import dataclass
import hashlib
import json
import math
import sqlite3
from typing import Protocol

from decidr.models import AtomicClaim


class SemanticUnavailableError(RuntimeError):
    """Raised when the optional local embedding dependency/model is unavailable."""


class Embedder(Protocol):
    name: str
    version: str

    def encode(self, texts: list[str]) -> list[list[float]]: ...


class SentenceTransformerEmbedder:
    """Lazy adapter; importing the core package never requires sentence-transformers."""

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> None:
        self.name = model_name
        try:
            from sentence_transformers import SentenceTransformer, __version__
        except ImportError as error:
            raise SemanticUnavailableError(
                "Semantic retrieval is unavailable. Install with `uv sync --extra semantic`; "
                "the lexical baseline remains fully operational."
            ) from error
        try:
            self._model = SentenceTransformer(model_name, local_files_only=True)
        except Exception as error:
            raise SemanticUnavailableError(
                f"Local embedding model '{model_name}' is not cached. No model was downloaded."
            ) from error
        self.version = __version__

    def encode(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(texts, normalize_embeddings=True)
        return [vector.tolist() for vector in vectors]


@dataclass(frozen=True, slots=True)
class SemanticResult:
    evidence_id: str
    source_id: str
    locator: str
    text: str
    rank: int
    score: float
    model_name: str
    model_version: str


def claim_text(claim: AtomicClaim) -> str:
    """Use the same complete structured claim representation for all semantic queries."""
    return " | ".join(
        value
        for value in (
            claim.claim_text,
            f"subject: {claim.subject}",
            f"relationship: {claim.predicate}",
            f"target: {claim.object}",
            f"process: {claim.process}" if claim.process else "",
            f"scope: {claim.scope}" if claim.scope else "",
            f"conditions: {', '.join(claim.conditions)}" if claim.conditions else "",
        )
        if value
    )


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        raise ValueError("Embedding vectors must be non-empty and have equal dimensions")
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    denominator = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    return numerator / denominator if denominator else 0.0


def _semantic_search_text(
    connection: sqlite3.Connection,
    query: str,
    embedder: Embedder,
    limit: int = 20,
) -> list[SemanticResult]:
    """Rank all evidence against a supplied query using cached local embeddings."""
    rows = connection.execute(
        "SELECT evidence_id, source_id, locator, text_content FROM evidence ORDER BY evidence_id"
    ).fetchall()
    query_vector = embedder.encode([query])[0]
    scored: list[tuple[float, sqlite3.Row]] = []
    missing: list[sqlite3.Row] = []
    vectors: dict[str, list[float]] = {}
    for row in rows:
        checksum = hashlib.sha256(row[3].encode()).hexdigest()
        cached = connection.execute(
            """
            SELECT vector_json FROM embedding_cache
            WHERE evidence_id=? AND model_name=? AND model_version=? AND content_checksum=?
            """,
            (row[0], embedder.name, embedder.version, checksum),
        ).fetchone()
        if cached:
            vectors[row[0]] = json.loads(cached[0])
        else:
            missing.append(row)
    if missing:
        encoded = embedder.encode([row[3] for row in missing])
        for row, vector in zip(missing, encoded, strict=True):
            checksum = hashlib.sha256(row[3].encode()).hexdigest()
            vectors[row[0]] = vector
            connection.execute(
                """
                INSERT INTO embedding_cache(
                    evidence_id, model_name, model_version, content_checksum, vector_json
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(evidence_id, model_name, model_version) DO UPDATE SET
                    content_checksum=excluded.content_checksum,
                    vector_json=excluded.vector_json,
                    created_at=CURRENT_TIMESTAMP
                """,
                (row[0], embedder.name, embedder.version, checksum, json.dumps(vector)),
            )
    for row in rows:
        scored.append((_cosine(query_vector, vectors[row[0]]), row))
    scored.sort(key=lambda item: (-item[0], item[1][0]))
    return [
        SemanticResult(
            evidence_id=row[0],
            source_id=row[1],
            locator=row[2],
            text=row[3],
            rank=rank,
            score=score,
            model_name=embedder.name,
            model_version=embedder.version,
        )
        for rank, (score, row) in enumerate(scored[:limit], start=1)
    ]


def semantic_search(
    connection: sqlite3.Connection,
    claim: AtomicClaim,
    embedder: Embedder,
    limit: int = 20,
) -> list[SemanticResult]:
    """Rank whole-corpus evidence from a structured claim."""
    return _semantic_search_text(
        connection,
        claim_text(claim),
        embedder,
        limit,
    )


def semantic_search_text(
    connection: sqlite3.Connection,
    query: str,
    embedder: Embedder,
    limit: int = 20,
) -> list[SemanticResult]:
    """Rank whole-corpus evidence directly from a free-text query."""
    cleaned = query.strip()
    if not cleaned:
        return []
    return _semantic_search_text(
        connection,
        cleaned,
        embedder,
        limit,
    )
