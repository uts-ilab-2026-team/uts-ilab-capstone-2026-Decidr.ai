"""Read-only, release-aware ingestion for the Northfield corpus."""

from decidr.ingestion.extractors import extract_csv, extract_markdown
from decidr.ingestion.helpers import IngestionResult, _related_source_codes
from decidr.ingestion.pipeline import ingest
from decidr.ingestion.source_builder import build_source

__all__ = [
    "IngestionResult",
    "_related_source_codes",
    "build_source",
    "extract_csv",
    "extract_markdown",
    "ingest",
]
