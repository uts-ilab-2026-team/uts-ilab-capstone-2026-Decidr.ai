"""Authenticated facet assessment of explicitly supplied judgements."""

from contextlib import closing
from datetime import date
import json
import re
import sqlite3
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from framework import CONFIG_PATH
from framework.config import GraphCredibilityConfig
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from decidr.api import auth
from decidr.api.corpus import corpus_database_path
from decidr.assessment_adapter import PreparedAttestation, assess_prepared_facet
from decidr.assessment_response import serialize_facet_assessment
from decidr.interpretation_models import EvidenceInterpretation, InterpretationCitation
from decidr.retrieval_models import Evidence, Source

router = APIRouter(
    prefix="/api/corpus",
    dependencies=[Depends(auth.current_user)],
)

Text = Annotated[
    str, StringConstraints(strict=True, min_length=1, max_length=10000, pattern=r"\S")
]
Score = Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]


class SuppliedInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    stance: Literal["support", "contradict", "qualify", "context", "unresolved"]
    mode: Literal["formal", "observed", "unresolved"]
    rationale: Text
    citations: list[InterpretationCitation] = Field(min_length=1, max_length=20)
    origin_id: Text
    source_class: Text
    approval_key: Text
    scope_matches: bool | None
    temporal_matches: bool | None
    authority_verified: bool | None
    directness: Score
    specificity: Score
    completeness: Score
    judgement_basis: Text
    origin_basis: Text
    independence_verified: bool = False
    independence_basis: str = Field(default="", max_length=10000)


class SuppliedAssessmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    claim_text: Text
    facet: Text
    as_of: date
    inputs: list[SuppliedInput] = Field(min_length=1, max_length=50)

    @field_validator("as_of", mode="before")
    @classmethod
    def explicit_iso_date(cls, value):
        if type(value) is date:
            return value
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("as_of must be an explicit YYYY-MM-DD date")
        return date.fromisoformat(value)


@router.post("/assess-supplied")
def assess_supplied(request: SuppliedAssessmentRequest) -> dict:
    """Assess a supplied packet; never infer relationships or save review records."""
    for item in request.inputs:
        if len({citation.source_id for citation in item.citations}) != 1:
            raise HTTPException(
                status_code=422,
                detail="Each supplied interpretation must cite exactly one source.",
            )

    path = corpus_database_path()
    evidence = {}
    sources = {}
    try:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
            connection.execute("PRAGMA query_only = ON")
            connection.execute("BEGIN")
            for item in request.inputs:
                for citation in item.citations:
                    key = (citation.evidence_id, citation.source_id)
                    if key in evidence:
                        continue
                    row = connection.execute(
                        """
                        SELECT e.payload_json, s.payload_json
                        FROM evidence AS e
                        JOIN sources AS s ON s.source_id = e.source_id
                        WHERE e.evidence_id = ? AND e.source_id = ?
                        """,
                        key,
                    ).fetchone()
                    if row is None:
                        raise HTTPException(
                            status_code=404,
                            detail="Cited evidence/source pair not found in the current index.",
                        )
                    passage = Evidence.model_validate_json(row[0])
                    source = Source.model_validate_json(row[1])
                    if (
                        passage.evidence_id != citation.evidence_id
                        or passage.source_id != citation.source_id
                        or source.source_id != citation.source_id
                    ):
                        raise ValueError("Stored citation identity mismatch")
                    evidence[key] = passage
                    sources[source.source_id] = source
    except (sqlite3.Error, ValueError) as error:
        raise HTTPException(
            status_code=503,
            detail="Stored assessment evidence could not be read; check the corpus index.",
        ) from error

    try:
        config = GraphCredibilityConfig(**json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError) as error:
        raise HTTPException(
            status_code=503, detail="Assessment configuration is unavailable."
        ) from error

    prepared = []
    for item in request.inputs:
        interpretation = EvidenceInterpretation(
            claim_text=request.claim_text,
            facet=request.facet,
            stance=item.stance,
            mode=item.mode,
            rationale=item.rationale,
            citations=tuple(item.citations),
        )
        prepared.append(
            PreparedAttestation(
                interpretation=interpretation,
                source=sources[item.citations[0].source_id],
                origin_id=item.origin_id,
                source_class=item.source_class,
                approval_key=item.approval_key,
                scope_matches=item.scope_matches,
                temporal_matches=item.temporal_matches,
                authority_verified=item.authority_verified,
                directness=item.directness,
                specificity=item.specificity,
                completeness=item.completeness,
                judgement_basis=item.judgement_basis,
                origin_basis=item.origin_basis,
                independence_verified=item.independence_verified,
                independence_basis=item.independence_basis,
            )
        )

    try:
        result = assess_prepared_facet(
            claim_text=request.claim_text,
            facet=request.facet,
            as_of=request.as_of,
            prepared=prepared,
            evidence=list(evidence.values()),
            config=config,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    response = serialize_facet_assessment(result)
    response.update(
        {
            "status": "assessed_supplied_judgements",
            "index_scope": "current",
            "persisted": False,
            "config_version": config.config_version,
        }
    )
    return response
