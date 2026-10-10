"""Source date meanings must remain separate during ingestion."""

from datetime import date

from decidr.ingestion import build_source
from decidr.retrieval_models import Source


def source_from_header(tmp_path, header):
    directory = tmp_path / "03_process_docs"
    directory.mkdir()
    path = directory / "example.md"
    path.write_text(
        "# Example procedure\n\n"
        + header
        + "\n\n## Purpose\n\nExample content.\n",
        encoding="utf-8",
    )
    return build_source(path, tmp_path, "development")


def test_update_date_does_not_supply_creation_or_effective_date(tmp_path):
    source = source_from_header(
        tmp_path, "- **Last updated:** 2024-04-12"
    )
    assert source.last_updated_date == date(2024, 4, 12)
    assert source.creation_date is None
    assert source.effective_start_date is None
    assert source.effective_end_date is None
    assert source.metadata_provenance["last_updated"] == (
        "direct:markdown_metadata:last updated"
    )


def test_superseded_date_does_not_invent_effective_end(tmp_path):
    source = source_from_header(
        tmp_path,
        "- **Effective date:** 2022-01-01\n"
        "- **Superseded date:** 2024-04-12",
    )
    assert source.effective_start_date == date(2022, 1, 1)
    assert source.superseded_date == date(2024, 4, 12)
    assert source.effective_end_date is None


def test_explicit_dates_remain_distinct_and_survive_serialisation(tmp_path):
    source = source_from_header(
        tmp_path,
        "- **Date:** 2022-01-01\n"
        "- **Last updated:** 2023-02-02\n"
        "- **Effective date:** 2022-03-03\n"
        "- **Effective end date:** 2024-04-11\n"
        "- **Superseded date:** 2024-04-12",
    )
    restored = Source.model_validate_json(source.model_dump_json())
    assert restored.creation_date == date(2022, 1, 1)
    assert restored.last_updated_date == date(2023, 2, 2)
    assert restored.effective_start_date == date(2022, 3, 3)
    assert restored.effective_end_date == date(2024, 4, 11)
    assert restored.superseded_date == date(2024, 4, 12)
