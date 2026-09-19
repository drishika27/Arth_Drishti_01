"""
Integration tests through the real FastAPI apps (TestClient, not just the
underlying Python functions) — the brief's non-negotiable rules enforced
"structurally, not just by prompting" deserve a check at the layer an
actual client hits, not only at the dataclass layer test_transaction_safety.py
and test_revoke_safety.py already cover.
"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from shared_engine.auth import _DEV_FALLBACK_KEY
from arth_raksha.backend.main import app as raksha_app
from arth_bodh.backend.main import app as bodh_app

_FORBIDDEN_SUBSTRINGS = ("privatekey", "private_key", "signature", "mnemonic", "seedphrase", "seed_phrase")


def _auth_headers(client: TestClient) -> dict:
    token = client.post("/auth/token", json={"api_key": _DEV_FALLBACK_KEY}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _assert_no_signing_material(payload) -> None:
    blob = json.dumps(payload).lower().replace(" ", "").replace("-", "_")
    for bad in _FORBIDDEN_SUBSTRINGS:
        assert bad not in blob, f"found forbidden substring '{bad}' in response: {payload}"


def test_no_request_body_field_anywhere_accepts_signing_material(monkeypatch):
    """Structural check across the whole OpenAPI schema, not just the
    endpoints this file happens to exercise: no request body field name
    on either backend should ever be named like a private key, signature,
    or seed phrase — enforced by scanning the real generated schema."""
    monkeypatch.delenv("ARTHDRISHTI_API_KEYS", raising=False)
    for app in (raksha_app, bodh_app):
        schema = app.openapi()
        schema_blob = json.dumps(schema).lower()
        for bad in ("privatekey", "private_key", "\"signature\"", "mnemonic", "seedphrase", "seed_phrase"):
            assert bad not in schema_blob, f"{app.title}: forbidden field-like term '{bad}' found in OpenAPI schema"


def test_full_send_flow_via_http_never_exposes_signing_material(monkeypatch):
    monkeypatch.delenv("ARTHDRISHTI_API_KEYS", raising=False)
    client = TestClient(raksha_app)
    headers = _auth_headers(client)

    connect = client.post("/wallet/connect", json={"address": "0xIntegrationWallet"}, headers=headers)
    assert connect.status_code == 200
    _assert_no_signing_material(connect.json())

    contact = client.post(
        "/address-book",
        json={"wallet_address": "0xIntegrationWallet", "name": "Saniya",
              "address": "0xaBC000000000000000000000000000000000DEaD"},
        headers=headers,
    )
    assert contact.status_code == 200

    draft = client.post(
        "/send/draft",
        json={"wallet_address": "0xIntegrationWallet", "request": "send 0.01 ETH to Saniya"},
        headers=headers,
    )
    assert draft.status_code == 200
    draft_body = draft.json()
    assert draft_body["confirmed"] is False
    _assert_no_signing_material(draft_body)

    confirm = client.post(f"/send/{draft_body['draft_id']}/confirm", headers=headers)
    assert confirm.status_code == 200
    payload = confirm.json()
    _assert_no_signing_material(payload)
    assert "from" not in {k.lower() for k in payload.keys()}
    assert payload["value"] == hex(int(0.01 * 10**18))


def test_send_draft_refuses_unknown_recipient_via_http(monkeypatch):
    monkeypatch.delenv("ARTHDRISHTI_API_KEYS", raising=False)
    client = TestClient(raksha_app)
    headers = _auth_headers(client)
    client.post("/wallet/connect", json={"address": "0xIntegrationWallet2"}, headers=headers)
    resp = client.post(
        "/send/draft",
        json={"wallet_address": "0xIntegrationWallet2", "request": "send 1 ETH to SomeoneNotSaved"},
        headers=headers,
    )
    assert resp.status_code == 400


def test_address_book_list_endpoint_returns_saved_contacts(monkeypatch):
    monkeypatch.delenv("ARTHDRISHTI_API_KEYS", raising=False)
    client = TestClient(raksha_app)
    headers = _auth_headers(client)
    client.post("/wallet/connect", json={"address": "0xIntegrationWallet4"}, headers=headers)

    empty = client.get("/address-book/0xIntegrationWallet4", headers=headers)
    assert empty.status_code == 200
    assert empty.json()["contacts"] == []

    client.post(
        "/address-book",
        json={"wallet_address": "0xIntegrationWallet4", "name": "Test2", "address": "0x1111111254EEB25477B68fb85Ed929f73A960582"},
        headers=headers,
    )
    listed = client.get("/address-book/0xIntegrationWallet4", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["contacts"] == [
        {"name": "Test2", "address": "0x1111111254EEB25477B68fb85Ed929f73A960582", "chain": "ethereum"}
    ]


def test_address_book_list_for_unknown_wallet_is_empty_not_an_error(monkeypatch):
    monkeypatch.delenv("ARTHDRISHTI_API_KEYS", raising=False)
    client = TestClient(raksha_app)
    headers = _auth_headers(client)
    resp = client.get("/address-book/0xNeverConnectedWallet", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["contacts"] == []


def test_full_revoke_flow_via_http_never_exposes_signing_material(monkeypatch):
    monkeypatch.delenv("ARTHDRISHTI_API_KEYS", raising=False)
    client = TestClient(raksha_app)
    headers = _auth_headers(client)
    client.post("/wallet/connect", json={"address": "0xIntegrationWallet3"}, headers=headers)

    draft_resp = client.post(
        "/revoke/draft",
        json={
            "wallet_address": "0xIntegrationWallet3",
            "approvals": [
                {"token_address": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
                 "spender_address": "0x1111111254EEB25477B68fb85Ed929f73A960582"},
                {"token_address": "not-a-real-address",
                 "spender_address": "0x1111111254EEB25477B68fb85Ed929f73A960582"},
            ],
        },
        headers=headers,
    )
    assert draft_resp.status_code == 200
    drafts = draft_resp.json()["drafts"]
    assert len(drafts) == 2
    assert "error" in drafts[1] and "draft_id" not in drafts[1]  # bad item failed alone
    assert "draft_id" in drafts[0]  # good item still succeeded
    _assert_no_signing_material(draft_resp.json())

    confirm = client.post(f"/revoke/{drafts[0]['draft_id']}/confirm", headers=headers)
    assert confirm.status_code == 200
    payload = confirm.json()
    _assert_no_signing_material(payload)
    assert payload["data"].startswith("0x095ea7b3")


def test_arth_bodh_full_flow_via_http(monkeypatch):
    monkeypatch.delenv("ARTHDRISHTI_API_KEYS", raising=False)
    client = TestClient(bodh_app)
    headers = _auth_headers(client)

    parsed = client.post(
        "/parse", json={"text": "Late Payment Fee of Rs. 750 charged on 12 Jan."}, headers=headers
    )
    assert parsed.status_code == 200
    body = parsed.json()
    assert body["finding_count"] > 0

    explained = client.post(
        "/explain",
        json={"doc_id": body["doc_id"], "finding_id": body["findings"][0]["finding_id"], "depth": "detailed"},
        headers=headers,
    )
    assert explained.status_code == 200
    assert "750" in explained.json()["text"]

    chatted = client.post(
        "/chat", json={"doc_id": body["doc_id"], "question": "why was I charged a late payment fee?"},
        headers=headers,
    )
    assert chatted.status_code == 200
    assert chatted.json()["answer"]
