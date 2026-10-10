from collections.abc import Iterator
import json

from fastapi.testclient import TestClient
from framework import CONFIG_PATH, GRAPH_PATH, GraphCredibilityFramework
import pytest

from decidr.api import app as api_module
from decidr.api.app import app

AS_OF = "2026-07-31"
ACCOUNT = {"name": "Test User", "email": "test@example.com", "password": "correct-horse"}

client = TestClient(app)


@pytest.fixture(autouse=True)
def signed_in(tmp_path, monkeypatch) -> Iterator[None]:
    """Give every test a fresh user store and a signed-in client."""
    monkeypatch.setenv("DECIDR_AUTH_DB", str(tmp_path / "users.db"))
    client.cookies.clear()
    assert client.post("/api/auth/signup", json=ACCOUNT).status_code == 201
    yield
    client.cookies.clear()


def test_claims_register_and_summary() -> None:
    payload = client.get("/api/claims", params={"as_of": AS_OF}).json()
    assert payload["as_of"] == AS_OF
    assert payload["summary"]["claims_assessed"] == len(payload["claims"]) == 3
    assert payload["summary"]["insufficient_evidence"] == 1
    assert payload["summary"]["sources"] == 7


def test_check_claim_assesses_closest_fact() -> None:
    response = client.post(
        "/api/claims/check",
        json={"claim": "Who approves discounts above 15 percent?", "as_of": AS_OF},
    )
    payload = response.json()
    assert payload["matches"][0]["fact_id"] == "fact:discount-new-business"
    assessment = payload["assessment"]
    assert assessment["formal_outcome"] == "Supported"
    assert assessment["observed_outcome"] == "Supported"
    slack = next(
        item for item in assessment["evidence"] if item["document_id"] == "document:COMMS-01"
    )
    assert slack["material"] is False
    assert slack["actor"]["label"] == "Diane Okafor"
    assert slack["document"]["short_id"] == "COMMS-01"
    assert "DEAL-014" in slack["attests_value"]
    assert "CRM approval_record field" in slack["attests_value"]
    deal = next(
        item for item in assessment["evidence"] if item["document_id"] == "document:DEAL-001"
    )
    assert deal["actor"]["label"] == "Harriet Doyle"


def test_check_claim_without_match_returns_no_assessment() -> None:
    payload = client.post("/api/claims/check", json={"claim": "zzzz qqqq"}).json()
    assert payload["matches"] == []
    assert payload["assessment"] is None
    assert payload["sources_searched"] == 7


def test_check_claim_rejects_empty_text() -> None:
    assert client.post("/api/claims/check", json={"claim": ""}).status_code == 422


def test_get_claim_by_fact_id() -> None:
    response = client.get("/api/claims/fact:billing-signoff-2026-02-18", params={"as_of": AS_OF})
    payload = response.json()
    assert payload["overall_outcome"] == "Insufficient evidence"
    assert payload["gaps"]
    assert client.get("/api/claims/fact:missing").status_code == 404


def test_sources_list_and_detail() -> None:
    sources = client.get("/api/sources").json()["sources"]
    assert len(sources) == 7
    detail = client.get("/api/sources/document:POL-01", params={"as_of": AS_OF}).json()
    assert detail["used_in"] == 1
    assert detail["attestations"][0]["fact_id"] == "fact:discount-new-business"
    assert {item["relationship"] for item in detail["lineage"]} == {
        "GOVERNS",
        "RELATED",
        "SUPERSEDED_BY",
    }
    assert client.get("/api/sources/document:missing").status_code == 404


def test_register_exports() -> None:
    csv_response = client.get("/api/register.csv", params={"as_of": AS_OF})
    assert csv_response.headers["content-type"].startswith("text/csv")
    assert "formal_outcome" in csv_response.text
    assert len(client.get("/api/register.json", params={"as_of": AS_OF}).json()) == 3


def _use_graph(tmp_path, monkeypatch, mutate) -> None:
    """Point the API at a copy of the prototype graph changed by ``mutate``."""
    payload = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    mutate(payload)
    path = tmp_path / "graph.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(
        api_module, "get_framework", lambda: GraphCredibilityFramework.load(path, CONFIG_PATH)
    )


def test_out_of_scope_source_is_reported_but_not_scored(tmp_path, monkeypatch) -> None:
    def mark_out_of_scope(payload: dict) -> None:
        edge = next(item for item in payload["edges"] if item["id"] == "attest:comms01-discount")
        edge["attributes"]["scope_match"] = False

    _use_graph(tmp_path, monkeypatch, mark_out_of_scope)
    assessment = client.get("/api/claims/fact:discount-new-business", params={"as_of": AS_OF})
    slack = next(
        item
        for item in assessment.json()["evidence"]
        if item["document_id"] == "document:COMMS-01"
    )
    assert slack["applicable"] is False
    assert slack["materiality_score"] is None
    assert slack["dimensions"] == {}
    source = client.get("/api/sources/document:COMMS-01", params={"as_of": AS_OF}).json()
    assert source["attestations"][0]["applicable"] is False


def test_invalid_graph_is_reported_clearly(tmp_path, monkeypatch) -> None:
    _use_graph(tmp_path, monkeypatch, lambda payload: payload["nodes"].append(payload["nodes"][0]))
    response = client.get("/api/claims", params={"as_of": AS_OF})
    assert response.status_code == 500
    assert "Node IDs must be unique" in response.json()["detail"]
