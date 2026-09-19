"""Whole-corpus hybrid retrieval with provenance-aware diversification."""

from collections import Counter
from dataclasses import dataclass
from datetime import date
import json
import re
import sqlite3

from decidr.hybrid import reciprocal_rank_fusion
from decidr.retrieval import lexical_search_text
from decidr.semantic import (
    SemanticUnavailableError,
    SentenceTransformerEmbedder,
    semantic_search_text,
)


@dataclass(frozen=True, slots=True)
class CorpusResult:
    evidence_id: str
    source_id: str
    locator: str
    text: str
    rank: int
    hybrid_score: float
    lexical_rank: int | None
    semantic_rank: int | None
    source_type: str
    lifecycle_status: str
    version: str | None
    approval_status: str | None
    effective_start_date: str | None
    effective_end_date: str | None
    creation_date: str | None
    temporal_status: str
    duplicate_group: str | None
    independence_group: str
    provenance_sources: tuple[str, ...]
    missing_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CorpusSearchPackage:
    query: str
    results: tuple[CorpusResult, ...]
    candidate_count: int
    unique_sources: int
    independent_source_groups: int
    duplicate_results_collapsed: int
    source_type_counts: dict[str, int]
    semantic_status: str
    query_period_start: str | None
    query_period_end: str | None
    gap_signals: tuple[str, ...]



def parse_query_period(query: str) -> tuple[date | None, date | None]:
    """Infer simple explicit date constraints without guessing missing dates."""
    lower = query.casefold()

    match = re.search(
        r"\bbetween\s+(20\d{2})\s+(?:and|to)\s+(20\d{2})\b",
        lower,
    )
    if match:
        start_year, end_year = map(int, match.groups())
        return date(start_year, 1, 1), date(end_year, 12, 31)

    match = re.search(r"\bbefore\s+(20\d{2})\b", lower)
    if match:
        year = int(match.group(1))
        return None, date(year - 1, 12, 31)

    match = re.search(r"\bafter\s+(20\d{2})\b", lower)
    if match:
        year = int(match.group(1))
        return date(year + 1, 1, 1), None

    match = re.search(r"\b(?:in|during)\s+(20\d{2})\b", lower)
    if match:
        year = int(match.group(1))
        return date(year, 1, 1), date(year, 12, 31)

    match = re.search(
        r"\b(?:as of|as at|on)\s+(20\d{2}-\d{2}-\d{2})\b",
        lower,
    )
    if match:
        value = date.fromisoformat(match.group(1))
        return value, value

    return None, None


def _iso_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _temporal_status(
    source: dict,
    query_start: date | None,
    query_end: date | None,
) -> str:
    lifecycle = source.get("lifecycle_status", "unknown")

    if query_start is None and query_end is None:
        if lifecycle == "superseded":
            return "historical_or_stale"
        if lifecycle == "draft":
            return "draft"
        return "current_or_unspecified"

    source_start = _iso_date(source.get("effective_start_date"))
    source_end = _iso_date(source.get("effective_end_date"))

    if source_start or source_end:
        if query_end and source_start and source_start > query_end:
            return "outside_query_period"
        if query_start and source_end and source_end < query_start:
            return "outside_query_period"
        return "applicable_to_query_period"

    created = _iso_date(source.get("creation_date"))
    if created:
        if query_end and created > query_end:
            return "recorded_outside_query_period"
        if query_start and created < query_start:
            return "recorded_outside_query_period"
        return "recorded_in_query_period"

    return "temporal_scope_unknown"

def _source_metadata(connection: sqlite3.Connection) -> dict[str, dict]:
    rows = connection.execute(
        "SELECT source_id, payload_json FROM sources"
    ).fetchall()
    return {row[0]: json.loads(row[1]) for row in rows}



def _evidence_metadata(connection: sqlite3.Connection) -> dict[str, dict]:
    rows = connection.execute(
        "SELECT evidence_id, payload_json FROM evidence"
    ).fetchall()
    return {row[0]: json.loads(row[1]) for row in rows}


def _missing_fields(evidence: dict) -> tuple[str, ...]:
    structured = evidence.get("structured_metadata", {})
    record = structured.get("record")
    if not isinstance(record, dict):
        return ()

    return tuple(
        sorted(
            key
            for key, value in record.items()
            if value is None or (isinstance(value, str) and not value.strip())
        )
    )

def _evidence_group_key(item, source: dict) -> str:
    duplicate_group = source.get("duplicate_group")
    if duplicate_group:
        return f"{duplicate_group}|{item.locator}"
    return item.evidence_id



def _temporal_priority(status: str, has_query_period: bool) -> int:
    """Prefer temporally applicable evidence without discarding historical context."""
    if not has_query_period:
        return {
            "current_or_unspecified": 0,
            "draft": 1,
            "historical_or_stale": 2,
        }.get(status, 1)

    return {
        "applicable_to_query_period": 0,
        "recorded_in_query_period": 1,
        "temporal_scope_unknown": 2,
        "recorded_outside_query_period": 3,
        "outside_query_period": 4,
    }.get(status, 2)


def _gap_signals(
    results: list[CorpusResult],
    semantic_status: str,
    has_query_period: bool,
    independent_groups: int,
) -> tuple[str, ...]:
    """Describe retrieval limitations without making a credibility judgement."""
    signals: list[str] = []

    if not results:
        signals.append("no_evidence_retrieved")
        return tuple(signals)

    if semantic_status != "available":
        signals.append("semantic_retrieval_unavailable")

    if independent_groups <= 1:
        signals.append("limited_independent_source_coverage")

    if any(result.missing_fields for result in results):
        signals.append("structured_fields_missing")

    if has_query_period:
        statuses = {result.temporal_status for result in results}

        if "applicable_to_query_period" not in statuses:
            signals.append("no_explicitly_applicable_dated_source")

        if "temporal_scope_unknown" in statuses:
            signals.append("some_temporal_scope_unknown")

        if statuses <= {
            "outside_query_period",
            "recorded_outside_query_period",
            "temporal_scope_unknown",
        }:
            signals.append("temporal_evidence_gap")

    return tuple(signals)

def search_corpus(
    connection: sqlite3.Connection,
    query: str,
    limit: int = 10,
    candidate_limit: int = 30,
    semantic: bool = True,
    max_per_source: int = 2,
) -> CorpusSearchPackage:
    """Search the complete evidence corpus and return diversified evidence."""

    cleaned = query.strip()
    if not cleaned:
        return CorpusSearchPackage(
            query="",
            results=(),
            candidate_count=0,
            unique_sources=0,
            independent_source_groups=0,
            duplicate_results_collapsed=0,
            source_type_counts={},
            semantic_status="not_requested",
            query_period_start=None,
            query_period_end=None,
            gap_signals=("empty_query",),
        )

    candidate_limit = max(candidate_limit, limit)

    lexical = lexical_search_text(
        connection, cleaned, limit=candidate_limit
    )

    semantic_results = []
    semantic_status = "not_requested"

    if semantic:
        try:
            embedder = SentenceTransformerEmbedder()
            semantic_results = semantic_search_text(
                connection,
                cleaned,
                embedder,
                limit=candidate_limit,
            )
            semantic_status = "available"
        except SemanticUnavailableError as error:
            semantic_status = str(error)

    fused = reciprocal_rank_fusion(
        lexical,
        semantic_results,
        limit=candidate_limit,
    )

    sources = _source_metadata(connection)
    evidence_metadata = _evidence_metadata(connection)
    query_start, query_end = parse_query_period(cleaned)

    grouped: dict[str, list] = {}
    group_order: list[str] = []

    for item in fused:
        source = sources[item.source_id]
        key = _evidence_group_key(item, source)
        if key not in grouped:
            grouped[key] = []
            group_order.append(key)
        grouped[key].append(item)

    results = []
    source_counts: Counter[str] = Counter()
    duplicate_results_collapsed = 0

    has_query_period = query_start is not None or query_end is not None

    ordered_groups = sorted(
        group_order,
        key=lambda key: (
            _temporal_priority(
                _temporal_status(
                    sources[grouped[key][0].source_id],
                    query_start,
                    query_end,
                ),
                has_query_period,
            ),
            -grouped[key][0].combined_score,
        ),
    )

    for key in ordered_groups:
        items = grouped[key]
        representative = items[0]
        source = sources[representative.source_id]

        duplicate_results_collapsed += len(items) - 1

        source_group = source.get("duplicate_group") or representative.source_id
        if source_counts[source_group] >= max_per_source:
            continue

        provenance_sources = tuple(
            dict.fromkeys(item.source_id for item in items)
        )

        results.append(
            CorpusResult(
                evidence_id=representative.evidence_id,
                source_id=representative.source_id,
                locator=representative.locator,
                text=representative.text,
                rank=len(results) + 1,
                hybrid_score=representative.combined_score,
                lexical_rank=representative.lexical_rank,
                semantic_rank=representative.semantic_rank,
                source_type=source.get("source_type", "unknown"),
                lifecycle_status=source.get("lifecycle_status", "unknown"),
                version=source.get("version"),
                approval_status=source.get("approval_status"),
                effective_start_date=source.get("effective_start_date"),
                effective_end_date=source.get("effective_end_date"),
                creation_date=source.get("creation_date"),
                temporal_status=_temporal_status(
                    source,
                    query_start,
                    query_end,
                ),
                duplicate_group=source.get("duplicate_group"),
                independence_group=source_group,
                provenance_sources=provenance_sources,
                missing_fields=_missing_fields(
                    evidence_metadata.get(representative.evidence_id, {})
                ),
            )
        )

        source_counts[source_group] += 1

        if len(results) >= limit:
            break

    all_sources = {
        source_id
        for result in results
        for source_id in result.provenance_sources
    }

    source_types = Counter(result.source_type for result in results)

    gaps = _gap_signals(
        results,
        semantic_status,
        has_query_period,
        len(source_counts),
    )

    return CorpusSearchPackage(
        query=cleaned,
        results=tuple(results),
        candidate_count=len(fused),
        unique_sources=len(all_sources),
        independent_source_groups=len(source_counts),
        duplicate_results_collapsed=duplicate_results_collapsed,
        source_type_counts=dict(sorted(source_types.items())),
        semantic_status=semantic_status,
        query_period_start=query_start.isoformat() if query_start else None,
        query_period_end=query_end.isoformat() if query_end else None,
        gap_signals=gaps,
    )
