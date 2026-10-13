"""Save/history plumbing for the graph-engine claim runner.

Stubs ONLY the engine (``build_graph_bundle``) and lets the real ``implementation_manifest`` run,
so this covers exactly the persistence path — append_run / list / snapshot / export / retry — that
had no test after the legacy scorers were retired (and where a stale manifest file-list bug hid).
"""

from datetime import date

from fastapi.testclient import TestClient
import pytest

from decidr import api
from decidr.api import automatic_assessment
from decidr.api.app import app


def _fake_bundle(request) -> dict:
    """A canned graph bundle in the exact shape build_graph_bundle returns (no model needed)."""
    return {
        "response": {
            "claim": request.claim,
            "overall_outcome": "Supported",
            "confidence": "Moderate confidence",
            "facets": [],
            "rules_applied": [],
            "claim_text": request.claim,
            "facet": request.facet or request.claim,
            "as_of": str(request.as_of),
            "status": "assessed_automatically",
            "assessment": {
                "overall_outcome": "Supported",
                "formal_outcome": "Supported",
                "observed_outcome": "Supported",
                "confidence": "Moderate confidence",
            },
            "assurance": {"outcome_basis": "graph_engine_deterministic_scoring"},
        },
        "request": {
            "claim_text": request.claim,
            "facet": request.facet or request.claim,
            "assessment_target": "formal_requirement",
            "as_of": str(request.as_of),
        },
        "provenance": {
            "assessment_method": "graph-credibility-v1",
            "evidence_scope": "graph_guided_lane_balanced_retrieval",
        },
    }


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DECIDR_ASSESSMENT_DB", str(tmp_path / "history.sqlite"))
    monkeypatch.setenv("DECIDR_AUTH_DB", str(tmp_path / "users.sqlite"))
    monkeypatch.delenv("DECIDR_CORPUS_DB", raising=False)
    monkeypatch.setattr(automatic_assessment, "build_graph_bundle", _fake_bundle)
    previous = dict(app.dependency_overrides)
    app.dependency_overrides[api.auth.current_user] = lambda: {"id": 1}
    try:
        with TestClient(app) as instance:
            yield instance
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


BODY = {"claim": "Discounts above 15% require Finance approval.", "as_of": "2026-07-31"}


def test_run_saves_lists_snapshots_and_exports(client):
    saved = client.post("/api/assessments/automatic", json={**BODY, "request_id": "req-1"})
    assert saved.status_code == 201, saved.text
    record = saved.json()
    run_id = record["snapshot"]["run_id"]
    # The saved bundle carries the real provenance manifest (the part that previously crashed).
    assert record["snapshot"]["provenance"]["implementation"]["files"]

    listing = client.get("/api/assessments").json()
    assert [item["run_id"] for item in listing["items"]] == [run_id]
    assert listing["items"][0]["overall_outcome"] == "Supported"
    assert listing["items"][0]["claim_text"] == BODY["claim"]

    snapshot = client.get(f"/api/assessments/{run_id}")
    assert snapshot.status_code == 200
    assert snapshot.json()["snapshot"]["response"]["claim_text"] == BODY["claim"]

    export = client.get(f"/api/assessments/{run_id}/export")
    assert export.status_code == 200
    assert export.headers["content-disposition"].endswith(f'assessment-{run_id}.json"')


def test_identical_request_id_is_an_idempotent_retry(client):
    first = client.post("/api/assessments/automatic", json={**BODY, "request_id": "req-2"})
    assert first.status_code == 201
    again = client.post("/api/assessments/automatic", json={**BODY, "request_id": "req-2"})
    assert again.status_code == 200
    assert again.json()["snapshot"]["run_id"] == first.json()["snapshot"]["run_id"]


def test_history_requires_a_configured_database(client, monkeypatch):
    monkeypatch.delenv("DECIDR_ASSESSMENT_DB", raising=False)
    response = client.post("/api/assessments/automatic", json={**BODY, "request_id": "req-3"})
    assert response.status_code == 503


def test_as_of_must_be_explicit_iso_date(client):
    bad = client.post(
        "/api/assessments/automatic",
        json={"claim": "x", "as_of": "July 2026", "request_id": "req-4"},
    )
    assert bad.status_code == 422


def test_build_graph_bundle_produces_history_summary_keys(monkeypatch):
    """Guard the engine->history contract: the real bundle must carry the keys list_runs reads."""
    from types import SimpleNamespace

    from decidr.api import graph_assessment

    def fake_run(claim, as_of):
        return SimpleNamespace(
            claim_text=claim,
            as_of=as_of,
            verdict=SimpleNamespace(
                overall_outcome="Contested",
                confidence="Lower confidence",
                facets=(),
                rules_applied=(),
            ),
            facet_assessments={},
            split={
                "target": "event",
                "components": [],
                "semantic_validation": {"status": "validated"},
            },
            reading={"findings": []},
            passages=[],
            retrieval={},
            notes=[],
        )

    monkeypatch.setattr(graph_assessment, "_run_claim", fake_run)
    bundle = graph_assessment.build_graph_bundle(
        SimpleNamespace(claim="c", as_of=date(2026, 7, 31), facet=None)
    )
    response = bundle["response"]
    for key in ("overall_outcome", "formal_outcome", "observed_outcome"):
        assert key in response["assessment"]
    assert response["assurance"]["outcome_basis"]
    assert response["status"] == "assessed_automatically"
    assert bundle["request"]["assessment_target"] == "event"
