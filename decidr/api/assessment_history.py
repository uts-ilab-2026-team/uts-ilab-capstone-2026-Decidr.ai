"""Owner-scoped read access to frozen assessment runs (list / snapshot / export).

Writes happen in ``automatic_assessment.save_automatic`` (the graph-engine claim runner). The old
human-revision endpoints (save-revised, canonical-review) were retired with the legacy scorers.
"""

from contextlib import contextmanager
import hashlib
from importlib.metadata import version
import os
from pathlib import Path
import platform
import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import Field

from decidr import assessment_history as history
from decidr.api import auth

router = APIRouter(prefix="/api/assessments")
Owner = Annotated[dict, Depends(auth.current_user)]
RunId = Annotated[str, Field(pattern=r"^[0-9a-f-]{36}$")]


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
        "decidr/api/automatic_assessment.py",
        "decidr/api/graph_assessment.py",
        "decidr/api/assessment_history.py",
        "decidr/assessment_history.py",
        "decidr/reading/finding_shim.py",
        "decidr/claims/combiner.py",
        "decidr/claims/split.py",
        "decidr/reading/fast_reader.py",
        "decidr/claims/spans.py",
        "decidr/corpus/models.py",
        "decidr/retrieval/hybrid.py",
        "decidr/corpus/store.py",
    ]
    names.extend(
        str(p.relative_to(root))
        for p in sorted((root / "decidr" / "claim_interpreter").glob("*.py"))
    )
    names.extend(
        str(p.relative_to(root)) for p in sorted((root / "decidr" / "assess_claim").glob("*.py"))
    )
    names.extend(
        str(p.relative_to(root))
        for p in sorted((root / "decidr" / "corpus" / "ingest").glob("*.py"))
    )
    names.extend(
        str(p.relative_to(root)) for p in sorted((root / "decidr" / "backbone").glob("*.py"))
    )
    names.extend(
        str(p.relative_to(root)) for p in sorted((root / "decidr" / "graph").glob("*.py"))
    )
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
