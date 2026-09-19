"""
Tests for the shared JWT + API-key auth layer (shared_engine/auth.py) and
its wiring into both backends' FastAPI apps.
"""
from __future__ import annotations

import time

import jwt
import pytest
from fastapi.testclient import TestClient

from shared_engine.auth import _ALGORITHM, _SECRET, _DEV_FALLBACK_KEY
from arth_raksha.backend.main import app as raksha_app
from arth_bodh.backend.main import app as bodh_app


@pytest.fixture(params=[raksha_app, bodh_app], ids=["arth_raksha", "arth_bodh"])
def client(request):
    return TestClient(request.param)


def test_health_needs_no_auth(client):
    resp = client.get("/health")
    assert resp.status_code == 200


def test_token_issued_for_valid_dev_fallback_key(client, monkeypatch):
    monkeypatch.delenv("ARTHDRISHTI_API_KEYS", raising=False)
    resp = client.post("/auth/token", json={"api_key": _DEV_FALLBACK_KEY})
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 3600
    assert body["access_token"]


def test_token_rejected_for_wrong_key(client, monkeypatch):
    monkeypatch.delenv("ARTHDRISHTI_API_KEYS", raising=False)
    resp = client.post("/auth/token", json={"api_key": "not-a-real-key"})
    assert resp.status_code == 401


def test_configured_keys_override_the_dev_fallback(client, monkeypatch):
    monkeypatch.setenv("ARTHDRISHTI_API_KEYS", "prod-key-1,prod-key-2")
    # the dev fallback must no longer work once real keys are configured
    resp = client.post("/auth/token", json={"api_key": _DEV_FALLBACK_KEY})
    assert resp.status_code == 401
    resp = client.post("/auth/token", json={"api_key": "prod-key-2"})
    assert resp.status_code == 200


def test_protected_endpoint_refuses_without_a_token(client):
    resp = client.get("/wallet/0xDemoWallet/risk") if client.app is raksha_app else \
        client.post("/explain", json={"doc_id": "x", "finding_id": "y"})
    assert resp.status_code in (401, 403)


def test_protected_endpoint_works_with_a_valid_token(client, monkeypatch):
    monkeypatch.delenv("ARTHDRISHTI_API_KEYS", raising=False)
    token = client.post("/auth/token", json={"api_key": _DEV_FALLBACK_KEY}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    if client.app is raksha_app:
        connect = client.post("/wallet/connect", json={"address": "0xDemoWallet"}, headers=headers)
        assert connect.status_code == 200
        resp = client.get("/wallet/0xDemoWallet/risk", headers=headers)
        assert resp.status_code == 200
    else:
        resp = client.post("/parse", json={"text": "Late Payment Fee of Rs. 750"}, headers=headers)
        assert resp.status_code == 200


def test_expired_token_is_refused(client):
    expired = jwt.encode(
        {"sub": "test", "iat": int(time.time()) - 7200, "exp": int(time.time()) - 3600},
        _SECRET, algorithm=_ALGORITHM,
    )
    target = "/wallet/0xDemoWallet/risk" if client.app is raksha_app else "/parse"
    method = client.get if client.app is raksha_app else (lambda url, **kw: client.post(url, json={"text": "x"}, **kw))
    resp = method(target, headers={"Authorization": f"Bearer {expired}"})
    assert resp.status_code == 401
    assert "expired" in resp.json()["detail"].lower()


def test_garbage_token_is_refused(client):
    target = "/wallet/0xDemoWallet/risk" if client.app is raksha_app else "/parse"
    method = client.get if client.app is raksha_app else (lambda url, **kw: client.post(url, json={"text": "x"}, **kw))
    resp = method(target, headers={"Authorization": "Bearer not-a-real-jwt"})
    assert resp.status_code == 401
