from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tradeguard.console import create_app
from tradeguard.market.service import import_csv
from tradeguard.portfolio.service import create_account

ORIGIN = "https://stock.example.test"
CREDENTIALS = {"username": "test-owner", "password": "fixture-secret"}


@pytest.fixture
def online(monkeypatch):
    monkeypatch.setenv("TRADEGUARD_PUBLIC_ORIGIN", ORIGIN)
    monkeypatch.setenv("TRADEGUARD_PORTFOLIO_USERNAME", CREDENTIALS["username"])
    monkeypatch.setenv("TRADEGUARD_PORTFOLIO_PASSWORD", CREDENTIALS["password"])
    return TestClient(create_app(), base_url=ORIGIN)


def test_public_routes_never_return_private_state(online, database):
    import_csv(Path("examples/bars.csv"))
    create_account("fixture-account", "manual", "Private label")

    assert online.get("/api/context?market=CN").status_code == 200
    workspace = online.get("/api/workspace?market=CN&source=synthetic")
    assert workspace.status_code == 200
    assert set(workspace.json()) == {"scope", "as_of", "report"}
    for path in ("/api/portfolio/accounts", "/api/discipline/playbook"):
        result = online.get(path)
        assert result.status_code == 401
        assert result.headers["Cache-Control"] == "no-store"
        assert "Private label" not in result.text
    for path in (
        "/api/portfolio/accounts/",
        "/api/watchlist",
        "/api/notifications",
        "/api/backtests",
        "/api/scan/example/events",
        "/openapi.json",
    ):
        result = online.get(path)
        if path != "/openapi.json":
            assert result.status_code == 404
        else:
            assert "paths" not in result.text
    assert online.post("/api/scan/run").status_code == 404


def test_portfolio_login_session_and_logout(online, database):
    create_account("fixture-account", "manual", "Private label")
    login = "/api/portfolio/login"
    accounts = "/api/portfolio/accounts"
    origin = {"Origin": ORIGIN}
    assert online.get("/api/portfolio/session").json() == {"authenticated": False}
    assert online.post(login, json=CREDENTIALS).status_code == 403
    assert online.post(login, json={**CREDENTIALS, "password": "wrong"}, headers=origin).status_code == 401
    logged_in = online.post(login, json=CREDENTIALS, headers=origin)
    assert logged_in.status_code == 200
    cookie = logged_in.headers["Set-Cookie"]
    assert all(attribute in cookie for attribute in ("__Host-", "HttpOnly", "Secure", "SameSite=strict"))
    assert online.get("/api/portfolio/session").json() == {"authenticated": True}
    private = online.get(accounts)
    assert private.status_code == 200
    assert "Private label" in private.text
    assert private.headers["Cache-Control"] == "no-store"
    assert online.post(accounts, headers=origin).status_code == 404
    assert online.post("/api/portfolio/logout", headers=origin).status_code == 200
    assert online.get(accounts).status_code == 401
