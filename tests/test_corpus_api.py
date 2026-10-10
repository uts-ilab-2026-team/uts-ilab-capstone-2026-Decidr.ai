"""Exercise the corpus route through the authenticated application."""

from contextlib import closing
import importlib
import sqlite3

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


@pytest.fixture
def corpus_db(tmp_path, monkeypatch):
    path = tmp_path / "corpus.sqlite3"
    initialise_database(path)
    source = Source(
        source_id="phase2:test-policy",
        title="Travel approval policy",
        original_file_path="test-policy.md",
        source_type="policy",
        checksum="a" * 64,
        ingestion_status="ingested",
        approval_status="Approved",
    )
    passage = Evidence(
        evidence_id="EV-test-policy",
        source_id=source.source_id,
        locator="heading:Travel approval#block:001",
        text="Travel approval requires a written manager decision.",
        source_type="policy",
        section="Travel approval",
        heading="Travel approval",
        paragraph=1,
        extraction_method="markdown_block",
    )
    with closing(connect(path)) as connection:
        with connection:
            upsert_source(connection, source)
            replace_source_evidence(connection, source.source_id, [passage])
    monkeypatch.setenv("DECIDR_CORPUS_DB", str(path))
    return path, passage


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


def test_search_preserves_claim_citations_and_does_not_write(client, corpus_db):
    path, passage = corpus_db
    before = path.read_bytes()
    claim = "  Travel approval requires a manager decision.  "
    response = client.post("/api/corpus/search", json={"claim": claim})
    assert response.status_code == 200
    body = response.json()
    assert body["claim"] == claim
    assert body["status"] == "retrieved_unassessed"
    assert body["assessment"] is None
    assert body["indexed_source_count"] == 1
    assert body["indexed_evidence_count"] == 1
    returned = body["ranked_groups"][0]["passages"][0]
    assert returned["evidence"] == passage.model_dump(mode="json")
    assert returned["relationship"] is None
    assert returned["interpretation_status"] == "unassessed"
    assert returned["retrieval"]["lexical_rank"] == 1
    assert returned["retrieval"]["semantic_rank"] is None
    assert body["sources"][0]["approval_status"] == "Approved"
    assert path.read_bytes() == before


def test_no_match_does_not_create_a_verdict(client, corpus_db):
    response = client.post(
        "/api/corpus/search", json={"claim": "zzzxxyyqq"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ranked_groups"] == []
    assert body["additional_linked_groups"] == []
    assert body["assessment"] is None
    assert body["status"] == "retrieved_unassessed"


@pytest.mark.parametrize("payload", [
    {"claim": "   "},
    {"claim": "Travel approval", "limit": 0},
    {"claim": "Travel approval", "limit": 51},
    {"claim": "Travel approval", "limit": True},
    {"claim": "Travel approval", "unexpected": True},
])
def test_invalid_requests_are_rejected(client, payload):
    assert client.post("/api/corpus/search", json=payload).status_code == 422


def test_unconfigured_database(client, monkeypatch):
    monkeypatch.delenv("DECIDR_CORPUS_DB", raising=False)
    assert client.post(
        "/api/corpus/search", json={"claim": "Travel approval"}
    ).status_code == 503


def test_missing_database_is_not_created(client, tmp_path, monkeypatch):
    path = tmp_path / "missing" / "corpus.sqlite3"
    monkeypatch.setenv("DECIDR_CORPUS_DB", str(path))
    assert client.post(
        "/api/corpus/search", json={"claim": "Travel approval"}
    ).status_code == 503
    assert not path.parent.exists()


def test_invalid_schema_returns_unavailable(client, tmp_path, monkeypatch):
    path = tmp_path / "unrelated.sqlite3"
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE unrelated (value TEXT)")
        connection.commit()
    monkeypatch.setenv("DECIDR_CORPUS_DB", str(path))
    assert client.post(
        "/api/corpus/search", json={"claim": "Travel approval"}
    ).status_code == 503


def test_route_keeps_authentication_dependency(monkeypatch):
    from fastapi import HTTPException

    calls = []

    def reject_unauthenticated():
        calls.append(True)
        raise HTTPException(status_code=401, detail="Not authenticated")

    # No database is configured: authentication must reject the request first.
    monkeypatch.delenv("DECIDR_CORPUS_DB", raising=False)
    previous = dict(api.app.dependency_overrides)
    api.app.dependency_overrides[api.auth.current_user] = reject_unauthenticated
    try:
        with TestClient(api.app) as client:
            response = client.post(
                "/api/corpus/search",
                json={"claim": "Travel approval"},
            )
        assert response.status_code == 401
        assert response.json()["detail"] == "Not authenticated"
        assert calls == [True]
    finally:
        api.app.dependency_overrides.clear()
        api.app.dependency_overrides.update(previous)


def test_citation_returns_exact_evidence_and_source_without_writes(client, corpus_db):
    path, passage = corpus_db
    before = path.read_bytes()
    response = client.get(
        f"/api/corpus/evidence/{passage.evidence_id}",
        params={"source_id": passage.source_id},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["evidence"] == passage.model_dump(mode="json")
    assert body["source"]["source_id"] == passage.source_id
    assert body["source"]["approval_status"] == "Approved"
    assert body["interpretation_status"] == "unassessed"
    assert body["relationship"] is None
    assert body["index_scope"] == "current"
    assert path.read_bytes() == before


@pytest.mark.parametrize("evidence_id,source_id", [
    ("EV-missing", "phase2:test-policy"),
    ("EV-test-policy", "phase2:wrong-source"),
    ("EV-test-policy", "' OR 1=1 --"),
])
def test_citation_rejects_unknown_or_mismatched_identity(
    client, corpus_db, evidence_id, source_id
):
    response = client.get(
        f"/api/corpus/evidence/{evidence_id}",
        params={"source_id": source_id},
    )
    assert response.status_code == 404


def test_citation_requires_source_identity(client, corpus_db):
    assert client.get("/api/corpus/evidence/EV-test-policy").status_code == 422


def test_citation_missing_database_is_not_created(client, tmp_path, monkeypatch):
    path = tmp_path / "not-created" / "corpus.sqlite3"
    monkeypatch.setenv("DECIDR_CORPUS_DB", str(path))
    response = client.get(
        "/api/corpus/evidence/EV-test-policy",
        params={"source_id": "phase2:test-policy"},
    )
    assert response.status_code == 503
    assert not path.parent.exists()


def test_citation_keeps_authentication_dependency(monkeypatch):
    from fastapi import HTTPException

    calls = []

    def reject():
        calls.append(True)
        raise HTTPException(status_code=401, detail="Not authenticated")

    monkeypatch.delenv("DECIDR_CORPUS_DB", raising=False)
    previous = dict(api.app.dependency_overrides)
    api.app.dependency_overrides[api.auth.current_user] = reject
    try:
        with TestClient(api.app) as instance:
            response = instance.get(
                "/api/corpus/evidence/EV-test-policy",
                params={"source_id": "phase2:test-policy"},
            )
        assert response.status_code == 401
        assert calls == [True]
    finally:
        api.app.dependency_overrides.clear()
        api.app.dependency_overrides.update(previous)
