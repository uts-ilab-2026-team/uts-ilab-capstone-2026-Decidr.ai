"""Shared ingestion primitives: constants, hashing, slugs, and the result type."""

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
import hashlib
from pathlib import Path
import re
import subprocess

from decidr.corpus.models import Evidence, Source
from decidr.infra.constants import SOURCE_CODE_PATTERN

SUPPORTED_SUFFIXES = {".md", ".csv"}
TECHNICAL_NAMES = {"README.md"}
ANNOTATION_NAMES = {"labelled_claims_sample.csv"}
METADATA_PATTERN = re.compile(r"^- \*\*(?P<key>[^*]+):\*\*\s*(?P<value>.*)$")
HEADING_PATTERN = re.compile(r"^(?P<level>#{1,6})\s+(?P<title>.+?)\s*$")
DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")


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
    configuration_version: str = "ingestion-v3-document-header"

    def summary(self) -> dict[str, object]:
        statuses = Counter(source.ingestion_status for source in self.sources)
        types = Counter(source.source_type for source in self.sources)
        return {
            "dataset_fingerprint": self.dataset_fingerprint,
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


_RELATED_CODE = re.compile(r"\b([A-Z]{2,}-\d+)\b")


def _related_source_codes(value: str | None, self_code: str) -> list[str]:
    """Extract document codes from a 'Related documents:' metadata value.

    "PROC-02 (Discount Approval Process), POL-06 (...)" -> ["PROC-02", "POL-06"].
    "None formally linked." -> [] (no code pattern). The document's own code is dropped so a
    self-reference never produces a self-loop.
    """
    if not value:
        return []
    codes: list[str] = []
    for code in _RELATED_CODE.findall(value):
        if code != self_code and code not in codes:
            codes.append(code)
    return codes


def _evidence_id(source_id: str, locator: str) -> str:
    digest = hashlib.sha256(f"{source_id}\0{locator}".encode()).hexdigest()[:16]
    return f"EV-{digest}"


def dataset_fingerprint(sources: Iterable[Source]) -> str:
    """Hash sorted release-relative identities and checksums."""
    digest = hashlib.sha256()
    for source in sorted(sources, key=lambda item: item.source_id):
        digest.update(f"{source.source_id}\0{source.checksum}\n".encode())
    return digest.hexdigest()
