"""Read-only, release-aware ingestion for the Northfield corpus."""

from decidr.corpus.ingest.extractors import extract_csv, extract_markdown
from decidr.corpus.ingest.helpers import IngestionResult, _related_source_codes
from decidr.corpus.ingest.pipeline import ingest
from decidr.corpus.ingest.source_builder import build_source

__all__ = [
    "IngestionResult",
    "_related_source_codes",
    "build_source",
    "extract_csv",
    "extract_markdown",
    "ingest",
]
