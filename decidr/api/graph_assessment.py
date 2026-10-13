"""Single-path claim assessment endpoint: NL claim -> graph-engine credibility verdict.

Exposes the ``decidr.assess_claim`` pipeline (split -> retrieve -> read -> shim -> graph engine
-> combine) over HTTP for the frontend. Returns ``to_payload``'s clean, UI-ready shape — NOT the
legacy ``build_general_bundle`` envelope. The older ``/api/corpus/assess-automatic`` route is left
untouched as a fallback.

The corpus snapshot, backbone skeleton and config are loaded once (cached) and reused across
requests; only the per-claim LLM work runs each call.
"""

from datetime import date
from functools import lru_cache
import re

from fastapi import APIRouter, Depends, HTTPException
from framework import CONFIG_PATH
from framework.config import GraphCredibilityConfig
from pydantic import BaseModel, ConfigDict, Field, field_validator

from decidr.api import auth
from decidr.assess_claim import assess_claim, to_payload
from decidr.backbone_assessment import load_skeleton
from decidr.claim_interpreter import ProviderError, get_provider
from decidr.finding_shim import load_corpus_snapshot

router = APIRouter(
    prefix="/api/corpus",
    dependencies=[Depends(auth.current_user)],
)


class AssessClaimRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    claim: str = Field(min_length=1, max_length=10000)
    as_of: date

    @field_validator("claim")
    @classmethod
    def reject_blank_claim(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Claim must not be blank")
        return value

    @field_validator("as_of", mode="before")
    @classmethod
    def explicit_iso_date(cls, value):
        if type(value) is date:
            return value
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("as_of must be an explicit YYYY-MM-DD date")
        return date.fromisoformat(value)


@lru_cache(maxsize=1)
def _snapshot():
    return load_corpus_snapshot()


@lru_cache(maxsize=1)
def _skeleton():
    return load_skeleton()


@lru_cache(maxsize=1)
def _config():
    return GraphCredibilityConfig.load(CONFIG_PATH)


ASSESSMENT_METHOD = "graph-credibility-v1"


def _run_claim(claim: str, as_of):
    """Shared engine run with the cached snapshot/skeleton/config. Raises HTTPException on model
    unavailability (503) or model failure (502) so both callers surface the same errors."""
    try:
        provider = get_provider()
    except ProviderError as error:
        raise HTTPException(
            status_code=503,
            detail="No local assessment model is configured; set DECIDR_ASSESSMENT_PROVIDER/MODEL.",
        ) from error
    try:
        return assess_claim(
            claim,
            provider,
            as_of=as_of,
            snapshot=_snapshot(),
            skeleton=_skeleton(),
            config=_config(),
        )
    except ProviderError as error:
        raise HTTPException(status_code=502, detail=f"Assessment model failed: {error}") from error


def build_graph_bundle(request) -> dict:
    """Run the engine and wrap it in the history bundle envelope the save/list path expects.

    ``request`` only needs ``.claim`` and ``.as_of`` (``.facet`` optional). The returned bundle's
    ``response`` carries our full verdict payload PLUS the minimal legacy summary keys
    (``claim_text``/``facet``/``as_of``/``status``/``assessment``/``assurance``) that
    ``assessment_history.append_run``/``list_runs`` read, so persistence keeps working unchanged.
    """
    result = _run_claim(request.claim, request.as_of)
    payload = to_payload(result)
    facet = getattr(request, "facet", None) or result.claim_text
    verdict = result.verdict
    response = {
        **payload,
        "claim_text": result.claim_text,
        "facet": facet,
        "as_of": str(result.as_of),
        "status": "assessed_automatically",
        # Claim-level formal/observed are not separated by the combiner; mirror the overall
        # outcome for the history summary (per-facet lanes live in payload["facets"]).
        "assessment": {
            "overall_outcome": verdict.overall_outcome,
            "formal_outcome": verdict.overall_outcome,
            "observed_outcome": verdict.overall_outcome,
            "confidence": verdict.confidence,
        },
        "assurance": {"outcome_basis": "graph_engine_deterministic_scoring"},
    }
    return {
        "response": response,
        "request": {
            "claim_text": result.claim_text,
            "facet": facet,
            "assessment_target": result.split.get("target"),
            "as_of": str(result.as_of),
        },
        "provenance": {
            "assessment_method": ASSESSMENT_METHOD,
            "evidence_scope": "graph_guided_lane_balanced_retrieval",
        },
    }


@router.post("/assess")
def assess(request: AssessClaimRequest) -> dict:
    """Assess one claim end to end and return the UI-ready verdict payload."""
    return to_payload(_run_claim(request.claim, request.as_of))
