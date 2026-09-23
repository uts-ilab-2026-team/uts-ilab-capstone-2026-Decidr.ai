"""Release-purpose boundary shared by modelling, retrieval and research gates."""

import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any

RELEASE_PURPOSES = {
    "phase1": {
        "directory": "phase1_framework_development",
        "purpose": "framework-development-only",
        "active": False,
    },
    "phase2": {
        "directory": "phase2_model_development",
        "purpose": "active modelling corpus",
        "active": True,
    },
}
INGESTION_VERSION = "ingestion-v3-document-metadata"


def active_source(source_id: str) -> bool:
    return source_id.startswith("phase2:")


def modelling_release_from_metadata(
    source_payload: dict[str, Any], evidence_payload: dict[str, Any]
) -> str | None:
    """Resolve a release from ingested metadata without interpreting an identifier."""
    structured = evidence_payload.get("structured_metadata", {})
    release = structured.get("release") if isinstance(structured, dict) else None
    if isinstance(release, str) and release.strip():
        return release.strip()
    notes = source_payload.get("metadata_notes")
    if isinstance(notes, str):
        for item in notes.split(";"):
            key, separator, value = item.strip().partition("=")
            if separator and key.strip() == "release" and value.strip():
                return value.strip()
    return None


def eligible_modelling_evidence(
    source_payload: dict[str, Any],
    evidence_payload: dict[str, Any],
    ingestion_status: str,
) -> bool:
    """Apply the configured release purpose and ingestion eligibility metadata."""
    release = modelling_release_from_metadata(source_payload, evidence_payload)
    source_release = modelling_release_from_metadata(source_payload, {})
    if source_release and source_release != release:
        return False
    purpose = RELEASE_PURPOSES.get(release or "", {})
    source_status = source_payload.get("ingestion_status", ingestion_status)
    return (
        bool(purpose.get("active"))
        and ingestion_status == "ingested"
        and source_status == "ingested"
    )


def ledger_fingerprint(connection: sqlite3.Connection) -> str:
    digest = hashlib.sha256()
    for sid, checksum in connection.execute(
        "SELECT source_id,checksum FROM sources ORDER BY source_id"
    ):
        if not active_source(sid):
            raise ValueError("Non-modelling sources present; rebuild the active Phase 2 ledger.")
        digest.update(f"{sid}\0{checksum}\n".encode())
    return digest.hexdigest()


def freeze_compatibility(
    database: Path, configuration: dict, project_root: Path
) -> tuple[bool, str]:
    """Check frozen dependencies without loading claim content or review outcomes."""
    version = configuration.get("configuration_version", "")
    if not version or Path(version).name != version:
        return False, "A versioned study configuration and compatible corpus freeze are required."
    manifest_path = project_root / "framework" / f"portfolio_freeze_manifest_v{version}.json"
    if not manifest_path.is_file() or not database.is_file():
        return False, "Active ledger or portfolio freeze manifest is missing."
    manifest = json.loads(manifest_path.read_text())
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
        try:
            fingerprint = ledger_fingerprint(connection)
        except ValueError as error:
            return False, str(error)
    if (
        manifest.get("corpus_fingerprint") != fingerprint
        or manifest.get("ingestion_version") != INGESTION_VERSION
    ):
        return (
            False,
            f"Freeze v{version} is incompatible with the active Phase 2 corpus; a controlled new portfolio/freeze version is required.",
        )
    for key in ("claim_file", "design_file", "study_configuration_file"):
        path = project_root / manifest[key]
        if (
            hashlib.sha256(path.read_bytes()).hexdigest()
            != manifest[
                key.replace("_file", "_file_sha256")
                if key != "study_configuration_file"
                else "study_configuration_sha256"
            ]
        ):
            return False, "Frozen component checksum mismatch."
    frozen_configuration = json.loads(
        (project_root / manifest["study_configuration_file"]).read_text()
    )
    if frozen_configuration.get("operational_definitions") != configuration.get(
        "operational_definitions"
    ):
        return False, "Operational definitions differ from the frozen study configuration."
    return True, "Active modelling corpus matches the frozen dependencies."
