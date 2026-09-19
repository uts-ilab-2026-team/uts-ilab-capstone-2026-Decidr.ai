"""Interpretable SQLite FTS5 lexical retrieval."""

from dataclasses import dataclass
import re
import sqlite3

from decidr.models import AtomicClaim

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.%-]*")
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "of",
    "on",
    "or",
    "the",
    "to",
}


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    evidence_id: str
    source_id: str
    locator: str
    text: str
    rank: int
    score: float
    matched_terms: tuple[str, ...]
    match_explanation: str


def _normalise_terms(
    values: list[str],
    synonyms: dict[str, list[str]] | None = None,
) -> list[str]:
    """Tokenise query values consistently for lexical retrieval."""
    terms: list[str] = []
    for value in values:
        for term in TOKEN_PATTERN.findall(value.casefold()):
            if term not in STOPWORDS and term not in terms:
                terms.append(term)
    for term in tuple(terms):
        for synonym in (synonyms or {}).get(term, []):
            normalised = synonym.casefold().strip()
            if normalised and normalised not in terms:
                terms.append(normalised)
    return terms


def claim_terms(claim: AtomicClaim, synonyms: dict[str, list[str]] | None = None) -> list[str]:
    """Build the lexical representation from structured claim fields."""
    return _normalise_terms(
        [
            claim.subject,
            claim.predicate,
            claim.object,
            claim.process or "",
            claim.scope or "",
            *claim.conditions,
        ],
        synonyms,
    )


def query_terms(query: str, synonyms: dict[str, list[str]] | None = None) -> list[str]:
    """Build a lexical representation directly from a free-text corpus query."""
    return _normalise_terms([query], synonyms)


def _lexical_search_terms(
    connection: sqlite3.Connection,
    terms: list[str],
    limit: int,
) -> list[RetrievalResult]:
    """Run whole-corpus FTS5 retrieval for already-normalised terms."""
    if not terms:
        return []

    query = " OR ".join(f'"{term.replace(chr(34), "")}"' for term in terms)
    rows = connection.execute(
        """
        SELECT f.evidence_id, e.source_id, e.locator, e.text_content, bm25(evidence_fts) score
        FROM evidence_fts f
        JOIN evidence e ON e.evidence_id = f.evidence_id
        WHERE evidence_fts MATCH ?
        ORDER BY score
        LIMIT ?
        """,
        (query, limit),
    ).fetchall()

    results = []
    for rank, row in enumerate(rows, start=1):
        text_lower = row[3].casefold()
        matched = tuple(term for term in terms if term in text_lower)
        results.append(
            RetrievalResult(
                evidence_id=row[0],
                source_id=row[1],
                locator=row[2],
                text=row[3],
                rank=rank,
                score=float(-row[4]),
                matched_terms=matched,
                match_explanation=f"FTS5 BM25 match on: {', '.join(matched)}",
            )
        )
    return results


def lexical_search(
    connection: sqlite3.Connection,
    claim: AtomicClaim,
    limit: int = 20,
    synonyms: dict[str, list[str]] | None = None,
) -> list[RetrievalResult]:
    """Rank whole-corpus evidence from a structured claim."""
    return _lexical_search_terms(
        connection,
        claim_terms(claim, synonyms),
        limit,
    )


def lexical_search_text(
    connection: sqlite3.Connection,
    query: str,
    limit: int = 20,
    synonyms: dict[str, list[str]] | None = None,
) -> list[RetrievalResult]:
    """Rank whole-corpus evidence directly from a free-text query."""
    return _lexical_search_terms(
        connection,
        query_terms(query, synonyms),
        limit,
    )
