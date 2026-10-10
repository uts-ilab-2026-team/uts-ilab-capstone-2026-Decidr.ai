"""History persists server results, isolates owners and preserves frozen evidence."""

from contextlib import closing
from copy import deepcopy
from datetime import date
import importlib
import json
import sqlite3
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from decidr.assessment_history import content_hash
from decidr.retrieval_models import Evidence, Source
from decidr.retrieval_store import (
    connect,
    initialise_database,
    replace_source_evidence,
    upsert_source,
)

api = importlib.import_module("decidr.api.app")
supplied = importlib.import_module("decidr.api.supplied_assessment")
URL = "/api/assessments"


@pytest.fixture
def setup(tmp_path, monkeypatch):
    corpus = tmp_path / "corpus.sqlite"
    history = tmp_path / "history.sqlite"
    initialise_database(corpus)
    source = Source(
        source_id="s",
        title="Policy",
        source_type="policy",
        original_file_path="policy.md",
        checksum="a" * 64,
        ingestion_status="ingested",
        lifecycle_status="current",
        approval_status="Approved",
        effective_start_date=date(2025, 1, 1),
    )
    passage = Evidence(
        evidence_id="e",
        source_id="s",
        locator="p:1",
        text="Written approval is required.",
        source_type="policy",
        extraction_method="test",
    )
    with closing(connect(corpus)) as connection, connection:
        upsert_source(connection, source)
        replace_source_evidence(connection, "s", [passage])
    monkeypatch.setenv("DECIDR_CORPUS_DB", str(corpus))
    monkeypatch.setenv("DECIDR_ASSESSMENT_DB", str(history))
    item = {
        "stance": "support",
        "mode": "formal",
        "rationale": "Synthetic supplied judgement.",
        "citations": [
            {
                "evidence_id": "e",
                "source_id": "s",
                "locator": "p:1",
                "quotation": passage.text,
                "start": 0,
                "end": len(passage.text),
            }
        ],
        "origin_id": "s",
        "source_class": "approved_policy",
        "approval_key": "approved",
        "scope_matches": True,
        "temporal_matches": True,
        "authority_verified": True,
        "directness": 1.0,
        "specificity": 1.0,
        "completeness": 1.0,
        "judgement_basis": "Synthetic supplied assumptions.",
        "origin_basis": "Single test source.",
        "evidence_target": "formal_rule",
        "target_basis": "Supplied rule target.",
    }
    body = {
        "request_id": str(uuid4()),
        "assessment": {
            "claim_text": "  Written approval is required.  ",
            "facet": passage.text,
            "assessment_target": "formal_rule",
            "as_of": "2026-06-17",
            "inputs": [item],
        },
    }
    return corpus, history, body


@pytest.fixture
def client():
    previous = dict(api.app.dependency_overrides)
    api.app.dependency_overrides[api.auth.current_user] = lambda: {"id": 1}
    try:
        with TestClient(api.app) as value:
            yield value
    finally:
        api.app.dependency_overrides.clear()
        api.app.dependency_overrides.update(previous)


def saved(client, body):
    response = client.post(URL, json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_frozen_response_and_export_survive_missing_corpus_and_config(client, setup, monkeypatch):
    corpus, history, body = setup
    before = corpus.read_bytes()
    record = saved(client, body)
    snapshot = record["snapshot"]
    run_id = snapshot["run_id"]
    assert record["snapshot_sha256"] == content_hash(snapshot)
    assert snapshot["request"] == supplied.SuppliedAssessmentRequest.model_validate(
        body["assessment"]
    ).model_dump(mode="json")
    assert snapshot["response"]["assessment"]["overall_outcome"] == "Supported"
    assert snapshot["response"]["persisted"] is True
    assert snapshot["response"]["index_scope"] == "frozen"
    assert snapshot["response"]["assurance"]["human_review"] == "not_established_by_this_request"
    assert snapshot["review_status"] == "not_established"
    assert snapshot["record_type"] == "conditional_supplied_assessment"
    assert snapshot["configuration"]["materiality_threshold"] == 0.55
    assert snapshot["evidence"][0]["text"] == "Written approval is required."
    assert snapshot["sources"][0]["title"] == "Policy"
    assert len(snapshot["provenance"]["corpus_index_sha256"]) == 64
    assert snapshot["provenance"]["implementation"]["files"]
    assert corpus.read_bytes() == before
    monkeypatch.delenv("DECIDR_CORPUS_DB")
    monkeypatch.setattr(supplied, "CONFIG_PATH", corpus.parent / "missing-config.json")
    corpus.unlink()
    assert client.get(f"{URL}/{run_id}").json() == record
    exported = client.get(f"{URL}/{run_id}/export")
    assert exported.status_code == 200
    assert exported.json() == record
    assert "attachment" in exported.headers["content-disposition"]
    assert client.post(URL, json=body).json() == record
    assert len(client.get(URL).json()["items"]) == 1
    assert history.exists()


def test_same_request_id_different_body_conflicts(client, setup):
    _, history, body = setup
    saved(client, body)
    before = history.read_bytes()
    body["assessment"]["as_of"] = "2026-06-18"
    assert client.post(URL, json=body).status_code == 409
    assert history.read_bytes() == before


def test_owner_isolation_including_parent_and_retry(client, setup):
    _, _, body = setup
    record = saved(client, body)
    run_id = record["snapshot"]["run_id"]
    api.app.dependency_overrides[api.auth.current_user] = lambda: {"id": 2}
    assert client.get(URL).json()["items"] == []
    assert client.get(f"{URL}/{run_id}").status_code == 404
    assert client.get(f"{URL}/{run_id}/export").status_code == 404
    revision = deepcopy(body)
    revision.update(request_id=str(uuid4()), parent_run_id=run_id, revision_reason="Review")
    assert client.post(URL, json=revision).status_code == 404
    other = saved(client, body)
    assert other["snapshot"]["run_id"] != run_id
    assert other["snapshot"]["owner_id"] == 2


def test_revision_preserves_parent_and_records_changed_corpus_and_config(
    client, setup, monkeypatch
):
    corpus, _, body = setup
    parent = saved(client, body)
    parent_id = parent["snapshot"]["run_id"]
    with closing(connect(corpus)) as connection, connection:
        raw = json.loads(
            connection.execute("SELECT payload_json FROM sources WHERE source_id='s'").fetchone()[
                0
            ]
        )
        raw["title"] = "Updated policy title"
        upsert_source(connection, Source.model_validate(raw))
    config = json.loads(supplied.CONFIG_PATH.read_text())
    config["materiality_threshold"] = 0.99
    path = corpus.parent / "config.json"
    path.write_text(json.dumps(config))
    monkeypatch.setattr(supplied, "CONFIG_PATH", path)
    child_body = deepcopy(body)
    child_body.update(
        request_id=str(uuid4()),
        parent_run_id=parent_id,
        revision_reason="Reassess current index and configuration",
    )
    child = saved(client, child_body)
    assert child["snapshot"]["parent_snapshot_sha256"] == parent["snapshot_sha256"]
    assert (
        child["snapshot"]["response"]["assessment"]["overall_outcome"] == "Insufficient evidence"
    )
    assert child["snapshot"]["configuration"]["materiality_threshold"] == 0.99
    assert (
        child["snapshot"]["provenance"]["corpus_index_sha256"]
        != parent["snapshot"]["provenance"]["corpus_index_sha256"]
    )
    assert client.get(f"{URL}/{parent_id}").json() == parent
    assert child["snapshot"]["sources"][0]["title"] == "Updated policy title"
    assert len(client.get(URL).json()["items"]) == 2


@pytest.mark.parametrize(
    "field,value",
    [
        ("claim_text", "Another claim."),
        ("facet", "Another facet."),
        ("assessment_target", "recorded_statement"),
    ],
)
def test_revision_cannot_silently_change_claim_identity(client, setup, field, value):
    _, _, body = setup
    parent = saved(client, body)
    body.update(
        request_id=str(uuid4()),
        parent_run_id=parent["snapshot"]["run_id"],
        revision_reason="Revision",
    )
    body["assessment"][field] = value
    assert client.post(URL, json=body).status_code == 409
    assert len(client.get(URL).json()["items"]) == 1


def test_qualification_and_exclusions_survive_save(client, setup):
    _, _, body = setup
    qualifier = deepcopy(body["assessment"]["inputs"][0])
    qualifier.update(stance="qualify", scope_matches=None, rationale="Supplied qualification")
    body["assessment"]["inputs"].append(qualifier)
    result = saved(client, body)["snapshot"]["response"]
    assert len(result["inputs"]) == 2
    assert result["inputs"][1]["interpretation"]["stance"] == "qualify"
    assert result["inputs"][1]["reasons"]
    assert result["inputs"][1]["edge_id"] is None


@pytest.mark.parametrize(
    "action",
    [
        "UPDATE assessment_runs SET created_at='changed'",
        "DELETE FROM assessment_runs",
        "INSERT OR REPLACE INTO assessment_runs SELECT * FROM assessment_runs",
    ],
)
def test_sql_mutations_are_blocked(client, setup, action):
    _, history, body = setup
    record = saved(client, body)
    with (
        sqlite3.connect(history) as connection,
        pytest.raises(sqlite3.IntegrityError, match="append-only"),
    ):
        connection.execute(action)
    assert client.get(f"{URL}/{record['snapshot']['run_id']}").json() == record


def test_corrupt_snapshot_fails_closed(client, setup):
    _, history, body = setup
    record = saved(client, body)
    with sqlite3.connect(history) as connection:
        connection.execute("DROP TRIGGER assessment_no_update")
        connection.execute("UPDATE assessment_runs SET payload_json='{}'")
    assert client.get(f"{URL}/{record['snapshot']['run_id']}").status_code == 503
    assert client.get(URL).status_code == 503


def test_invalid_quote_does_not_create_history_database(client, setup):
    _, history, body = setup
    body["assessment"]["inputs"][0]["citations"][0]["quotation"] = "X" * 29
    body["assessment"]["inputs"][0]["citations"][0]["end"] = 29
    assert client.post(URL, json=body).status_code == 422
    assert not history.exists()


def test_preview_still_does_not_save(client, setup):
    _, history, body = setup
    response = client.post("/api/corpus/assess-supplied", json=body["assessment"])
    assert response.status_code == 200
    assert response.json()["persisted"] is False
    assert not history.exists()


@pytest.mark.parametrize("protected", ["corpus", "auth", "hardlink"])
def test_history_cannot_share_corpus_or_auth_database(client, setup, monkeypatch, protected):
    corpus, history, body = setup
    before = corpus.read_bytes()
    if protected == "corpus":
        monkeypatch.setenv("DECIDR_ASSESSMENT_DB", str(corpus))
    elif protected == "auth":
        monkeypatch.setenv("DECIDR_AUTH_DB", str(history))
    else:
        history.hardlink_to(corpus)
    assert client.post(URL, json=body).status_code == 503
    assert corpus.read_bytes() == before


def test_existing_unrelated_database_is_not_modified(client, setup):
    _, history, body = setup
    with sqlite3.connect(history) as connection:
        connection.execute("CREATE TABLE unrelated(x TEXT)")
    before = history.read_bytes()
    assert client.post(URL, json=body).status_code == 503
    assert history.read_bytes() == before


def test_empty_read_and_pagination_do_not_create_database(client, setup):
    _, history, _ = setup
    assert client.get(URL).json()["items"] == []
    assert client.get(URL + "?limit=0").status_code == 422
    assert client.get(URL + "?offset=-1").status_code == 422
    assert not history.exists()


@pytest.mark.parametrize(
    "extra", [{"response": {}}, {"owner_id": 2}, {"review_status": "approved"}]
)
def test_client_cannot_supply_server_results_or_owner(client, setup, extra):
    _, history, body = setup
    body.update(extra)
    assert client.post(URL, json=body).status_code == 422
    assert not history.exists()


def test_revision_requires_reason(client, setup):
    _, history, body = setup
    body["parent_run_id"] = str(uuid4())
    assert client.post(URL, json=body).status_code == 422
    assert not history.exists()


def test_all_history_routes_use_authentication(setup):
    _, history, body = setup
    previous = dict(api.app.dependency_overrides)

    def deny():
        raise HTTPException(status_code=401, detail="Not authenticated")

    api.app.dependency_overrides[api.auth.current_user] = deny
    try:
        with TestClient(api.app) as client:
            assert client.post(URL, json=body).status_code == 401
            for suffix in ["", "/" + str(uuid4()), "/" + str(uuid4()) + "/export"]:
                assert client.get(URL + suffix).status_code == 401
    finally:
        api.app.dependency_overrides.clear()
        api.app.dependency_overrides.update(previous)
    assert not history.exists()


def test_concurrent_retry_saves_once(client, setup):
    from concurrent.futures import ThreadPoolExecutor

    _, _, body = setup
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: client.post(URL, json=body), range(4)))
    assert sorted(r.status_code for r in responses) == [200, 200, 200, 201]
    assert len({r.json()["snapshot"]["run_id"] for r in responses}) == 1
    assert len(client.get(URL).json()["items"]) == 1


def test_failed_revision_rolls_back_without_extra_record(client, setup):
    _, history, body = setup
    parent = saved(client, body)
    revision = deepcopy(body)
    revision.update(
        request_id=str(uuid4()),
        parent_run_id=parent["snapshot"]["run_id"],
        revision_reason="Review",
    )
    revision["assessment"]["inputs"][0]["citations"][0]["quotation"] = "Z" * 29
    revision["assessment"]["inputs"][0]["citations"][0]["end"] = 29
    before = history.read_bytes()
    assert client.post(URL, json=revision).status_code == 422
    assert history.read_bytes() == before
    assert len(client.get(URL).json()["items"]) == 1


def test_history_configuration_is_explicit(client, setup, monkeypatch):
    _, history, body = setup
    monkeypatch.delenv("DECIDR_ASSESSMENT_DB")
    assert client.post(URL, json=body).status_code == 503
    assert client.get(URL).status_code == 503
    assert not history.exists()
