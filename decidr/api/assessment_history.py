"""Explicit saves and owner-scoped access to frozen supplied assessments."""

from collections import Counter
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
from decidr.claim_interpreter import Finding

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


class SaveCanonicalReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    request_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    revision_reason: Text
    findings: list[Finding] = Field(min_length=1, max_length=160)


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
        "decidr/api/interpretation.py",
        "decidr/interpretation_engine.py",
        "decidr/approval_propositions.py",
        "decidr/approval_context.py",
        "decidr/authority_context.py",
        "decidr/authority_resolution.py",
        "decidr/policy_adoption.py",
        "decidr/expense_approval.py",
        "decidr/renewal_cap.py",
        "decidr/deployment_signoff.py",
        "decidr/practice_assessment.py",
        "decidr/transaction_claims.py",
        "decidr/claim_interpreter.py",
        "decidr/claim_spans.py",
        "decidr/canonical_assessment.py",
        "decidr/general_assessment.py",
        "decidr/evidence_synthesis.py",
        "decidr/authority_links.py",
        "decidr/source_metadata.py",
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
            parent = history.get_run(path, user["id"], request.parent_run_id)
            if parent["snapshot"]["response"].get("canonical_assessment"):
                raise HTTPException(
                    409,
                    "Canonical assessments require a canonical review so the saved result and evidence relationships stay consistent.",
                )
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


@router.post("/{run_id}/review-canonical")
def review_canonical(run_id: RunId, request: SaveCanonicalReviewRequest, user: Owner):
    """Reassess declared relationships against exactly the parent's frozen evidence."""
    from datetime import date

    from decidr.api.interpretation import InterpretationProposalRequest
    from decidr.canonical_assessment import canonical_assessment
    from decidr.general_assessment import project_response
    from decidr.retrieval_models import Evidence, Source

    def binding(finding):
        return tuple(
            finding.get(key) for key in ("component_id", "evidence_id", "source_id", "quotation")
        )

    with history_errors():
        path = history_path()
        parent = history.get_run(path, user["id"], run_id)
        snapshot = parent["snapshot"]
        canonical = snapshot["response"].get("canonical_assessment")
        if not canonical or canonical.get("processing", {}).get("status") != "assessed":
            raise HTTPException(409, "Only a completed canonical assessment can be reviewed here.")
        command = {
            **request.model_dump(mode="json"),
            "parent_run_id": run_id,
            "method": "canonical-human-review-v1",
        }
        previous = history.existing_retry(path, user["id"], command)
        if previous is not None:
            return JSONResponse(previous, status_code=200)
        prior = [
            finding for component in canonical["components"] for finding in component["findings"]
        ]
        findings = [finding.model_dump(mode="json") for finding in request.findings]
        expected = Counter(binding(finding) for finding in prior)
        supplied = Counter(binding(finding) for finding in findings)
        if supplied != expected:
            raise HTTPException(
                422,
                "A review must preserve every existing component and exact citation binding. Add evidence through a new assessment.",
            )
        sources = {
            source["source_id"]: Source.model_validate(source) for source in snapshot["sources"]
        }
        evidence = {
            passage["evidence_id"]: Evidence.model_validate(passage)
            for passage in snapshot["evidence"]
        }
        as_of = date.fromisoformat(snapshot["request"]["as_of"])
        provenance = {
            "assessment_method": "canonical-human-review-v1",
            "review_basis": "human_supplied_judgements",
            "revision_basis": "frozen_parent_snapshot",
            "parent_run_id": run_id,
            "parent_snapshot_sha256": parent["snapshot_sha256"],
            "parent_assessment_method": snapshot.get("provenance", {}).get("assessment_method"),
            "corpus_index_sha256": snapshot.get("provenance", {}).get("corpus_index_sha256"),
            "evidence_scope": "frozen_parent_corpus",
            "implementation": implementation_manifest(),
        }
        reviewed = canonical_assessment(
            canonical["interpreted_claim"],
            {"findings": findings, "unresolved_questions": []},
            evidence,
            sources,
            as_of,
            diagnostics={
                "review_basis": "human_supplied_judgements",
                "revision_reason": request.revision_reason,
                "parent_unresolved_questions": canonical.get("unresolved_questions", []),
            },
            provenance=provenance,
        )
        if reviewed["processing"]["status"] != "assessed":
            raise HTTPException(
                422,
                "The reviewed judgements could not be validated against the frozen parent assessment.",
            )
        selected_ids = list(
            dict.fromkeys(
                citation["evidence_id"]
                for item in snapshot["response"]["inputs"]
                for citation in item["interpretation"]["citations"]
            )
        )
        selected = [
            {
                "evidence_id": key,
                "source_id": evidence[key].source_id,
                "locator": evidence[key].locator,
                "text": evidence[key].text,
            }
            for key in selected_ids
        ]
        assessment_request = InterpretationProposalRequest(
            claim=snapshot["request"]["claim_text"],
            facet=snapshot["request"]["facet"],
            as_of=as_of,
            assessment_target=snapshot["request"]["assessment_target"],
        )
        response, packet = project_response(assessment_request, reviewed, selected, sources)
        response.update(
            status="assessed_supplied_judgements",
            interpretation_basis="frozen_parent_interpretation",
            target_validation="human_declared_relationships_exact_citations_checked",
        )
        response["assurance"].update(
            human_review="declared_by_user",
            outcome_basis="canonical_human_component_assessment",
            notice="This revision uses human-supplied evidence judgements and the original frozen citations. Source authenticity, authority and independence are not established merely by saving a review.",
        )
        response["claim_conclusion"]["notice"] = response["assurance"]["notice"]
        reviewed["processing"]["message"] = (
            "Human-supplied findings were checked against the parent's frozen evidence and deterministic safeguards."
        )
        bundle = {
            "response": response,
            "request": packet,
            "sources": snapshot["sources"],
            "evidence": snapshot["evidence"],
            "configuration": snapshot["configuration"],
            "interpretation": canonical["interpreted_claim"],
            "provenance": provenance,
        }
        result, created = history.append_run(path, user["id"], command, bundle)
    return JSONResponse(result, status_code=201 if created else 200)


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
