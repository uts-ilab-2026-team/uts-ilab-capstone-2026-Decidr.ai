"""Source references preserve content and remain stable after reordering."""

from collections import Counter
import csv
from hashlib import sha256

import pytest

from decidr.graph.sources import build_source_catalogue


@pytest.fixture
def dataset(tmp_path):
    (tmp_path / "notes.md").write_text(
        "# Notes α\n\n## THREAD-01\nFirst statement.\n\n"
        "## THREAD-02\nA different statement.\n",
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text("Dataset instructions.", encoding="utf-8")
    (tmp_path / "events.csv").write_text(
        'event_id,notes,approval\n'
        'EV-02,"Quoted, text",\n'
        'EV-01,"First line\nSecond line α",\n',
        encoding="utf-8-sig",
    )
    return tmp_path


def catalogue(root):
    return build_source_catalogue(
        root,
        csv_id_columns={"events.csv": "event_id"},
        exclude_paths=("README.md",),
    )


def test_preserves_complete_sources_and_leaves_files_unchanged(dataset):
    original = {path.name: path.read_bytes() for path in dataset.iterdir()}
    records = catalogue(dataset)

    assert Counter(item.kind for item in records) == {"markdown": 1, "csv_record": 2}
    assert len({item.source_id for item in records}) == 3
    assert {item.source_path for item in records} == {"notes.md", "events.csv"}

    markdown = next(item for item in records if item.kind == "markdown")
    assert markdown.content == (dataset / "notes.md").read_text(encoding="utf-8")
    assert markdown.record_key is None
    assert markdown.record_id is None

    rows = {item.record_id: item for item in records if item.kind == "csv_record"}
    assert rows["EV-01"].content == {
        "event_id": "EV-01",
        "notes": "First line\nSecond line α",
        "approval": "",
    }
    assert rows["EV-02"].content["notes"] == "Quoted, text"
    for item in records:
        assert item.source_sha256 == sha256(original[item.source_path]).hexdigest()

    assert original == {path.name: path.read_bytes() for path in dataset.iterdir()}


def test_csv_record_identity_survives_row_reordering(dataset):
    before = catalogue(dataset)
    path = dataset / "events.csv"
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        csv.writer(handle).writerows([rows[0], *reversed(rows[1:])])
    after = catalogue(dataset)

    assert [item.source_id for item in before] == [item.source_id for item in after]
    assert [item.content for item in before] == [item.content for item in after]
    old = next(item for item in before if item.record_id == "EV-01")
    new = next(item for item in after if item.record_id == "EV-01")
    assert old.source_sha256 != new.source_sha256


def test_content_change_updates_hash_but_preserves_location_id(dataset):
    before = next(item for item in catalogue(dataset) if item.kind == "markdown")
    (dataset / "notes.md").write_text("# Revised notes\n", encoding="utf-8")
    after = next(item for item in catalogue(dataset) if item.kind == "markdown")

    assert before.source_id == after.source_id
    assert before.source_sha256 != after.source_sha256
    assert before.content != after.content


def test_exported_row_does_not_mutate_catalogue_record(dataset):
    record = next(item for item in catalogue(dataset) if item.record_id == "EV-01")
    exported = record.model_dump()
    exported["content"]["notes"] = "Changed outside the catalogue"

    assert record.content["notes"] == "First line\nSecond line α"


def test_equal_record_keys_in_different_files_have_distinct_source_ids(dataset):
    (dataset / "other.csv").write_text(
        "event_id,notes\nEV-01,Other source\n", encoding="utf-8"
    )
    records = build_source_catalogue(
        dataset,
        csv_id_columns={"events.csv": "event_id", "other.csv": "event_id"},
        exclude_paths=("README.md",),
    )
    matching = [item for item in records if item.record_id == "EV-01"]

    assert len(matching) == 2
    assert len({item.source_id for item in matching}) == 2


@pytest.mark.parametrize(
    "content",
    [
        "event_id,notes\nEV-01,A\nEV-01,B\n",
        "event_id,notes\n,A\n",
        "other_id,notes\nEV-01,A\n",
        "event_id,event_id\nEV-01,EV-02\n",
        "event_id,notes\nEV-01\n",
        "event_id,notes\nEV-01,A,extra\n",
        "event_id,\nEV-01,A\n",
        'event_id,notes\nEV-01,"Unclosed field\n',
    ],
)
def test_rejects_ambiguous_or_malformed_csv_records(dataset, content):
    (dataset / "events.csv").write_text(content, encoding="utf-8")

    with pytest.raises((ValueError, csv.Error)):
        catalogue(dataset)


def test_requires_explicit_csv_id_configuration(dataset):
    with pytest.raises(ValueError, match="unconfigured"):
        build_source_catalogue(dataset, csv_id_columns={})


def test_rejects_configuration_for_a_missing_csv(dataset):
    with pytest.raises(ValueError, match="not found"):
        build_source_catalogue(
            dataset,
            csv_id_columns={"events.csv": "event_id", "missing.csv": "id"},
        )


@pytest.mark.parametrize("missing", [True, False])
def test_missing_or_empty_dataset_is_reported(tmp_path, missing):
    root = tmp_path / "missing" if missing else tmp_path

    with pytest.raises(ValueError):
        build_source_catalogue(root, csv_id_columns={})


def test_unsupported_files_are_reported_instead_of_silently_skipped(dataset):
    (dataset / "unknown.bin").write_bytes(b"Unknown source format")

    with pytest.raises(ValueError, match="unsupported source format"):
        catalogue(dataset)
