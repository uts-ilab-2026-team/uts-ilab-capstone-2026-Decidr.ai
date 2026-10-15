"""Register one file and label every inferred metadata field as a Source."""

from pathlib import Path

from decidr.ingestion.helpers import (
    ANNOTATION_NAMES,
    TECHNICAL_NAMES,
    _related_source_codes,
    _source_code,
    _source_type,
    sha256_file,
)
from decidr.retrieval_models import Source
from decidr.source_metadata import (
    METADATA_VERSION,
    approval_lifecycle,
    header_date,
    read_header,
)


def build_source(path: Path, root: Path, release: str) -> Source:
    """Register a file and label every inferred metadata field."""
    relative = path.relative_to(root)
    checksum = sha256_file(path)
    source_type = _source_type(relative)
    title, metadata, header_entries, conflicts = (
        read_header(path) if path.suffix.casefold() == ".md" else (path.stem, {}, [], [])
    )
    code = _source_code(path, title)
    excluded = path.name in TECHNICAL_NAMES or path.name in ANNOTATION_NAMES
    is_superseded = "superseded" in {part.casefold() for part in relative.parts}
    owner = metadata.get("document owner") or metadata.get("owner")
    role_function = metadata.get("role / function")
    author = owner or (role_function.split(",", 1)[0] if role_function else None)
    date_key = (
        "date"
        if "date" in metadata or any(c["field"] == "date" for c in conflicts)
        else "interview date"
    )
    creation_date = header_date(metadata, date_key, conflicts)
    last_updated_date = header_date(metadata, "last updated", conflicts)
    effective_start = header_date(metadata, "effective date", conflicts)
    effective_end = header_date(metadata, "effective end date", conflicts)
    superseded_date = header_date(metadata, "superseded date", conflicts)
    if effective_start and effective_end and effective_start > effective_end:
        conflicts.append(
            {
                "field": "effective_end_date",
                "values": [effective_start.isoformat(), effective_end.isoformat()],
                "reason": "Effective end precedes start; interval left unresolved.",
            }
        )
        effective_end = None

    approval = metadata.get("approval status")
    own_lifecycle, approval_clauses, approval_conflicts = approval_lifecycle(approval, code)
    conflicts.extend(approval_conflicts)
    approval_unresolved = any(
        item["field"] in {"approval_status", "lifecycle_status"} for item in conflicts
    )
    if approval_unresolved:
        lifecycle = "unknown"
        lifecycle_provenance = "unresolved:approval_metadata"
    elif is_superseded:
        lifecycle = "superseded"
        lifecycle_provenance = "inferred:superseded_directory"
    elif own_lifecycle:
        lifecycle = own_lifecycle
        lifecycle_provenance = "derived:document_scoped_approval_clauses"
    else:
        lifecycle = "current"
        lifecycle_provenance = "inferred:active_directory_not_proof_of_approval"

    for entry in header_entries:
        entry["source_id"] = f"{release}:{code}"
    provenance = {
        "title": "direct:markdown_h1" if path.suffix.casefold() == ".md" else "inferred:filename",
        "source_type": "inferred:directory",
        "release": "direct:configured_root",
        "checksum": "calculated:sha256",
        "lifecycle_status": lifecycle_provenance,
    }
    for key in (
        "version",
        "approval status",
        "effective date",
        "effective end date",
        "last updated",
        "superseded date",
        "document owner",
        "owner",
        "related documents",
    ):
        if key in metadata:
            provenance[key.replace(" ", "_")] = f"direct:markdown_metadata:{key}"
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
        related_source_codes=_related_source_codes(metadata.get("related documents"), code),
        author_or_system=author,
        creation_date=creation_date,
        last_updated_date=last_updated_date,
        superseded_date=superseded_date,
        effective_start_date=effective_start,
        effective_end_date=effective_end,
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
        header_evidence=header_entries,
        approval_clauses=approval_clauses,
        metadata_conflicts=conflicts,
    )
