import logging

from fastapi.testclient import TestClient
import pytest

from decidr.api.app import app

ACCOUNT = {"name": "Test User", "email": "Test@Example.com", "password": "correct-horse"}


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("DECIDR_AUTH_DB", str(tmp_path / "users.db"))
    return TestClient(app)


def test_data_routes_require_a_session(client: TestClient) -> None:
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/claims").status_code == 401
    assert client.get("/api/sources").status_code == 401
    assert client.get("/api/auth/me").status_code == 401


def test_signup_signs_in_and_rejects_duplicates(client: TestClient) -> None:
    response = client.post("/api/auth/signup", json=ACCOUNT)
    assert response.status_code == 201
    assert response.json()["email"] == "test@example.com"
    assert client.get("/api/auth/me").json()["name"] == "Test User"
    assert client.get("/api/claims").status_code == 200
    assert client.post("/api/auth/signup", json=ACCOUNT).status_code == 409


def test_signup_validates_email_and_password(client: TestClient) -> None:
    assert client.post("/api/auth/signup", json={**ACCOUNT, "email": "nope"}).status_code == 422
    assert (
        client.post("/api/auth/signup", json={**ACCOUNT, "password": "short"}).status_code == 422
    )


def test_login_and_logout(client: TestClient) -> None:
    client.post("/api/auth/signup", json=ACCOUNT)
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401
    wrong = {"email": "test@example.com", "password": "wrong-password"}
    assert client.post("/api/auth/login", json=wrong).status_code == 401
    unknown = {"email": "nobody@example.com", "password": "correct-horse"}
    assert client.post("/api/auth/login", json=unknown).status_code == 401
    right = {"email": "TEST@example.com", "password": "correct-horse"}
    assert client.post("/api/auth/login", json=right).status_code == 200
    assert client.get("/api/auth/me").status_code == 200


def test_profile_and_password_change(client: TestClient) -> None:
    client.post("/api/auth/signup", json=ACCOUNT)
    assert client.patch("/api/auth/me", json={"name": "New Name"}).json()["name"] == "New Name"
    bad = {"current_password": "wrong-password", "new_password": "another-horse"}
    assert client.post("/api/auth/password", json=bad).status_code == 400
    good = {"current_password": "correct-horse", "new_password": "another-horse"}
    assert client.post("/api/auth/password", json=good).status_code == 204
    client.post("/api/auth/logout")
    login = {"email": "test@example.com", "password": "another-horse"}
    assert client.post("/api/auth/login", json=login).status_code == 200


def test_forgot_and_reset_password(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    client.post("/api/auth/signup", json=ACCOUNT)
    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        known = client.post("/api/auth/forgot", json={"email": "test@example.com"})
        unknown = client.post("/api/auth/forgot", json={"email": "nobody@example.com"})
    # The reply never reveals whether the account exists; only one link is issued.
    assert known.json() == unknown.json()
    links = [record.getMessage() for record in caplog.records if "reset=" in record.getMessage()]
    assert len(links) == 1
    token = links[0].split("reset=")[1]

    assert (
        client.post("/api/auth/reset", json={"token": "bogus", "password": "brand-new-pass"})
    ).status_code == 400
    reset = {"token": token, "password": "brand-new-pass"}
    assert client.post("/api/auth/reset", json=reset).status_code == 204
    # The reset signs out existing sessions and the link is single-use.
    assert client.get("/api/auth/me").status_code == 401
    assert client.post("/api/auth/reset", json=reset).status_code == 400
    old = {"email": "test@example.com", "password": "correct-horse"}
    assert client.post("/api/auth/login", json=old).status_code == 401
    new = {"email": "test@example.com", "password": "brand-new-pass"}
    assert client.post("/api/auth/login", json=new).status_code == 200
