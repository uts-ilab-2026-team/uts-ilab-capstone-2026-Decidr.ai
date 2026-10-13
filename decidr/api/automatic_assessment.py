"""Claim runner + save: POST /api/assessments/automatic runs the graph engine and saves it.

The claim check now runs the single-path graph engine (``decidr.assess_claim`` via
``graph_assessment.build_graph_bundle``). The former general/bounded scorers are retired. The
saved bundle keeps the history envelope (``response``/``request``/``provenance``) so the history
read endpoints (list/snapshot/export) keep working.
"""

from fastapi import APIRouter, Depends
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
from decidr.api.graph_assessment import ASSESSMENT_METHOD, build_graph_bundle
from decidr.api.interpretation import InterpretationProposalRequest

router = APIRouter(dependencies=[Depends(auth.current_user)])


class SaveAutomaticRequest(InterpretationProposalRequest):
    request_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


def build_automatic_assessment(request: InterpretationProposalRequest) -> dict:
    return build_graph_bundle(request)


@router.post("/api/assessments/automatic")
def save_automatic(request: SaveAutomaticRequest, user: Owner):
    with history_errors():
        path = history_path()
        command = {**request.model_dump(mode="json"), "method": ASSESSMENT_METHOD}
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
