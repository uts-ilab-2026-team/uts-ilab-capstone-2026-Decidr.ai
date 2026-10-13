"""Automatic assessment endpoint (legacy general-bundle path) + parent-linked human review.

Single code path: delegates to ``decidr.general_assessment.build_general_bundle``. The former
``bounded`` vs general dispatcher — and the overloaded ``DECIDR_ASSESSMENT_PROVIDER`` toggle that
selected it — were removed (3d). ``DECIDR_ASSESSMENT_PROVIDER`` now means only "which LLM provider"
(used by the graph-engine endpoint ``POST /api/corpus/assess``); it no longer switches this route.
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import Field

from decidr import assessment_history as history
from decidr.api import auth
from decidr.api.assessment_history import (
    Owner,
    history_errors,
    history_path,
    implementation_manifest,
)
from decidr.api.corpus import corpus_database_path
from decidr.api.interpretation import InterpretationProposalRequest

router = APIRouter(dependencies=[Depends(auth.current_user)])


class SaveAutomaticRequest(InterpretationProposalRequest):
    request_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


def build_automatic_assessment(request: InterpretationProposalRequest) -> dict:
    from decidr.general_assessment import build_general_bundle

    try:
        path = corpus_database_path()
    except HTTPException:
        path = None
    return build_general_bundle(request, path)


@router.post("/api/corpus/assess-automatic")
def assess_automatic(request: InterpretationProposalRequest):
    return build_automatic_assessment(request)["response"]


@router.post("/api/assessments/automatic")
def save_automatic(request: SaveAutomaticRequest, user: Owner):
    with history_errors():
        from decidr.general_assessment import METHOD as GENERAL_METHOD

        path = history_path()
        command = {**request.model_dump(mode="json"), "method": GENERAL_METHOD}
        previous = history.existing_retry(path, user["id"], command)
        if previous is not None:
            return JSONResponse(previous, status_code=200)
        query = InterpretationProposalRequest.model_validate(
            request.model_dump(exclude={"request_id"})
        )
        bundle = build_automatic_assessment(query)
        bundle["provenance"]["implementation"] = implementation_manifest()
        record, created = history.append_run(path, user["id"], command, bundle)
    return JSONResponse(record, status_code=201 if created else 200)
