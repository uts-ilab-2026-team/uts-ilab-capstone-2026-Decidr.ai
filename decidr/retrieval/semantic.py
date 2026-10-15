# Adapted from decidr/semantic.py at commit 90ffff9.
"""Optional local semantic retrieval with auditable embedding caching."""

from contextlib import closing
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import sqlite3
from typing import Protocol

import ollama

from decidr.infra.constants import ASSESSMENT_URL, EMBEDDING_CACHE_PATH, SEMANTIC_MODEL

# Standalone persistent-cache schema (no FK to evidence, so it stands alone as a file).
_CACHE_SCHEMA = """
CREATE TABLE IF NOT EXISTS embedding_cache (
    evidence_id TEXT NOT NULL,
    model_name TEXT NOT NULL,
    model_version TEXT NOT NULL,
    content_checksum TEXT NOT NULL,
    vector_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(evidence_id, model_name, model_version)
);
"""


class Embedder(Protocol):
    name: str
    version: str

    def encode(self, texts: list[str]) -> list[list[float]]: ...


class OllamaEmbedder:
    """Local Ollama embedding backend (implements the ``Embedder`` protocol).

    Served by the same local Ollama server as the assessment model, so it needs no
    extra model files and runs anywhere Ollama does (including Intel macOS). ``name``
    and ``version`` key the embedding cache; bump ``version`` if the embedding contract
    changes so stale vectors are not reused.
    """

    name = SEMANTIC_MODEL
    version = "ollama-embed-v1"

    def encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = ollama.Client(host=ASSESSMENT_URL).embed(model=self.name, input=list(texts))
        return [list(vector) for vector in response.embeddings]


def get_embedder() -> Embedder | None:
    """A ready local embedder, or ``None`` to fall back to lexical-only retrieval.

    Probes the server once; any failure (server down, model not installed) degrades to
    the deterministic lexical baseline rather than erroring mid-retrieval. Because a
    returned embedder has answered, ``search_corpus`` never sees a semantic failure.
    """
    try:
        embedder = OllamaEmbedder()
        embedder.encode(["ready"])
        return embedder
    except Exception:  # noqa: BLE001 - any backend failure must degrade to lexical, never crash
        return None


def index_evidence(evidence, embedder: Embedder, cache_path: Path = EMBEDDING_CACHE_PATH) -> int:
    """Embed every passage once into the persistent cache (the pre-index / ingestion step).

    ``evidence`` is any iterable of objects exposing ``evidence_id`` and ``text``. Only passages
    whose (id, model, version, checksum) are not already cached are embedded, so re-running after
    a corpus edit re-embeds just the changed passages. Returns the number newly embedded.
    """
    cache_path = Path(cache_path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(cache_path)) as cache, cache:
        cache.executescript(_CACHE_SCHEMA)
        pending: list[tuple[str, str, str]] = []
        for item in evidence:
            checksum = hashlib.sha256(item.text.encode()).hexdigest()
            cached = cache.execute(
                "SELECT 1 FROM embedding_cache WHERE evidence_id=? AND model_name=? "
                "AND model_version=? AND content_checksum=?",
                (item.evidence_id, embedder.name, embedder.version, checksum),
            ).fetchone()
            if cached is None:
                pending.append((item.evidence_id, item.text, checksum))
        if not pending:
            return 0
        vectors = embedder.encode([text for _id, text, _sum in pending])
        for (evidence_id, _text, checksum), vector in zip(pending, vectors, strict=True):
            cache.execute(
                "INSERT INTO embedding_cache(evidence_id, model_name, model_version, "
                "content_checksum, vector_json) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(evidence_id, model_name, model_version) DO UPDATE SET "
                "content_checksum=excluded.content_checksum, vector_json=excluded.vector_json, "
                "created_at=CURRENT_TIMESTAMP",
                (evidence_id, embedder.name, embedder.version, checksum, json.dumps(vector)),
            )
    return len(pending)


def preload_cached_vectors(
    connection: sqlite3.Connection, cache_path: Path = EMBEDDING_CACHE_PATH
) -> int:
    """Copy pre-indexed vectors from the persistent cache into an in-memory retrieval DB.

    Best-effort: if the cache file is absent nothing is loaded and retrieval embeds on demand.
    Only vectors for evidence present in ``connection`` are copied; query-time checksum matching
    still guards correctness, so a stale row simply misses and is re-embedded. Returns the number
    of rows loaded.
    """
    if not Path(cache_path).is_file():
        return 0
    evidence_ids = {row[0] for row in connection.execute("SELECT evidence_id FROM evidence")}
    if not evidence_ids:
        return 0
    with closing(sqlite3.connect(cache_path)) as cache:
        rows = cache.execute(
            "SELECT evidence_id, model_name, model_version, content_checksum, vector_json "
            "FROM embedding_cache"
        ).fetchall()
    loaded = 0
    for row in rows:
        if row[0] not in evidence_ids:
            continue
        connection.execute(
            "INSERT OR IGNORE INTO embedding_cache(evidence_id, model_name, model_version, "
            "content_checksum, vector_json) VALUES (?, ?, ?, ?, ?)",
            row,
        )
        loaded += 1
    return loaded


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
