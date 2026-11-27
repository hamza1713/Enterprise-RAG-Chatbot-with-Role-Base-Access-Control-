"""
tests/test_phase2_auth_dual.py — Dual Auth (HttpOnly cookie, Bearer JWT, CSRF origin check, OIDC mapping).
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest
from starlette.requests import Request

from app.api import auth as auth_api
from app.core.config import SESSION_COOKIE_NAME
from app.core.security import create_access_token, hash_password, verify_password


def _make_request(
    method: str = "POST",
    *,
    headers: dict[str, str] | None = None,
    base_url: str = "http://localhost:8000/",
) -> Request:
    raw_headers = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    scope = {
        "type": "http",
        "method": method,
        "scheme": "http",
        "server": ("localhost", 8000),
        "path": "/chat",
        "headers": raw_headers,
    }
    req = Request(scope)
    return req


def test_oidc_password_sentinel_always_rejected():
    assert verify_password("!oidc-managed!", "!oidc-managed!") is False
    assert verify_password("any-password", "!oidc-managed!") is False
    real_hash = hash_password("correct-horse-battery-staple")
    assert verify_password("correct-horse-battery-staple", real_hash) is True


def test_extract_oidc_role_maps_known_claims_and_fails_closed():
    available = ["C-Level", "Finance", "HR", "Engineering", "General"]
    with patch.dict(
        os.environ,
        {
            "OIDC_ROLE_CLAIM": "groups",
            "OIDC_ROLE_MAP_JSON": '{"corp-fin-analysts": "Finance", "corp-admins": "C-Level"}',
        },
    ):
        assert auth_api.extract_oidc_role({"groups": ["corp-fin-analysts"]}, available) == "Finance"
        assert auth_api.extract_oidc_role({"groups": ["Engineering"]}, available) == "Engineering"
        # Unmapped claims must fail closed to least-privilege General
        assert auth_api.extract_oidc_role({"groups": ["unknown-vendor"]}, available) == "General"
        assert auth_api.extract_oidc_role({}, available) == "General"


def test_csrf_guard_blocks_cross_origin_cookie_mutations():
    # Allowed same-origin / CORS origin passes
    auth_api.verify_csrf_for_cookie_auth(
        _make_request("POST", headers={"Origin": "http://localhost:5173"})
    )
    # GET requests skip mutation CSRF check
    auth_api.verify_csrf_for_cookie_auth(
        _make_request("GET", headers={"Origin": "https://evil.example"})
    )
    # Evil cross-site origin must raise 403
    with pytest.raises(HTTPException) as exc1:
        auth_api.verify_csrf_for_cookie_auth(
            _make_request("POST", headers={"Origin": "https://evil.example"})
        )
    assert exc1.value.status_code == 403

    # Evil Referer or Sec-Fetch-Site must raise 403
    with pytest.raises(HTTPException):
        auth_api.verify_csrf_for_cookie_auth(
            _make_request("DELETE", headers={"Referer": "https://attacker.tld/phish"})
        )
    with pytest.raises(HTTPException):
        auth_api.verify_csrf_for_cookie_auth(
            _make_request("POST", headers={"Sec-Fetch-Site": "cross-site"})
        )


def test_cookie_and_bearer_dual_auth_endpoints():
    test_app = FastAPI()
    test_app.include_router(auth_api.router)

    fake_user = SimpleNamespace(
        username="alice",
        password_hash=hash_password("strong-password-1234"),
        role_name="Finance",
        auth_provider="local",
        is_active=True,
        token_version=1,
    )

    class _FakeDb:
        async def scalar(self, _stmt):
            return fake_user

        async def commit(self):
            return None

    async def _override_db():
        yield _FakeDb()

    test_app.dependency_overrides[auth_api.get_db] = _override_db
    client = TestClient(test_app)

    prov = client.get("/auth/providers")
    assert prov.status_code == 200
    assert prov.json()["local_enabled"] is True

    # JSON login sets HttpOnly cookie and returns user + bearer token
    login_res = client.post(
        "/auth/login",
        json={"username": "alice", "password": "strong-password-1234"},
    )
    assert login_res.status_code == 200
    assert SESSION_COOKIE_NAME in login_res.cookies
    assert login_res.json()["user"]["username"] == "alice"

    # Cookie-based session hydration (/auth/me) works without Bearer header
    me_cookie = client.get("/auth/me")
    assert me_cookie.status_code == 200
    assert me_cookie.json() == {
        "username": "alice",
        "role": "Finance",
        "auth_provider": "local",
    }

    # Explicit cross-origin cookie mutation is blocked cleanly (403)
    bad_csrf = client.post("/auth/logout", headers={"Origin": "https://evil.example"})
    assert bad_csrf.status_code == 403

    # Same-origin logout clears cookie cleanly
    logout_res = client.post("/auth/logout", headers={"Origin": "http://localhost:5173"})
    assert logout_res.status_code == 200
    assert client.get("/auth/me").status_code == 401

    # Bearer header authentication remains fully supported
    bearer_tok = create_access_token({"sub": "alice", "role": "Finance", "tv": 1})
    me_bearer = client.get("/auth/me", headers={"Authorization": f"Bearer {bearer_tok}"})
    assert me_bearer.status_code == 200
    assert me_bearer.json()["username"] == "alice"
