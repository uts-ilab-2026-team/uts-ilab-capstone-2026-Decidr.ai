"""FastAPI application exposing the graph credibility framework to the web frontend.

A thin interaction layer: every outcome, score and trace comes from ``framework``.
This module only shapes those records as JSON.
"""

from __future__ import annotations

from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from framework import (
    CONFIG_PATH,
    GRAPH_PATH,
    GraphCredibilityFramework,
    GraphFactsRegister,
    OrganisationalGraph,
)
from framework.errors import GraphValidationError
from pydantic import BaseModel, Field

from decidr.api import auth

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
ATTESTATIONS = {"FORMAL", "OBSERVED"}

app = FastAPI(title="Decidr claim checker API", version="0.1.0")
# Everything except the health check and the auth routes requires a signed-in user.
router = APIRouter(dependencies=[Depends(auth.current_user)])


@app.exception_handler(GraphValidationError)
def graph_validation_failed(request: Request, error: GraphValidationError) -> JSONResponse:
    """Report a graph or configuration that fails validation instead of a bare 500."""
    return JSONResponse(
        status_code=500, content={"detail": f"The graph data failed validation: {error}"}
    )


class ClaimCheckRequest(BaseModel):
    claim: str = Field(min_length=1)
    as_of: date | None = None


@lru_cache(maxsize=1)
def get_framework() -> GraphCredibilityFramework:
    return GraphCredibilityFramework.load(GRAPH_PATH, CONFIG_PATH)


def _today() -> date:
    return datetime.now().astimezone().date()


def _short_id(node_id: str) -> str:
    return node_id.split(":", 1)[-1]


def _document_ids(graph: OrganisationalGraph) -> list[str]:
    return sorted(node.node_id for node in graph.nodes.values() if node.kind == "document")


def _document_payload(graph: OrganisationalGraph, document_id: str) -> dict[str, Any]:
    document = graph.document(document_id)
    attributes = document.attributes
    owner = next(
        (
            graph.nodes[edge.target].label
            for edge in graph.edges.values()
            if edge.source == document_id and edge.relationship == "OWNED_BY"
        ),
        None,
    )
    attested_facts = {
        edge.target
        for edge in graph.edges.values()
        if edge.source == document_id and edge.relationship in ATTESTATIONS
    }
    return {
        "id": document_id,
        "short_id": _short_id(document_id),
        "title": document.label,
        "type": attributes.get("type"),
        "status": attributes.get("status", "unknown"),
        "approval_status": attributes.get("approval_status", "unknown"),
        "source_class": attributes.get("source_class", "unknown"),
        "effective_date": attributes.get("effective_date"),
        "effective_end_date": attributes.get("effective_end_date"),
        "last_updated": attributes.get("last_updated"),
        "owner": owner,
        "used_in": len(attested_facts),
    }


def _actor_payload(graph: OrganisationalGraph, edge_id: str) -> dict[str, Any] | None:
    actor_id = graph.edges[edge_id].attributes.get("actor_person_id")
    person = graph.nodes.get(str(actor_id)) if actor_id else None
    if person is None:
        return None
    roles = sorted(
        graph.nodes[edge.target].label
        for edge in graph.edges.values()
        if edge.source == person.node_id and edge.relationship == "HOLDS"
    )
    return {"id": person.node_id, "label": person.label, "roles": roles}


def _assessment_payload(
    framework: GraphCredibilityFramework, fact_id: str, as_of: date
) -> dict[str, Any]:
    graph = framework.graph
    try:
        assessment = framework.evaluate_fact(fact_id, as_of=as_of)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=f"Unknown fact: {fact_id}") from error
    fact = graph.nodes[fact_id]
    payload = assessment.model_dump()
    for item in payload["evidence"]:
        item["document"] = _document_payload(graph, item["document_id"])
        item["actor"] = _actor_payload(graph, item["edge_id"])
    payload["label"] = fact.label
    payload["scope"] = fact.attributes.get("scope")
    payload["as_of"] = as_of.isoformat()
    payload["sources_searched"] = len(_document_ids(graph))
    return payload


def _lineage(graph: OrganisationalGraph, document_id: str) -> list[dict[str, Any]]:
    links = []
    for edge in sorted(graph.edges.values(), key=lambda item: item.edge_id):
        if edge.relationship in ATTESTATIONS or document_id not in (edge.source, edge.target):
            continue
        outgoing = edge.source == document_id
        other = graph.nodes[edge.target if outgoing else edge.source]
        links.append(
            {
                "relationship": edge.relationship,
                "direction": "outgoing" if outgoing else "incoming",
                "node_id": other.node_id,
                "short_id": _short_id(other.node_id),
                "label": other.label,
                "kind": other.kind,
                "status": other.attributes.get("status"),
                "reason": edge.attributes.get("reason"),
            }
        )
    return links


@app.get("/api/health")
def health() -> dict[str, Any]:
    graph = get_framework().graph
    return {"status": "ok", "graph_version": graph.version, "facts": len(graph.fact_nodes())}


@router.get("/api/claims")
def list_claims(as_of: date | None = None) -> dict[str, Any]:
    """Facts register plus the dashboard summary counts."""
    framework = get_framework()
    assess_date = as_of or _today()
    records = GraphFactsRegister(framework, as_of=assess_date).list_records()
    return {
        "as_of": assess_date.isoformat(),
        "summary": {
            "claims_assessed": len(records),
            "contested": sum(item.overall_outcome == "Contested" for item in records),
            "insufficient_evidence": sum(
                item.overall_outcome == "Insufficient evidence" for item in records
            ),
            "sources": len(_document_ids(framework.graph)),
        },
        "claims": [item.model_dump() for item in records],
    }


@router.post("/api/claims/check")
def check_claim(request: ClaimCheckRequest) -> dict[str, Any]:
    """Retrieve the closest Fact for a free-text claim and assess that Fact."""
    framework = get_framework()
    assess_date = request.as_of or _today()
    matches = framework.graph.retrieve_facts(request.claim)
    return {
        "claim": request.claim,
        "as_of": assess_date.isoformat(),
        "sources_searched": len(_document_ids(framework.graph)),
        "matches": [
            {
                "fact_id": fact.node_id,
                "label": fact.label,
                "statement": fact.attributes.get("statement", fact.label),
                "similarity": round(score, 4),
            }
            for fact, score in matches
        ],
        "assessment": (
            _assessment_payload(framework, matches[0][0].node_id, assess_date) if matches else None
        ),
    }


@router.get("/api/claims/{fact_id}")
def get_claim(fact_id: str, as_of: date | None = None) -> dict[str, Any]:
    return _assessment_payload(get_framework(), fact_id, as_of or _today())


@router.get("/api/sources")
def list_sources() -> dict[str, Any]:
    graph = get_framework().graph
    return {"sources": [_document_payload(graph, item) for item in _document_ids(graph)]}


@router.get("/api/sources/{document_id}")
def get_source(document_id: str, as_of: date | None = None) -> dict[str, Any]:
    framework = get_framework()
    graph = framework.graph
    if document_id not in _document_ids(graph):
        raise HTTPException(status_code=404, detail=f"Unknown source: {document_id}")
    assess_date = as_of or _today()
    attestations = []
    for edge in sorted(graph.edges.values(), key=lambda item: item.edge_id):
        if edge.source != document_id or edge.relationship not in ATTESTATIONS:
            continue
        assessment = framework.evaluate_fact(edge.target, as_of=assess_date)
        reviewed = next(item for item in assessment.evidence if item.edge_id == edge.edge_id)
        attestations.append(
            {
                "edge_id": edge.edge_id,
                "fact_id": assessment.fact_id,
                "statement": assessment.statement,
                "mode": reviewed.mode,
                "stance": reviewed.stance,
                "attests_value": reviewed.attests_value,
                "applicable": reviewed.applicable,
                "material": reviewed.material,
                "formal_outcome": assessment.formal_outcome,
                "observed_outcome": assessment.observed_outcome,
                "overall_outcome": assessment.overall_outcome,
            }
        )
    return {
        **_document_payload(graph, document_id),
        "as_of": assess_date.isoformat(),
        "attestations": attestations,
        "lineage": _lineage(graph, document_id),
    }


@router.get("/api/register.csv")
def register_csv(as_of: date | None = None) -> Response:
    register = GraphFactsRegister(get_framework(), as_of=as_of or _today())
    return Response(
        register.to_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="graph_facts_register.csv"'},
    )


@router.get("/api/register.json")
def register_json(as_of: date | None = None) -> Response:
    register = GraphFactsRegister(get_framework(), as_of=as_of or _today())
    return Response(
        register.to_json(),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="graph_facts_register.json"'},
    )


from decidr.api.assessment_history import router as history_router
from decidr.api.automatic_assessment import router as automatic_assessment_router
from decidr.api.corpus import router as corpus_router
from decidr.api.interpretation import router as interpretation_router

app.include_router(auth.router)
app.include_router(router)
from decidr.api.graph_assessment import router as graph_assessment_router
from decidr.api.supplied_assessment import router as supplied_assessment_router

app.include_router(automatic_assessment_router)
app.include_router(corpus_router)
app.include_router(graph_assessment_router)
app.include_router(history_router)
app.include_router(interpretation_router)
app.include_router(supplied_assessment_router)

# Serve the built frontend when it exists, so one process can host the whole app.
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
