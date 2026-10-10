"""Catalogue supplied sources without extracting claims or assigning verdicts."""

from dataclasses import asdict, dataclass
import csv
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True, slots=True)
class SourceRecord:
    source_id: str
    source_path: str
    source_sha256: str
    kind: str
    content: str | dict[str, str]
    record_key: str | None = None
    record_id: str | None = None

    def model_dump(self) -> dict[str, object]:
        return asdict(self)


def _source_id(path: str, key: str | None, value: str | None) -> str:
    locator = json.dumps([path, key, value], ensure_ascii=False)
    return "source:" + sha256(locator.encode("utf-8")).hexdigest()


def build_source_catalogue(
    root: Path,
    *,
    csv_id_columns: Mapping[str, str],
    exclude_paths: tuple[str, ...] = (),
) -> tuple[SourceRecord, ...]:
    """Read Markdown files and CSV records beneath one dataset root.

    Paths and CSV configuration keys are relative to that root. Markdown is
    retained whole, including communication thread headings. CSV identity uses
    an explicitly configured unique column, never a row position. File hashes
    identify the supplied version; IDs identify locations within this dataset.
    A source location does not establish that its content supports a claim.
    """
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"Dataset directory does not exist: {root}")
    paths = [
        path for path in sorted(root.rglob("*"))
        if path.is_file()
        and not any(part.startswith(".") for part in path.relative_to(root).parts)
        and path.relative_to(root).as_posix() not in exclude_paths
    ]
    if not paths:
        raise ValueError("The dataset contains no source files")
    csv_paths = {
        path.relative_to(root).as_posix() for path in paths
        if path.suffix.lower() == ".csv"
    }
    if csv_paths != set(csv_id_columns):
        raise ValueError(
            "CSV ID configuration must match the dataset CSV files; "
            f"unconfigured={sorted(csv_paths - set(csv_id_columns))}, "
            f"not found={sorted(set(csv_id_columns) - csv_paths)}"
        )
    records = []
    for path in paths:
        relative = path.relative_to(root).as_posix()
        if not path.resolve().is_relative_to(root):
            raise ValueError(f"{relative}: source resolves outside the dataset directory")
        kind = path.suffix.lower()
        if kind not in {".md", ".csv"}:
            raise ValueError(f"{relative}: unsupported source format")
        raw = path.read_bytes()
        digest = sha256(raw).hexdigest()
        text = raw.decode("utf-8-sig")
        if kind == ".md":
            records.append(SourceRecord(
                source_id=_source_id(relative, None, None),
                source_path=relative,
                source_sha256=digest,
                kind="markdown",
                content=text,
            ))
            continue
        key = csv_id_columns[relative]
        reader = csv.DictReader(StringIO(text, newline=""), strict=True)
        columns = reader.fieldnames
        if (
            not columns
            or any(not name.strip() for name in columns)
            or len(set(columns)) != len(columns)
            or not isinstance(key, str)
            or not key.strip()
            or key not in columns
        ):
            raise ValueError(f"{relative}: invalid CSV header or ID column {key!r}")
        seen = set()
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"{relative}: CSV record has an unexpected field count")
            identifier = row[key]
            if not identifier.strip() or identifier in seen:
                raise ValueError(f"{relative}: empty or duplicate {key}: {identifier!r}")
            seen.add(identifier)
            records.append(SourceRecord(
                source_id=_source_id(relative, key, identifier),
                source_path=relative,
                source_sha256=digest,
                kind="csv_record",
                content=dict(row),
                record_key=key,
                record_id=identifier,
            ))
    return tuple(sorted(records, key=lambda item: (item.source_path, item.record_id or "")))
