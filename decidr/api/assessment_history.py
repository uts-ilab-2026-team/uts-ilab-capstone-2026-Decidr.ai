"""Explicit saves and owner-scoped access to frozen supplied assessments."""

from contextlib import contextmanager
import hashlib
from importlib.metadata import version
import os
from pathlib import Path
import platform
import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from decidr import assessment_history as history
from decidr.api import auth
from decidr.api.supplied_assessment import (
    SuppliedAssessmentRequest,
    Text,
    build_supplied_assessment,
)

router = APIRouter(prefix="/api/assessments")
Owner = Annotated[dict, Depends(auth.current_user)]
RunId = Annotated[str, Field(pattern=r"^[0-9a-f-]{36}$")]


class SaveAssessmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    request_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    assessment: SuppliedAssessmentRequest
    parent_run_id: RunId | None = None
    revision_reason: Text | None = None

    @model_validator(mode="after")
    def revision_needs_reason(self):
        if self.parent_run_id and not self.revision_reason:
            raise ValueError("A parent-linked revision requires a reason")
        return self


def history_path() -> Path:
    configured = os.environ.get("DECIDR_ASSESSMENT_DB", "").strip()
    if not configured:
        raise HTTPException(status_code=503, detail="Assessment history is not configured.")
    path = Path(configured).expanduser().resolve()
    protected = [
        Path(os.environ.get("DECIDR_AUTH_DB", auth.DEFAULT_DB_PATH)).expanduser().resolve()
    ]
    corpus = os.environ.get("DECIDR_CORPUS_DB", "").strip()
    if corpus:
        protected.append(Path(corpus).expanduser().resolve())
    if any(
        path == other or (path.exists() and other.exists() and path.samefile(other))
        for other in protected
    ):
        raise HTTPException(
            status_code=503, detail="Assessment history requires a separate database."
        )
    return path


@contextmanager
def history_errors():
    try:
        yield
    except history.HistoryNotFound as error:
        raise HTTPException(status_code=404, detail="Assessment snapshot not found.") from error
    except history.HistoryConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except (history.HistoryIntegrityError, sqlite3.Error, OSError) as error:
        raise HTTPException(
            status_code=503, detail="Assessment history could not be read or saved."
        ) from error


def implementation_manifest() -> dict:
    """Record source-file hashes as build provenance, not a signed executable identity."""
    root = Path(__file__).resolve().parents[2]
    names = [
        "decidr/assessment_adapter.py",
        "decidr/assessment_targets.py",
        "decidr/assessment_response.py",
        "decidr/interpretation_models.py",
        "decidr/retrieval_models.py",
        "decidr/api/supplied_assessment.py",
        "decidr/assessment_history.py",
        "decidr/api/assessment_history.py",
    ]
    names.extend(str(p.relative_to(root)) for p in sorted((root / "framework").glob("*.py")))
    hashes = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names}
    return {
        "method": "source-files-on-disk-v1",
        "files": hashes,
        "sha256": history.content_hash(hashes),
        "runtime": {
            "python": platform.python_version(),
            "fastapi": version("fastapi"),
            "pydantic": version("pydantic"),
        },
    }


@router.post("")
def save_assessment(request: SaveAssessmentRequest, user: Owner):
    """Assess current stored evidence and save that server-generated result explicitly."""
    with history_errors():
        path = history_path()
        command = request.model_dump(mode="json")
        previous = history.existing_retry(path, user["id"], command)
        if previous is not None:
            return JSONResponse(previous, status_code=200)
        if request.parent_run_id:
            history.get_run(path, user["id"], request.parent_run_id)
        bundle = build_supplied_assessment(request.assessment, freeze=True)
        bundle["provenance"]["implementation"] = implementation_manifest()
        result, created = history.append_run(path, user["id"], command, bundle)
    return JSONResponse(result, status_code=201 if created else 200)


@router.get("")
def assessment_list(
    user: Owner, limit: int = Query(default=20, ge=1, le=100), offset: int = Query(default=0, ge=0)
):
    with history_errors():
        items = history.list_runs(history_path(), user["id"], limit=limit, offset=offset)
    return {"items": items, "limit": limit, "offset": offset}


@router.get("/{run_id}")
def assessment_snapshot(run_id: RunId, user: Owner):
    with history_errors():
        return history.get_run(history_path(), user["id"], run_id)


@router.get("/{run_id}/export")
def assessment_export(run_id: RunId, user: Owner):
    with history_errors():
        record = history.get_run(history_path(), user["id"], run_id)
    return Response(
        history.canonical_json(record),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="assessment-{run_id}.json"'},
    )
