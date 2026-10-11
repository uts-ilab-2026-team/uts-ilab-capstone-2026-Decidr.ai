"""Automatic results remain conditional and preserve immutable evidence for review."""

from contextlib import closing
from datetime import date
import importlib

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
RULE = "Any discount of at least 20% off list price on a new-business deal requires written approval from Finance before the deal is marked won."
URL = "/api/corpus/assess-automatic"
SAVE = "/api/assessments/automatic"


@pytest.fixture
def setup(tmp_path, monkeypatch):
    path = tmp_path / "corpus.sqlite"
    initialise_database(path)
    source = Source(
        source_id="s",
        title="Policy",
        original_file_path="policy.md",
        source_type="policy",
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
        text=RULE,
        source_type="policy",
        extraction_method="test",
    )

    def store():
        with closing(connect(path)) as connection, connection:
            upsert_source(connection, source)
            replace_source_evidence(connection, "s", [passage])

    store()
    monkeypatch.setenv("DECIDR_CORPUS_DB", str(path))
    monkeypatch.setenv("DECIDR_ASSESSMENT_DB", str(tmp_path / "history.sqlite"))
    previous = dict(api.app.dependency_overrides)
    api.app.dependency_overrides[api.auth.current_user] = lambda: {"id": 1}
    with TestClient(api.app) as client:
        yield client, source, passage, store
    api.app.dependency_overrides.clear()
    api.app.dependency_overrides.update(previous)


def body(**changes):
    return {"claim": RULE, "as_of": "2026-06-17", **changes}


def test_supported_wording_does_not_invent_authority(setup):
    client, _, passage, _ = setup
    response = client.post(URL, json=body())
    assert response.status_code == 200, response.text
    result = response.json()
    item = result["inputs"][0]
    assert item["interpretation"]["stance"] == "support"
    assert item["supplied_judgements"]["directness"] == 1
    assert item["supplied_judgements"]["authority_verified"] is None
    assert item["supplied_judgements"]["independence_verified"] is False
    assert not item["admitted_to_framework"]
    assert result["assessment"]["overall_outcome"] == "Insufficient evidence"
    citation = item["interpretation"]["citations"][0]
    assert passage.text[citation["start"] : citation["end"]] == citation["quotation"]
    assert result["assurance"]["human_review"] == "pending"


@pytest.mark.parametrize(
    "text",
    [
        RULE.replace("Finance", "Sales"),
        RULE.replace("at least 20%", "above 20%"),
        RULE + " Except for renewals.",
        "Written approval is required.",
    ],
)
def test_unsupported_comparisons_are_not_support_or_contradiction(setup, text):
    client, _, passage, store = setup
    passage.text = text
    store()
    result = client.post(URL, json=body()).json()
    assert all(
        x["interpretation"]["stance"] in {"unresolved", "context"} for x in result["inputs"]
    )
    assert result["assessment"]["overall_outcome"] == "Insufficient evidence"


def test_original_claim_optional_facet_and_no_matches(setup):
    client, *_ = setup
    original = "  My broader original claim.  "
    result = client.post(URL, json=body(claim=original, facet=RULE)).json()
    assert result["claim_text"] == original
    assert result["facet"] == RULE
    result = client.post(URL, json=body(claim="zzxqqzz")).json()
    assert result["inputs"] == []
    assert result["assessment"]["overall_outcome"] == "Insufficient evidence"


@pytest.mark.parametrize(
    "field,value",
    [
        ("derived_from_source_id", "missing-parent"),
        ("approval_status", "Not approved"),
        ("lifecycle_status", "draft"),
        ("effective_start_date", date(2027, 1, 1)),
        ("superseded_date", date(2026, 6, 17)),
    ],
)
def test_safeguards_retain_inputs_without_scoring(setup, field, value):
    client, source, _, store = setup
    setattr(source, field, value)
    store()
    response = client.post(URL, json=body())
    assert response.status_code == 200, response.text
    result = response.json()
    assert len(result["inputs"]) == 1
    assert not result["inputs"][0]["admitted_to_framework"]


def test_frozen_history_retry_and_review_revision(setup):
    client, _, passage, store = setup
    request = body(request_id="automatic-1")
    response = client.post(SAVE, json=request)
    assert response.status_code == 201, response.text
    saved = response.json()
    snapshot = saved["snapshot"]
    assert snapshot["record_type"] == "automatic_assessment"
    assert snapshot["response"]["persisted"] is True
    assert snapshot["interpretation"]["proposals"][0]["authority_context"]
    packet = snapshot["request"]
    packet["inputs"][0]["authority_verified"] = True
    packet["inputs"][0]["judgement_basis"] = "Synthetic reviewer authority assumption."
    reviewed = client.post(
        "/api/assessments",
        json={
            "request_id": "review-1",
            "assessment": packet,
            "parent_run_id": snapshot["run_id"],
            "revision_reason": "Review authority evidence",
        },
    )
    assert reviewed.status_code == 201, reviewed.text
    assert reviewed.json()["snapshot"]["response"]["assessment"]["overall_outcome"] == "Supported"
    passage.text = "Changed after assessment."
    store()
    assert (
        client.post(SAVE, json=request).json()
        == client.get("/api/assessments/" + snapshot["run_id"]).json()
    )
    assert (
        client.get("/api/assessments/" + snapshot["run_id"]).json()["snapshot"]["response"][
            "assessment"
        ]["overall_outcome"]
        == "Insufficient evidence"
    )
    assert client.post(SAVE, json={**request, "claim": "different"}).status_code == 409
    api.app.dependency_overrides[api.auth.current_user] = lambda: {"id": 2}
    assert client.get("/api/assessments/" + snapshot["run_id"]).status_code == 404


def test_request_validation_and_authentication(setup):
    client, *_ = setup
    for changes in ({"as_of": "tomorrow"}, {"claim": " "}, {"authority_verified": True}):
        assert client.post(URL, json=body(**changes)).status_code == 422
    api.app.dependency_overrides.pop(api.auth.current_user)
    assert client.post(URL, json=body()).status_code == 401
    assert client.post(SAVE, json=body(request_id="one")).status_code == 401


def test_matching_rule_with_compatible_surroundings_is_explained_and_frozen(setup):
    client, _, passage, store = setup
    passage.text = (
        "1. "
        + RULE
        + "\n2. Approval must be recorded in the CRM's `approval_record` field, referencing the approver and date."
        + "\n3. Discounts below 20% may be approved by the deal's Account Executive without further sign-off."
        + "\n4. This policy applies to new-business deals. Renewal discounting is governed separately by POL-06."
    )
    store()
    response = client.post(SAVE, json=body(request_id="context-regression"))
    assert response.status_code == 201, response.text
    saved = response.json()
    result = saved["snapshot"]["response"]
    assert result["rule_comparison"]["message"] == "Rule wording matches; authority unresolved"
    item = result["inputs"][0]
    assert item["interpretation"]["stance"] == "support"
    assert item["supplied_judgements"]["authority_verified"] is None
    assert not item["admitted_to_framework"]
    assert result["assessment"]["overall_outcome"] == "Insufficient evidence"
    context = result["proposals"][0]["passage_context"]
    assert context["compatible"]
    assert context["citation"]["quotation"] == passage.text
    quote = item["interpretation"]["citations"][0]
    assert passage.text[quote["start"] : quote["end"]] == quote["quotation"]
    passage.text += " Except for urgent deals."
    store()
    changed = client.post(URL, json=body()).json()
    assert changed["rule_comparison"]["status"] == "unresolved"
    assert changed["inputs"][0]["interpretation"]["stance"] == "unresolved"
    assert client.get("/api/assessments/" + saved["snapshot"]["run_id"]).json() == saved


@pytest.mark.parametrize("structured", [False, True])
def test_automatic_authority_chain_can_reach_supported_and_is_frozen(setup, structured):
    from test_authority_resolution import chain
    import os
    from pathlib import Path

    from test_structured_adoption import structured_chain

    sources, passages = structured_chain() if structured else chain()
    client, _, _, _ = setup
    with closing(connect(Path(os.environ["DECIDR_CORPUS_DB"]))) as connection, connection:
        for source in sources.values():
            upsert_source(connection, source)
            replace_source_evidence(
                connection,
                source.source_id,
                [p for p in passages if p.source_id == source.source_id],
            )
    response = client.post(SAVE, json=body(request_id="authority-chain"))
    assert response.status_code == 201, response.text
    saved = response.json()
    result = saved["snapshot"]["response"]
    assert result["assessment"]["overall_outcome"] == "Supported"
    assert result["rule_comparison"]["status"] == "wording_matches_authority_resolved"
    policy = next(i for i in result["inputs"] if i["source"]["source_id"] == "test:POL-01")
    assert policy["admitted_to_framework"]
    assert policy["supplied_judgements"]["independence_verified"] is False
    proposal = next(p for p in result["proposals"] if p["source_id"] == "test:POL-01")
    assert proposal["authority_resolution"]["authority_verified"] is True
    assert proposal["authority_resolution"]["citations"]
    assert client.get("/api/assessments/" + saved["snapshot"]["run_id"]).json() == saved
