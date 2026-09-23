"""Read-only, release-aware ingestion for the Northfield corpus."""

from collections import Counter, defaultdict
from collections.abc import Iterable
import csv
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import tempfile

from decidr.corpus import INGESTION_VERSION, RELEASE_PURPOSES, ledger_fingerprint
from decidr.database import connect, initialise_database, upsert_source, upsert_source_evidence
from decidr.models import Evidence, Source
from decidr.source_metadata import METADATA_VERSION, approval_lifecycle, header_date, read_header

SUPPORTED_SUFFIXES = {".md", ".csv"}
TECHNICAL_NAMES = {"README.md"}
ANNOTATION_NAMES = {"labelled_claims_sample.csv"}
HEADING_PATTERN = re.compile(r"^(?P<level>#{1,6})\s+(?P<title>.+?)\s*$")
DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")
SOURCE_CODE_PATTERN = re.compile(r"\b(?:POL|PROC|INT|MTG)-\d+\b")


@dataclass(slots=True)
class IngestionResult:
    """Complete, serialisable result of one ingestion run."""

    sources: list[Source] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    dataset_fingerprint: str = ""
    started_at: str = ""
    completed_at: str = ""
    code_version: str = "unknown"
    configuration_version: str = INGESTION_VERSION
    available_releases: list[dict] = field(default_factory=list)

    def summary(self) -> dict[str, object]:
        statuses = Counter(source.ingestion_status for source in self.sources)
        types = Counter(source.source_type for source in self.sources)
        return {
            "dataset_fingerprint": self.dataset_fingerprint,
            "available_releases": self.available_releases,
            "active_releases": ["phase2_model_development"],
            "source_count": len(self.sources),
            "evidence_count": len(self.evidence),
            "status_counts": dict(sorted(statuses.items())),
            "source_type_counts": dict(sorted(types.items())),
            "warning_count": len(self.warnings),
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "code_version": self.code_version,
            "configuration_version": self.configuration_version,
        }


def sha256_file(path: Path) -> str:
    """Return the SHA-256 checksum of a file without modifying it."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def code_version(project_root: Path) -> str:
    """Return the Git commit when available, otherwise an explicit unknown marker."""
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project_root,
        capture_output=True,
        check=False,
        text=True,
    )
    return completed.stdout.strip() if completed.returncode == 0 else "unknown:not-a-git-worktree"


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def _source_type(relative_path: Path) -> str:
    directory = relative_path.parts[0] if len(relative_path.parts) > 1 else "root"
    return {
        "00_overview": "organisational_information",
        "02_policies": "policy",
        "03_process_docs": "procedure",
        "04_interviews": "interview",
        "05_meetings": "meeting",
        "06_communications": "internal_communication",
        "07_crm": "crm_records",
        "08_project_tasks": "project_tasks",
        "09_audit_log": "audit_events",
    }.get(directory, "technical" if relative_path.name in TECHNICAL_NAMES else "annotation")


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    match = DATE_PATTERN.search(value)
    if not match:
        return None
    return date.fromisoformat(match.group())


def _source_code(path: Path, title: str) -> str:
    match = SOURCE_CODE_PATTERN.search(f"{path.stem} {title}")
    return match.group() if match else _slug(path.stem)


def build_source(path: Path, root: Path, release: str) -> Source:
    """Register a file and label every inferred metadata field."""
    relative = path.relative_to(root)
    checksum = sha256_file(path)
    source_type = _source_type(relative)
    title, metadata, header_evidence, conflicts = (
        read_header(path) if path.suffix.casefold() == ".md" else (path.stem, {}, [], [])
    )
    code = _source_code(path, title)
    excluded = path.name in TECHNICAL_NAMES or path.name in ANNOTATION_NAMES
    is_superseded = "superseded" in {part.casefold() for part in relative.parts}
    owner = metadata.get("document owner") or metadata.get("owner")
    role_function = metadata.get("role / function")
    author = owner or (role_function.split(",", 1)[0] if role_function else None)
    creation_date = header_date(metadata, "date", conflicts) or header_date(
        metadata, "interview date", conflicts
    )
    last_updated = header_date(metadata, "last updated", conflicts)
    effective_start = header_date(metadata, "effective date", conflicts)
    superseded_date = header_date(metadata, "superseded date", conflicts)
    approval = metadata.get("approval status")
    lifecycle, clauses, approval_conflicts = approval_lifecycle(approval, code)
    conflicts.extend(approval_conflicts)
    for entry in header_evidence:
        entry["source_id"] = f"{release}:{code}"
        if entry["key"] == "approval status":
            entry["clauses"] = clauses
    if is_superseded or superseded_date:
        explicitly_current = any(
            clause["scope"] == "own_document"
            and re.search(r"\bcurrent\b", clause["quote"], re.IGNORECASE)
            for clause in clauses
        )
        if lifecycle in {"draft", "unknown", "withdrawn"} or explicitly_current:
            conflicts.append(
                {
                    "field": "lifecycle_status",
                    "values": [lifecycle, "superseded"],
                    "reason": "Supersession conflicts with own approval status.",
                }
            )
            lifecycle = "unknown"
        else:
            lifecycle = "superseded"
    if any(c["field"] == "approval_status" for c in conflicts):
        lifecycle = "unknown"
    lifecycle = lifecycle or "current"
    if effective_start and superseded_date and effective_start > superseded_date:
        conflicts.append(
            {
                "field": "supersession",
                "values": [effective_start.isoformat(), superseded_date.isoformat()],
                "reason": "Superseded date precedes effective start; dates retained unresolved.",
            }
        )
    provenance = {
        "title": "direct:markdown_h1" if path.suffix.casefold() == ".md" else "inferred:filename",
        "source_type": "inferred:directory",
        "release": "direct:configured_root",
        "checksum": "calculated:sha256",
        "lifecycle_status": "derived:document_scoped_approval_and_supersession"
        if approval or is_superseded or superseded_date
        else "inferred:active_directory_default",
    }
    for key in metadata:
        if key in metadata:
            provenance[key.replace(" ", "_")] = f"direct:markdown_metadata:{key}"
    for field_name, header_key in (
        ("creation_date", "date" if "date" in metadata else "interview date"),
        ("last_updated_date", "last updated"),
        ("effective_start_date", "effective date"),
        ("superseded_date", "superseded date"),
    ):
        if header_key in metadata:
            provenance[field_name] = f"direct:markdown_metadata:{header_key}"
    notes = [f"release={release}", f"relative_path={relative.as_posix()}"]
    supersedes = metadata.get("supersedes")
    if supersedes:
        notes.append(f"declared_supersedes={supersedes}")
    return Source(
        source_id=f"{release}:{code}",
        title=title,
        original_file_path=str(path.resolve()),
        source_type=source_type,
        organisational_function=(
            role_function.split(",", 1)[1].strip()
            if role_function and "," in role_function
            else None
        ),
        responsible_person_or_role=owner or role_function,
        author_or_system=author,
        creation_date=creation_date,
        effective_start_date=effective_start,
        superseded_date=superseded_date,
        last_updated_date=last_updated,
        version=metadata.get("version"),
        approval_status=approval,
        formality_level="formal" if source_type in {"policy", "procedure"} else "operational",
        lifecycle_status=lifecycle,
        ingestion_status="excluded" if excluded else "registered",
        exclusion_reason=(
            "release documentation; not organisational evidence"
            if path.name in TECHNICAL_NAMES
            else "illustrative annotation; not organisational evidence or hidden ground truth"
            if path.name in ANNOTATION_NAMES
            else None
        ),
        checksum=checksum,
        metadata_notes="; ".join(notes),
        metadata_provenance=provenance,
        metadata_version=METADATA_VERSION,
        metadata_evidence=header_evidence,
        metadata_conflicts=conflicts,
    )


def _evidence_id(source_id: str, locator: str) -> str:
    digest = hashlib.sha256(f"{source_id}\0{locator}".encode()).hexdigest()[:16]
    return f"EV-{digest}"


def extract_markdown(source: Source, path: Path) -> list[Evidence]:
    """Extract paragraphs/list/table rows with heading-based stable locators."""
    units: list[Evidence] = []
    headings: list[str] = []
    section_counts: Counter[str] = Counter()
    buffer: list[str] = []

    def emit() -> None:
        nonlocal buffer
        text = "\n".join(buffer).strip()
        buffer = []
        if not text:
            return
        section = " > ".join(headings) if headings else "document"
        section_counts[section] += 1
        locator = f"heading:{section}#block:{section_counts[section]:03d}"
        units.append(
            Evidence(
                evidence_id=_evidence_id(source.source_id, locator),
                source_id=source.source_id,
                locator=locator,
                text=text,
                source_type=source.source_type,
                section=section,
                heading=headings[-1] if headings else None,
                paragraph=section_counts[section],
                version=source.version,
                extraction_method="markdown_heading_blocks_v1",
                structured_metadata={"release": source.source_id.split(":", 1)[0]},
            )
        )

    in_fence = False
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.rstrip()
        if line.startswith("```"):
            in_fence = not in_fence
            buffer.append(line)
            continue
        heading = None if in_fence else HEADING_PATTERN.match(line)
        if heading:
            emit()
            level = len(heading.group("level"))
            headings[:] = headings[: level - 1]
            headings.append(heading.group("title").strip())
        elif not line.strip():
            emit()
        else:
            buffer.append(line)
    emit()
    return units


def extract_csv(source: Source, path: Path) -> list[Evidence]:
    """Extract one faithful evidence unit per CSV record."""
    units: list[Evidence] = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("CSV has no header")
        identifier_field = reader.fieldnames[0]
        for row_number, row in enumerate(reader, start=2):
            row_identifier = (row.get(identifier_field) or f"row-{row_number}").strip()
            locator = f"csv:row:{row_number};{identifier_field}:{row_identifier}"
            faithful = json.dumps(row, ensure_ascii=False, sort_keys=True)
            relevant_dates = [_parse_date(value) for value in row.values()]
            relevant_dates = [value for value in relevant_dates if value]
            units.append(
                Evidence(
                    evidence_id=_evidence_id(source.source_id, locator),
                    source_id=source.source_id,
                    locator=locator,
                    text=faithful,
                    source_type=source.source_type,
                    row_identifier=row_identifier,
                    relevant_start_date=min(relevant_dates) if relevant_dates else None,
                    relevant_end_date=max(relevant_dates) if relevant_dates else None,
                    extraction_method="csv_dict_row_v1",
                    structured_metadata={"row_number": row_number, "record": row},
                )
            )
    return units


def _apply_duplicate_and_version_links(sources: list[Source]) -> None:
    by_checksum: dict[str, list[Source]] = defaultdict(list)
    by_code: dict[str, list[Source]] = defaultdict(list)
    for source in sources:
        by_checksum[source.checksum].append(source)
        by_code[source.source_id.split(":", 1)[1]].append(source)
    for checksum, matches in by_checksum.items():
        if len(matches) > 1:
            group = f"sha256:{checksum}"
            for source in matches:
                source.duplicate_group = group
    links: set[tuple[str, str]] = set()
    by_id = {source.source_id: source for source in sources}
    for source in sources:
        for entry in source.metadata_evidence:
            if entry["key"] not in {"supersedes", "superseded by"}:
                continue
            codes = set(entry["references"])
            candidates = [
                item
                for code in codes
                for item in by_code.get(code, [])
                if item.source_id.split(":", 1)[0] == source.source_id.split(":", 1)[0]
                and item.source_id != source.source_id
            ]
            if len(codes) != 1 or len(candidates) != 1:
                entry["resolution"] = "unresolved_document_identity"
                continue
            other = candidates[0]
            entry["resolution"] = other.source_id
            links.add(
                (source.source_id, other.source_id)
                if entry["key"] == "supersedes"
                else (other.source_id, source.source_id)
            )
    for sid, source in by_id.items():
        for field_name, candidates in (
            ("predecessor_source_id", sorted(b for a, b in links if a == sid)),
            ("successor_source_id", sorted(a for a, b in links if b == sid)),
        ):
            if len(candidates) == 1:
                setattr(source, field_name, candidates[0])
            elif candidates:
                source.metadata_conflicts.append(
                    {
                        "field": "supersession",
                        "values": candidates,
                        "reason": f"Conflicting {field_name} declarations; no link selected.",
                    }
                )


def _normalised_shingles(path: Path, width: int = 5) -> set[tuple[str, ...]]:
    text = path.read_text(encoding="utf-8-sig").casefold()
    tokens = re.findall(r"[a-z0-9]+", text)
    return {tuple(tokens[index : index + width]) for index in range(len(tokens) - width + 1)}


def _apply_near_duplicate_signals(
    sources: list[Source], source_paths: dict[str, Path], threshold: float = 0.92
) -> None:
    """Flag highly similar documents for review without asserting dependence."""
    candidates = [
        source
        for source in sources
        if source.ingestion_status != "excluded"
        and source_paths[source.source_id].suffix.casefold() == ".md"
    ]
    shingles = {
        source.source_id: _normalised_shingles(source_paths[source.source_id])
        for source in candidates
    }
    for index, left in enumerate(candidates):
        for right in candidates[index + 1 :]:
            if left.checksum == right.checksum or left.source_type != right.source_type:
                continue
            left_set = shingles[left.source_id]
            right_set = shingles[right.source_id]
            if not left_set or not right_set:
                continue
            similarity = len(left_set & right_set) / len(left_set | right_set)
            if similarity >= threshold:
                for source, other in ((left, right), (right, left)):
                    signal = f"near_duplicate_candidate={other.source_id}:{similarity:.3f}"
                    source.metadata_notes = f"{source.metadata_notes}; {signal}"


def dataset_fingerprint(sources: Iterable[Source]) -> str:
    """Hash sorted release-relative identities and checksums."""
    digest = hashlib.sha256()
    for source in sorted(sources, key=lambda item: item.source_id):
        digest.update(f"{source.source_id}\0{source.checksum}\n".encode())
    return digest.hexdigest()


def ingest(releases: dict[str, Path], database_path: Path | None = None) -> IngestionResult:
    """Scan configured releases, extract supported evidence, and optionally persist it."""
    started = datetime.now(UTC).isoformat()
    result = IngestionResult(started_at=started)
    source_paths: dict[str, Path] = {}
    for release, root in sorted(releases.items()):
        purpose = RELEASE_PURPOSES.get(
            release,
            {"directory": root.name, "purpose": "unconfigured; not modelling", "active": False},
        )
        result.available_releases.append(
            {
                "release": release,
                **purpose,
                "available": root.is_dir(),
                "file_count": sum(p.is_file() for p in root.rglob("*")) if root.is_dir() else 0,
            }
        )
        if not root.is_dir():
            result.warnings.append(f"Missing configured release directory: {release}={root}")
            continue
        if not purpose["active"]:
            continue
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
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
    result.code_version = code_version(Path(__file__).resolve().parents[1])
    if database_path:
        if not result.sources or any(
            source.ingestion_status == "failed" for source in result.sources
        ):
            raise ValueError(
                "Active Phase 2 corpus is missing or extraction failed; existing ledger preserved."
            )
        rebuild_ledger(result, database_path)
    return result


def rebuild_ledger(result: IngestionResult, database_path: Path) -> None:
    """Build fresh indexes and atomically install them; archive the previous ledger."""
    database_path.parent.mkdir(parents=True, exist_ok=True)
    if database_path.exists():
        with connect(database_path) as existing:
            try:
                unchanged = ledger_fingerprint(existing) == result.dataset_fingerprint
            except (ValueError, sqlite3.OperationalError):
                unchanged = False
            if unchanged:
                # Re-registration of an unchanged active corpus must preserve reviews.
                return
    descriptor, temporary = tempfile.mkstemp(
        prefix="modelling-", suffix=".sqlite3", dir=database_path.parent
    )
    os.close(descriptor)
    fresh = Path(temporary)
    try:
        initialise_database(fresh)
        evidence_by_source: dict[str, list[Evidence]] = defaultdict(list)
        for item in result.evidence:
            evidence_by_source[item.source_id].append(item)
        with connect(fresh) as connection:
            for source in result.sources:
                upsert_source(connection, source)
                upsert_source_evidence(
                    connection, source.source_id, evidence_by_source[source.source_id]
                )
        if database_path.exists():
            archive = database_path.parent / "archive"
            archive.mkdir(exist_ok=True)
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
            with (
                sqlite3.connect(database_path) as previous,
                sqlite3.connect(archive / f"{database_path.stem}-{stamp}.sqlite3") as backup,
            ):
                previous.backup(backup)
        os.replace(fresh, database_path)
    finally:
        fresh.unlink(missing_ok=True)


def write_exports(result: IngestionResult, output_dir: Path) -> None:
    """Write machine-readable registers and a concise Markdown ingestion report."""
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "source_register.json").write_text(
        json.dumps([item.model_dump(mode="json") for item in result.sources], indent=2),
        encoding="utf-8",
    )
    (output_dir / "evidence_register.json").write_text(
        json.dumps([item.model_dump(mode="json") for item in result.evidence], indent=2),
        encoding="utf-8",
    )
    with (output_dir / "source_register.csv").open("w", encoding="utf-8", newline="") as handle:
        fields = [
            "source_id",
            "title",
            "source_type",
            "original_file_path",
            "checksum",
            "ingestion_status",
            "lifecycle_status",
            "duplicate_group",
            "predecessor_source_id",
            "successor_source_id",
            "exclusion_reason",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for source in result.sources:
            data = source.model_dump(mode="json")
            writer.writerow({field: data.get(field) for field in fields})
    summary = result.summary()
    lines = ["# Ingestion report", "", f"- Dataset fingerprint: `{result.dataset_fingerprint}`"]
    lines.extend(
        f"- {key.replace('_', ' ').title()}: {value}"
        for key, value in summary.items()
        if key not in {"dataset_fingerprint", "available_releases"}
    )
    lines.extend(
        [
            "",
            "## Release purposes",
            "",
            "Only Phase 2 sources contribute to the active SQLite ledger, indexes and fingerprint.",
            "Phase 1 remains available on disk as archived framework-development material; it is not modelling evidence.",
            "",
        ]
    )
    for release in result.available_releases:
        lines.append(
            f"- {release['directory']}: {release['purpose']}; available={release['available']}; files={release['file_count']}; active={release['active']}"
        )
    if result.warnings:
        lines.extend(["", "## Warnings", "", *[f"- {warning}" for warning in result.warnings]])
    (output_dir / "ingestion_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
