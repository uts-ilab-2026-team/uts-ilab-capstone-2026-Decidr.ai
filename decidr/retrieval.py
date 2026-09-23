"""Interpretable SQLite FTS5 lexical retrieval."""

from dataclasses import dataclass
import json
import re
import sqlite3

from decidr.corpus import eligible_modelling_evidence
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


@dataclass(frozen=True, slots=True)
class SearchQuery:
    """Neutral retrieval input; it is search text, not a factual proposition."""

    text: str

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("Search text must not be empty")


def claim_terms(claim: AtomicClaim, synonyms: dict[str, list[str]] | None = None) -> list[str]:
    """Build the shared lexical representation from structured claim fields."""
    values = [
        claim.subject,
        claim.predicate,
        claim.object,
        claim.process or "",
        claim.scope or "",
        *claim.conditions,
    ]
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


def text_terms(query: SearchQuery, synonyms: dict[str, list[str]] | None = None) -> list[str]:
    """Build terms directly from employee search text without creating a claim."""
    terms: list[str] = []
    for term in TOKEN_PATTERN.findall(query.text.casefold()):
        if term not in STOPWORDS and term not in terms:
            terms.append(term)
    for term in tuple(terms):
        for synonym in (synonyms or {}).get(term, []):
            normalised = synonym.casefold().strip()
            if normalised and normalised not in terms:
                terms.append(normalised)
    return terms


def lexical_text_search(
    connection: sqlite3.Connection,
    query: SearchQuery,
    limit: int = 20,
    synonyms: dict[str, list[str]] | None = None,
) -> list[RetrievalResult]:
    """Search raw text and enforce modelling eligibility from ingested metadata."""
    if limit < 1:
        raise ValueError("Retrieval limit must be positive")
    terms = text_terms(query, synonyms)
    if not terms:
        return []
    fts_query = " OR ".join(f'"{term.replace(chr(34), "")}"' for term in terms)
    rows = connection.execute(
        """
        SELECT f.evidence_id, e.source_id, e.locator, e.text_content,
               bm25(evidence_fts) score, e.payload_json, s.payload_json,
               s.ingestion_status
        FROM evidence_fts f
        JOIN evidence e ON e.evidence_id = f.evidence_id
        JOIN sources s ON s.source_id = e.source_id
        WHERE evidence_fts MATCH ?
        ORDER BY score, f.evidence_id
        """,
        (fts_query,),
    ).fetchall()
    results: list[RetrievalResult] = []
    for row in rows:
        if not eligible_modelling_evidence(json.loads(row[6]), json.loads(row[5]), row[7]):
            continue
        text_lower = row[3].casefold()
        matched = tuple(term for term in terms if term in text_lower)
        results.append(
            RetrievalResult(
                evidence_id=row[0],
                source_id=row[1],
                locator=row[2],
                text=row[3],
                rank=len(results) + 1,
                score=float(-row[4]),
                matched_terms=matched,
                match_explanation=f"FTS5 BM25 match on: {', '.join(matched)}",
            )
        )
        if len(results) == limit:
            break
    return results


def lexical_search(
    connection: sqlite3.Connection,
    claim: AtomicClaim,
    limit: int = 20,
    synonyms: dict[str, list[str]] | None = None,
) -> list[RetrievalResult]:
    """Rank evidence with BM25 and state exactly which query terms matched."""
    terms = claim_terms(claim, synonyms)
    if not terms:
        return []
    return lexical_text_search(connection, SearchQuery(" ".join(terms)), limit=limit)
