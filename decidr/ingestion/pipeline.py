"""Orchestrate a full ingestion run: scan releases, extract evidence, optionally persist."""

from collections import defaultdict
from contextlib import closing
import csv
from datetime import UTC, datetime
from pathlib import Path

from decidr.ingestion.deduplication import (
    _apply_duplicate_and_version_links,
    _apply_near_duplicate_signals,
)
from decidr.ingestion.extractors import extract_csv, extract_markdown
from decidr.ingestion.helpers import (
    SUPPORTED_SUFFIXES,
    IngestionResult,
    code_version,
    dataset_fingerprint,
)
from decidr.ingestion.source_builder import build_source
from decidr.retrieval_models import Evidence
from decidr.retrieval_store import (
    connect,
    initialise_database,
    replace_source_evidence,
    upsert_source,
)


def ingest(releases: dict[str, Path], database_path: Path | None = None) -> IngestionResult:
    """Scan configured releases, extract supported evidence, and optionally persist it."""
    started = datetime.now(UTC).isoformat()
    result = IngestionResult(started_at=started)
    source_paths: dict[str, Path] = {}
    for release, root in sorted(releases.items()):
        if not root.is_dir():
            result.warnings.append(f"Missing configured release directory: {release}={root}")
            continue
        for path in sorted(
            item
            for item in root.rglob("*")
            if item.is_file() and not item.name.casefold().endswith(":zone.identifier")
        ):
            source = build_source(path, root, release)
            if path.suffix.casefold() not in SUPPORTED_SUFFIXES:
                source.ingestion_status = "excluded"
                source.exclusion_reason = f"unsupported format: {path.suffix or '[none]'}"
            result.sources.append(source)
            source_paths[source.source_id] = path
    _apply_duplicate_and_version_links(result.sources)
    _apply_near_duplicate_signals(result.sources, source_paths)
    for source in result.sources:
        if source.ingestion_status == "excluded":
            continue
        path = source_paths[source.source_id]
        try:
            units = (
                extract_markdown(source, path)
                if path.suffix.casefold() == ".md"
                else extract_csv(source, path)
            )
            result.evidence.extend(units)
            source.ingestion_status = "ingested"
        except (OSError, UnicodeError, csv.Error, ValueError) as error:
            source.ingestion_status = "failed"
            source.metadata_notes = f"{source.metadata_notes}; extraction_error={error}"
            result.warnings.append(f"Failed {source.source_id}: {error}")
    result.dataset_fingerprint = dataset_fingerprint(result.sources)
    result.completed_at = datetime.now(UTC).isoformat()
    result.code_version = code_version(Path(__file__).resolve().parents[2])
    if database_path is not None:
        # Do not publish a partial scan or replace evidence after extraction failure.
        if result.warnings:
            raise ValueError(
                "Ingestion was incomplete; retrieval index was not updated: "
                + "; ".join(result.warnings)
            )
        source_ids = [source.source_id for source in result.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("Duplicate source IDs; retrieval index was not updated")
        initialise_database(database_path)
        evidence_by_source: dict[str, list[Evidence]] = defaultdict(list)
        for item in result.evidence:
            evidence_by_source[item.source_id].append(item)
        with closing(connect(database_path)) as connection, connection:
            for source in result.sources:
                upsert_source(connection, source)
                replace_source_evidence(
                    connection,
                    source.source_id,
                    evidence_by_source[source.source_id],
                )
    return result
