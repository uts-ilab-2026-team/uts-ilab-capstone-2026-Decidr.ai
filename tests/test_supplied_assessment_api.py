"""HTTP checks for supplied assessments and stored citation validation."""

from contextlib import closing
from copy import deepcopy
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
URL = "/api/corpus/assess-supplied"


def test_stored_nonapproval_overrides_positive_supplied_authority(client, packet):
    path, body = packet
    with closing(connect(path)) as connection, connection:
        row = connection.execute("SELECT payload_json FROM sources").fetchone()
        source = Source.model_validate_json(row[0])
        source.approval_status = "Never approved"
        upsert_source(connection, source)
    before = path.read_bytes()
    response = client.post(URL, json=body)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["assessment"]["overall_outcome"] == "Insufficient evidence"
    assert result["inputs"][0]["admitted_to_framework"] is False
    assert any("Stored own-document approval" in r for r in result["inputs"][0]["reasons"])
    assert path.read_bytes() == before


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
def packet(tmp_path, monkeypatch):
    path = tmp_path / "corpus.sqlite"
    initialise_database(path)
    source = Source(
        source_id="source-test",
        title="Test policy",
        original_file_path="test.md",
        source_type="policy",
        checksum="a" * 64,
        ingestion_status="ingested",
        lifecycle_status="current",
        approval_status="Approved",
        effective_start_date=date(2025, 1, 1),
    )
    passage = Evidence(
        evidence_id="evidence-test",
        source_id=source.source_id,
        locator="paragraph:1",
        text="Written approval is required.",
        source_type="policy",
        extraction_method="test",
    )
    with closing(connect(path)) as connection, connection:
        upsert_source(connection, source)
        replace_source_evidence(connection, source.source_id, [passage])
    monkeypatch.setenv("DECIDR_CORPUS_DB", str(path))
    item = {
        "stance": "support",
        "mode": "formal",
        "rationale": "Synthetic supplied interpretation.",
        "citations": [
            {
                "evidence_id": passage.evidence_id,
                "source_id": passage.source_id,
                "locator": passage.locator,
                "quotation": passage.text,
                "start": 0,
                "end": len(passage.text),
            }
        ],
        "origin_id": source.source_id,
        "source_class": "approved_policy",
        "approval_key": "approved",
        "scope_matches": True,
        "temporal_matches": True,
        "authority_verified": True,
        "directness": 1.0,
        "specificity": 1.0,
        "completeness": 1.0,
        "judgement_basis": "Supplied synthetic assumptions, not human review.",
        "origin_basis": "One synthetic source.",
    }
    body = {
        "claim_text": "  Written approval is required.  ",
        "facet": passage.text,
        "as_of": "2026-06-17",
        "inputs": [item],
    }
    return path, body


def test_assessment_preserves_qualification_and_database(client, packet):
    path, body = packet
    qualification = deepcopy(body["inputs"][0])
    qualification.update(stance="qualify", scope_matches=None)
    body["inputs"].append(qualification)
    before = path.read_bytes()

    response = client.post(URL, json=body)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["claim_text"] == body["claim_text"]
    assert result["facet"] == body["facet"]
    assert result["status"] == "assessed_supplied_judgements"
    assert result["persisted"] is False
    assert result["assessment"]["formal_outcome"] == "Supported"
    assert result["inputs"][0]["source"]["title"] == "Test policy"
    assert result["inputs"][0]["admitted_to_framework"] is True
    assert result["inputs"][1]["admitted_to_framework"] is False
    assert result["inputs"][1]["interpretation"]["stance"] == "qualify"
    assert result["inputs"][1]["interpretation"]["citations"] == qualification["citations"]
    assert result["inputs"][1]["reasons"]
    assert result["assessment"]["rules_applied"]
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("quotation", "Xritten approval is required."),
        ("locator", "paragraph:2"),
    ],
)
def test_changed_citation_is_rejected(client, packet, field, value):
    _, body = packet
    body["inputs"][0]["citations"][0][field] = value
    assert client.post(URL, json=body).status_code == 422


@pytest.mark.parametrize("field", ["evidence_id", "source_id"])
def test_unknown_citation_identity(client, packet, field):
    _, body = packet
    body["inputs"][0]["citations"][0][field] = "missing"
    assert client.post(URL, json=body).status_code == 404


@pytest.mark.parametrize(
    "field,value",
    [
        ("scope_matches", "true"),
        ("directness", True),
        ("specificity", 1.1),
        ("source_class", "invented"),
        ("approval_key", "invented"),
        ("judgement_basis", "   "),
        ("source", {"lifecycle_status": "current"}),
    ],
)
def test_invalid_judgements_or_client_metadata(client, packet, field, value):
    _, body = packet
    body["inputs"][0][field] = value
    assert client.post(URL, json=body).status_code == 422


@pytest.mark.parametrize("value", ["2026-99-01", "20260617", 1781654400, None])
def test_date_must_be_explicit_iso(client, packet, value):
    _, body = packet
    body["as_of"] = value
    assert client.post(URL, json=body).status_code == 422


def test_missing_database_is_not_created(client, packet, tmp_path, monkeypatch):
    _, body = packet
    missing = tmp_path / "missing" / "corpus.sqlite"
    monkeypatch.setenv("DECIDR_CORPUS_DB", str(missing))
    assert client.post(URL, json=body).status_code == 503
    assert not missing.parent.exists()


def test_authentication_precedes_assessment(packet, monkeypatch):
    _, body = packet
    monkeypatch.delenv("DECIDR_CORPUS_DB", raising=False)
    calls = []

    def reject():
        calls.append(True)
        raise HTTPException(status_code=401, detail="Not authenticated")

    previous = dict(api.app.dependency_overrides)
    api.app.dependency_overrides[api.auth.current_user] = reject
    try:
        with TestClient(api.app) as instance:
            response = instance.post(URL, json=body)
        assert response.status_code == 401
        assert calls == [True]
    finally:
        api.app.dependency_overrides.clear()
        api.app.dependency_overrides.update(previous)


@pytest.mark.parametrize("verified", [False, True])
def test_independence_judgement_roundtrip(client, packet, verified):
    path, body = packet
    before = path.read_bytes()
    body["inputs"][0].update(
        independence_verified=verified,
        independence_basis="Synthetic packet-relative independence judgement.",
    )
    response = client.post(URL, json=body)
    assert response.status_code == 200, response.text
    saved = response.json()["inputs"][0]["supplied_judgements"]
    assert saved["independence_verified"] is verified
    assert saved["independence_basis"] == body["inputs"][0]["independence_basis"]
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "fields",
    [
        {"independence_verified": "true"},
        {"independence_verified": True},
        {"independence_verified": True, "independence_basis": " "},
        {"independence_basis": 123},
    ],
)
def test_invalid_independence_judgement(client, packet, fields):
    _, body = packet
    body["inputs"][0].update(fields)
    assert client.post(URL, json=body).status_code == 422


def test_legacy_request_defaults_to_unverified(client, packet):
    _, body = packet
    response = client.post(URL, json=body)
    assert response.status_code == 200
    result = response.json()
    assert result["inputs"][0]["supplied_judgements"]["independence_verified"] is False
    assert any(
        "unverified" in reason for reason in result["assessment"]["evidence"][0]["limitations"]
    )


@pytest.mark.parametrize(
    "target,mode",
    [
        ("recorded_statement", "observed"),
        ("underlying_event", "observed"),
        ("formal_rule", "formal"),
    ],
)
def test_targeted_assessment_roundtrip(client, packet, target, mode):
    path, body = packet
    before = path.read_bytes()
    body["assessment_target"] = target
    body["inputs"][0].update(
        mode=mode,
        evidence_target=target,
        target_basis="Synthetic supplied target; no semantic verification.",
    )
    response = client.post(URL, json=body)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["assessment_target"] == target
    assert result["target_validation"] == "supplied_declarations_checked"
    assert result["inputs"][0]["admitted_to_framework"] is True
    assert result["inputs"][0]["supplied_judgements"]["evidence_target"] == target
    assert path.read_bytes() == before


def test_statement_is_not_admitted_as_event(client, packet):
    _, body = packet
    body["assessment_target"] = "underlying_event"
    body["inputs"][0].update(
        mode="observed",
        evidence_target="recorded_statement",
        target_basis="The record establishes only the statement.",
    )
    result = client.post(URL, json=body).json()
    assert result["assessment"]["overall_outcome"] == "Insufficient evidence"
    assert result["inputs"][0]["admitted_to_framework"] is False
    assert result["inputs"][0]["interpretation"]["citations"] == body["inputs"][0]["citations"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("evidence_target", "invented"),
        ("evidence_target", None),
        ("target_basis", 12),
    ],
)
def test_invalid_target_fields(client, packet, field, value):
    _, body = packet
    body["inputs"][0][field] = value
    assert client.post(URL, json=body).status_code == 422


def test_explicit_evidence_target_requires_basis(client, packet):
    _, body = packet
    body["assessment_target"] = "formal_rule"
    body["inputs"][0]["evidence_target"] = "formal_rule"
    assert client.post(URL, json=body).status_code == 422


def test_legacy_api_target_is_disclosed(client, packet):
    _, body = packet
    result = client.post(URL, json=body).json()
    assert result["assessment_target"] == "unspecified"
    assert result["target_validation"] == "not_performed_legacy"


def test_valid_quote_does_not_establish_semantic_or_authority_verification(client, packet):
    path, body = packet
    before = path.read_bytes()
    # Deliberately false supplied relationship: the endpoint is not an interpreter.
    body["claim_text"] = "Written approval is never required."
    body["facet"] = body["claim_text"]
    body["inputs"][0].update(
        independence_verified=True,
        independence_basis="Caller assertion only; no independent verification.",
    )
    response = client.post(URL, json=body)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["assessment"]["formal_outcome"] == "Supported"
    assurance = result["assurance"]
    assert assurance["outcome_basis"] == "conditional_on_supplied_judgements"
    assert assurance["citation_validation"] == "exact_spans_and_identities_checked"
    assert assurance["semantic_verification"] == "not_performed"
    assert assurance["authority_verification"] == "caller_declared_not_independently_verified"
    assert assurance["independence_verification"] == "caller_declared_with_consistency_checks"
    assert assurance["human_review"] == "not_established_by_this_request"
    assert result["status"] == "assessed_supplied_judgements"
    assert result["inputs"][0]["supplied_judgements"]["independence_verified"] is True
    assert path.read_bytes() == before


def test_supplied_class_and_quality_remain_distinct_from_stored_source(client, packet):
    _, body = packet
    body["inputs"][0].update(
        source_class="interview",
        approval_key="unknown",
        directness=0.4,
        specificity=0.5,
        completeness=0.6,
    )
    response = client.post(URL, json=body)
    assert response.status_code == 200, response.text
    result = response.json()
    item = result["inputs"][0]
    assert item["source"]["source_type"] == "policy"
    assert item["source"]["approval_status"] == "Approved"
    assert item["supplied_judgements"]["source_class"] == "interview"
    assert item["supplied_judgements"]["approval_key"] == "unknown"
    assert item["supplied_judgements"]["directness"] == 0.4
    assert item["supplied_judgements"]["specificity"] == 0.5
    assert item["supplied_judgements"]["completeness"] == 0.6
    assert (
        result["assurance"]["source_class_and_approval_key"] == "caller_supplied_configured_keys"
    )
    assert (
        result["assurance"]["quality_scores"] == "caller_supplied_not_calibrated_by_this_endpoint"
    )


@pytest.mark.parametrize("field", ["assurance", "review_status", "config_version"])
def test_client_cannot_inject_assurance_or_review_status(client, packet, field):
    _, body = packet
    body[field] = "verified"
    response = client.post(URL, json=body)
    assert response.status_code == 422


def test_assurance_present_when_no_input_is_admitted(client, packet):
    _, body = packet
    body["inputs"][0].update(stance="qualify", authority_verified=None)
    response = client.post(URL, json=body)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["inputs"][0]["admitted_to_framework"] is False
    assert result["inputs"][0]["supplied_judgements"]["authority_verified"] is None
    assert result["assurance"]["semantic_verification"] == "not_performed"
    assert result["assurance"]["outcome_basis"] == "conditional_on_supplied_judgements"
