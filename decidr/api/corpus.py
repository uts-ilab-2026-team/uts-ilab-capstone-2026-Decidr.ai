"""Authenticated corpus retrieval; no claim verdicts are assigned."""

from contextlib import closing
from dataclasses import asdict
import os
from pathlib import Path
import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from decidr.api import auth
from decidr.hybrid import search_corpus
from decidr.retrieval_models import Source


router = APIRouter(
    prefix="/api/corpus",
    dependencies=[Depends(auth.current_user)],
)


class CorpusSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim: str = Field(min_length=1, max_length=10000)
    limit: int = Field(default=8, ge=1, le=50, strict=True)

    @field_validator("claim")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Claim must not be blank")
        return value


def corpus_database_path() -> Path:
    configured = os.environ.get("DECIDR_CORPUS_DB")
    if not configured or not configured.strip():
        raise HTTPException(
            status_code=503,
            detail="Corpus search is unavailable: DECIDR_CORPUS_DB is not configured.",
        )
    path = Path(configured).expanduser().resolve()
    if not path.is_file():
        raise HTTPException(
            status_code=503,
            detail="The configured corpus database is unavailable.",
        )
    return path


@router.post("/search")
def corpus_search(request: CorpusSearchRequest) -> dict:
    path = corpus_database_path()
    try:
        # Create and use the connection in this request's worker thread.
        # mode=ro prevents creation or modification of a database.
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only = ON")
            connection.execute("BEGIN")

            sources = {
                row["source_id"]: Source.model_validate_json(row["payload_json"])
                for row in connection.execute(
                    "SELECT source_id, payload_json FROM sources ORDER BY source_id"
                )
            }
            evidence_count = connection.execute(
                "SELECT COUNT(*) FROM evidence"
            ).fetchone()[0]

            if not sources or not evidence_count:
                raise HTTPException(
                    status_code=503,
                    detail="The corpus index contains no searchable evidence.",
                )

            result = search_corpus(
                connection, request.claim, limit=request.limit
            )
            candidates = {
                item.evidence_id: item for item in result.candidates
            }

            def group_payload(group, position):
                passages = []
                for passage in group.passages:
                    candidate = candidates.get(passage.evidence_id)
                    passages.append({
                        "evidence": passage.model_dump(mode="json"),
                        "interpretation_status": "unassessed",
                        "relationship": None,
                        "retrieval": (
                            asdict(candidate.retrieval)
                            if candidate and candidate.retrieval else None
                        ),
                        "record_references": (
                            [asdict(item) for item in candidate.record_references]
                            if candidate else []
                        ),
                    })
                return {
                    "position": position,
                    "source_id": group.lead_result.source_id,
                    "lead_evidence_id": group.lead_result.evidence_id,
                    "matched_evidence_ids": list(group.matched_evidence_ids),
                    "passages": passages,
                }

            ranked = [
                group_payload(group, position)
                for position, group in enumerate(result.ranked_groups, 1)
            ]
            linked = [
                group_payload(group, position)
                for position, group in enumerate(result.additional_linked_groups, 1)
            ]
            displayed_source_ids = {
                group["source_id"] for group in [*ranked, *linked]
            }
            source_payloads = [
                sources[source_id].model_dump(mode="json")
                for source_id in sorted(displayed_source_ids)
            ]

    except sqlite3.Error as error:
        raise HTTPException(
            status_code=503,
            detail="The corpus index could not be read; check its configuration and schema.",
        ) from error

    return {
        "claim": request.claim,
        "status": "retrieved_unassessed",
        "assessment": None,
        "retrieval_method": "lexical_with_explicit_record_links",
        "ranked_group_limit": request.limit,
        "indexed_source_count": len(sources),
        "indexed_evidence_count": evidence_count,
        "candidate_count": len(result.candidates),
        "ranked_groups": ranked,
        "additional_linked_groups": linked,
        "sources": source_payloads,
        "limitations": [
            "Retrieval relevance and record links do not establish support or contradiction.",
            "Section context is included without becoming independent corroboration.",
            "Additional linked groups are outside the ranked-group limit.",
            "Temporal applicability and credibility have not been assessed.",
            "Search results are not exhaustive evidence coverage.",
        ],
    }
