"""HTTP integration for unreviewed proposal drafts and existing assurance."""

from contextlib import closing
from datetime import date
import importlib

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from decidr.retrieval_models import Evidence, Source
from decidr.retrieval_store import (
    connect,
    initialise_database,
    replace_source_evidence,
    upsert_source,
)

api = importlib.import_module("decidr.api.app")
URL = "/api/corpus/interpret"


@pytest.fixture
def client():
    previous = dict(api.app.dependency_overrides)
    api.app.dependency_overrides[api.auth.current_user] = lambda: {"id": 1}
    try:
        with TestClient(api.app) as instance:
            yield instance
    finally:
        api.app.dependency_overrides.clear()
        api.app.dependency_overrides.update(previous)


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    path = tmp_path / "corpus.sqlite"
    initialise_database(path)
    source = Source(
        source_id="s",
        title="Policy",
        original_file_path="/private/path/policy.md",
        source_type="policy",
        checksum="a" * 64,
        ingestion_status="ingested",
        lifecycle_status="current",
        approval_status="Approved",
        effective_start_date=date(2025, 1, 1),
    )
    evidence = Evidence(
        evidence_id="e",
        source_id="s",
        locator="p:1",
        text="Written approval is required.",
        source_type="policy",
        extraction_method="test",
    )
    with closing(connect(path)) as connection, connection:
        upsert_source(connection, source)
        replace_source_evidence(connection, "s", [evidence])
    monkeypatch.setenv("DECIDR_CORPUS_DB", str(path))
    return path, source


def body(**changes):
    values = {
        "claim": "Written approval is required.",
        "as_of": "2026-06-17",
        "assessment_target": "formal_rule",
    }
    values.update(changes)
    return values


def test_unedited_proposal_cannot_decide_credibility(client, corpus):
    path, _ = corpus
    before = path.read_bytes()
    response = client.post(URL, json=body())
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["assessment_ready"] is False
    assert result["review_status"] == "unreviewed"
    assert result["proposal_count"] == 1
    proposal = result["proposals"][0]
    assert proposal["suggested_input"]["stance"] == "support"
    assert proposal["review_required"] is True
    assert proposal["evidence"]["text"] == "Written approval is required."
    assert "original_file_path" not in proposal["source_context"]
    assessed = client.post("/api/corpus/assess-supplied", json=result["assessment_request"])
    assert assessed.status_code == 200, assessed.text
    data = assessed.json()
    assert data["assessment"]["overall_outcome"] == "Insufficient evidence"
    assert data["assurance"]["semantic_verification"] == "not_performed"
    assert all(x["edge_id"] is None for x in data["inputs"])
    assert path.read_bytes() == before


def test_reviewed_judgements_still_use_existing_assessment_contract(client, corpus):
    packet = client.post(URL, json=body()).json()["assessment_request"]
    item = packet["inputs"][0]
    item.update(
        authority_verified=True,
        directness=1.0,
        specificity=1.0,
        completeness=1.0,
        judgement_basis="Synthetic supplied review assumptions for this test.",
    )
    response = client.post("/api/corpus/assess-supplied", json=packet)
    assert response.status_code == 200, response.text
    assert response.json()["assessment"]["overall_outcome"] == "Supported"
    assert response.json()["assurance"]["human_review"] == "not_established_by_this_request"


def test_facet_controls_search_and_comparison_preserving_claim(client, corpus):
    claim = "  unrelated original claim  "
    result = client.post(
        URL, json=body(claim=claim, facet="Written approval is not required.")
    ).json()
    assert result["claim"] == claim
    assert result["assessment_request"]["claim_text"] == claim
    assert result["proposals"][0]["suggested_input"]["stance"] == "contradict"


def test_no_match_is_explicit_no_draft(client, corpus):
    result = client.post(URL, json=body(claim="zzxqqzz")).json()
    assert result["proposal_count"] == 0
    assert result["assessment_request"] is None
    assert result["draft_blockers"]


@pytest.mark.parametrize(
    "change",
    [
        {"claim": " "},
        {"facet": " "},
        {"as_of": "tomorrow"},
        {"as_of": "2026-02-30"},
        {"assessment_target": "anything"},
        {"max_inputs": 51},
        {"max_inputs": True},
        {"ranked_group_limit": 0},
        {"extra": "field"},
    ],
)
def test_invalid_requests_rejected(client, corpus, change):
    assert client.post(URL, json=body(**change)).status_code == 422


def test_authentication_dependency_is_used(corpus):
    previous = dict(api.app.dependency_overrides)
    calls = []

    def deny():
        calls.append(True)
        raise HTTPException(status_code=401, detail="Not authenticated")

    api.app.dependency_overrides[api.auth.current_user] = deny
    try:
        with TestClient(api.app) as client:
            response = client.post(URL, json=body())
        assert response.status_code == 401
        assert calls == [True]
    finally:
        api.app.dependency_overrides.clear()
        api.app.dependency_overrides.update(previous)


def test_missing_source_parent_blocks_assessment_draft(client, corpus):
    path, source = corpus
    source.derived_from_source_id = "absent-parent"
    with closing(connect(path)) as connection, connection:
        upsert_source(connection, source)
    result = client.post(URL, json=body()).json()
    assert result["proposal_count"] == 1
    assert result["assessment_request"] is None
    assert result["draft_blockers"]


def test_missing_database_is_unavailable_not_created(client, tmp_path, monkeypatch):
    path = tmp_path / "absent.sqlite"
    monkeypatch.setenv("DECIDR_CORPUS_DB", str(path))
    assert client.post(URL, json=body()).status_code == 503
    assert not path.exists()
