"""Wallet sign-in (signature-based, keyless) and the real-portfolio logic
(mocked provider responses shaped like the real Blockscout/CoinGecko ones)."""
import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

from arth_core import crypto
from arth_core.crypto import ChainDataError

USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
SPAM = "0x9cdf242ef7975d8c68d5c1f5b6905801699b1940"


def _login(client, acct, domain="localhost:5173"):
    ch = client.post("/auth/wallet/nonce", json={"address": acct.address, "domain": domain}).json()
    sig = acct.sign_message(encode_defunct(text=ch["message"])).signature.hex()
    return ch, sig


def _verify(client, acct, ch, sig):
    return client.post("/auth/wallet/verify", json={"address": acct.address, "signature": sig, "token": ch["token"]})


# ---- wallet sign-in --------------------------------------------------------
def test_wallet_login_creates_then_reuses_the_same_account(client):
    acct = Account.create()
    ch, sig = _login(client, acct)
    assert "does not send a transaction" in ch["message"] and acct.address in ch["message"]
    r = _verify(client, acct, ch, sig)
    assert r.status_code == 200
    first = r.json()
    assert first["user"]["email"].endswith("@wallet.local")

    ch2, sig2 = _login(client, acct)
    second = _verify(client, acct, ch2, sig2).json()
    assert second["user"]["id"] == first["user"]["id"]

    h = {"Authorization": f"Bearer {first['access_token']}"}
    wallets = client.get("/crypto/wallets", headers=h).json()["wallets"]
    assert len(wallets) == 1 and wallets[0]["verified"] is True and wallets[0]["address"] == acct.address.lower()


def test_signature_cannot_be_replayed_or_forged(client):
    acct, other = Account.create(), Account.create()
    ch, sig = _login(client, acct)
    assert _verify(client, acct, ch, sig).status_code == 200
    assert _verify(client, acct, ch, sig).status_code == 401                      # replay of a used nonce

    ch, _ = _login(client, acct)
    forged = other.sign_message(encode_defunct(text=ch["message"])).signature.hex()
    assert _verify(client, acct, ch, forged).status_code == 401                   # signed by someone else

    ch, sig = _login(client, acct)
    assert client.post("/auth/wallet/verify", json={"address": other.address, "signature": sig, "token": ch["token"]}).status_code == 401
    assert client.post("/auth/wallet/nonce", json={"address": "0x123"}).status_code == 422


def test_wallet_accounts_cannot_be_squatted_or_password_logged_into(client):
    acct = Account.create()
    ch, sig = _login(client, acct)
    _verify(client, acct, ch, sig)
    email = f"{acct.address.lower()}@wallet.local"
    assert client.post("/auth/register", json={"email": email, "password": "attacker-pass-1"}).status_code == 422
    assert client.post("/auth/login", json={"email": email, "password": "anything-at-all"}).status_code == 401


def test_link_wallet_to_email_account_and_ownership_rules(client, auth, auth2):
    acct = Account.create()
    ch, sig = _login(client, acct)
    body = {"address": acct.address, "signature": sig, "token": ch["token"]}
    r = client.post("/crypto/wallets/link", json=body, headers=auth)
    assert r.status_code == 201 and r.json()["verified"] is True
    ch, sig = _login(client, acct)
    dup = client.post("/crypto/wallets/link", json={"address": acct.address, "signature": sig, "token": ch["token"]}, headers=auth2)
    assert dup.status_code == 409                                                  # already owned by someone else
    assert client.get("/crypto/wallets", headers=auth2).json()["wallets"] == []


def test_sign_in_wallet_cannot_be_removed(client):
    acct = Account.create()
    ch, sig = _login(client, acct)
    tokens = _verify(client, acct, ch, sig).json()
    h = {"Authorization": f"Bearer {tokens['access_token']}"}
    wid = client.get("/crypto/wallets", headers=h).json()["wallets"][0]["id"]
    assert client.delete(f"/crypto/wallets/{wid}", headers=h).status_code == 409


def test_watch_wallet_validation_and_isolation(client, auth, auth2):
    assert client.post("/crypto/wallets/watch", json={"address": "not-an-address"}, headers=auth).status_code == 422
    r = client.post("/crypto/wallets/watch", json={"address": USDC, "label": "USDC contract"}, headers=auth)
    assert r.status_code == 201 and r.json()["verified"] is False
    wid = r.json()["id"]
    assert client.get("/crypto/wallets", headers=auth2).json()["wallets"] == []
    assert client.delete(f"/crypto/wallets/{wid}", headers=auth2).status_code == 404
    assert client.delete(f"/crypto/wallets/{wid}", headers=auth).status_code == 204


# ---- portfolio logic (mocked provider data) ---------------------------------
def _fake_get(fail=None):
    def fake(url, params=None, ttl=60):
        if fail:
            raise ChainDataError(fail)
        if "/token-balances" in url:
            return [
                {"value": "100000000", "token": {"address_hash": USDC, "symbol": "USDC", "name": "USD Coin", "decimals": "6", "type": "ERC-20", "exchange_rate": "1.0"}},
                {"value": "10000000000000000000000000000", "token": {"address_hash": SPAM, "symbol": "WHITE", "name": "spam", "decimals": "18", "type": "ERC-20", "exchange_rate": "0.00003"}},
            ]
        if "/token-transfers" in url:
            return {"items": [
                {"token": {"address_hash": USDC, "symbol": "USDC", "decimals": "6"}, "total": {"value": "25000000", "decimals": "6"},
                 "from": {"hash": "0x1111111111111111111111111111111111111111"}, "to": {"hash": "0x2222222222222222222222222222222222222222"},
                 "transaction_hash": "0xabc1", "log_index": 1, "timestamp": "2026-09-18T10:00:00.000000Z"},
                {"token": {"address_hash": SPAM, "symbol": "WHITE", "decimals": "18"}, "total": {"value": "5", "decimals": "18"},
                 "from": {"hash": "0x3333333333333333333333333333333333333333"}, "to": {"hash": "0x2222222222222222222222222222222222222222"},
                 "transaction_hash": "0xabc2", "log_index": 2, "timestamp": "2026-09-19T10:00:00.000000Z"}]}
        if "/transactions" in url:
            return {"items": [{"hash": "0xabc3", "timestamp": "2026-09-17T09:00:00.000000Z", "value": "500000000000000000", "status": "ok",
                               "from": {"hash": "0x9999999999999999999999999999999999999999"}, "to": {"hash": "0x2222222222222222222222222222222222222222"},
                               "fee": {"value": "20000000000000"}, "method": None}]}
        if "/addresses/" in url:
            return {"coin_balance": "2000000000000000000", "is_contract": False, "is_scam": False, "ens_domain_name": None}
        if "coins/list" in url:
            return [{"id": "usd-coin", "platforms": {"ethereum": USDC}}]
        if "coins/markets" in url:
            return [{"id": "usd-coin"}]
        if "simple/price" in url:
            ids = params["ids"].split(",")
            table = {"ethereum": {"inr": 250000, "inr_24h_change": 2.0}, "usd-coin": {"inr": 90, "inr_24h_change": 0.0}}
            return {i: table[i] for i in ids if i in table}
        raise AssertionError(f"unexpected url {url}")
    return fake


@pytest.fixture()
def wallet_id(client, auth):
    crypto.clear_cache()
    addr = "0x2222222222222222222222222222222222222222"
    return client.post("/crypto/wallets/watch", json={"address": addr}, headers=auth).json()["id"], addr


def test_overview_values_real_assets_and_excludes_spam(client, auth, wallet_id, monkeypatch):
    monkeypatch.setattr(crypto, "_get", _fake_get())
    wid, addr = wallet_id
    o = client.get(f"/crypto/overview?wallet_id={wid}", headers=auth).json()
    assert o["data_mode"] == "live" and o["wallet"]["watch_only"] is True
    assert {a["symbol"] for a in o["assets"]} == {"ETH", "USDC"}                    # spam token not counted
    assert o["total_value_inr"] == 2 * 250000 + 100 * 90                             # 509,000: real balances x real prices
    assert o["hidden_unverified_tokens"] == 1
    eth = next(a for a in o["assets"] if a["symbol"] == "ETH")
    assert eth["amount"] == 2.0 and eth["allocation_pct"] == round(500000 / 509000 * 100, 1)
    assert o["change_24h_pct"] is not None


def test_transactions_are_normalised_and_spam_transfers_hidden(client, auth, wallet_id, monkeypatch):
    monkeypatch.setattr(crypto, "_get", _fake_get())
    wid, addr = wallet_id
    o = client.get(f"/crypto/overview?wallet_id={wid}", headers=auth).json()
    hashes = {t["hash"] for t in o["transactions"]}
    assert hashes == {"0xabc1", "0xabc3"} and o["hidden_unverified_transfers"] == 1
    usdc = next(t for t in o["transactions"] if t["hash"] == "0xabc1")
    assert usdc["asset"] == "USDC" and usdc["amount"] == 25.0 and usdc["type"] == "Received" and usdc["value_now_inr"] == 2250.0
    eth = next(t for t in o["transactions"] if t["hash"] == "0xabc3")
    assert eth["type"] == "Received" and eth["amount"] == 0.5 and eth["status"] == "Confirmed"
    assert eth["explorer_url"].endswith("0xabc3")


def test_provider_outage_is_reported_not_faked(client, auth, wallet_id, monkeypatch):
    monkeypatch.setattr(crypto, "_get", _fake_get(fail="503 from eth.blockscout.com"))
    wid, _ = wallet_id
    r = client.get(f"/crypto/overview?wallet_id={wid}", headers=auth)
    assert r.status_code == 502 and r.json()["detail"]["retryable"] is True


def test_prices_unavailable_shows_balances_without_values(client, auth, wallet_id, monkeypatch):
    real = _fake_get()

    def flaky(url, params=None, ttl=60):
        if "simple/price" in url:
            raise ChainDataError("429 from api.coingecko.com")
        return real(url, params, ttl)
    monkeypatch.setattr(crypto, "_get", flaky)
    wid, _ = wallet_id
    o = client.get(f"/crypto/overview?wallet_id={wid}", headers=auth).json()
    assert o["total_value_inr"] is None or o["total_value_inr"] == 0
    assert all(a["value_inr"] is None for a in o["assets"]) and o["notes"]


def test_live_wallet_takes_priority_over_sample_data(client, auth, wallet_id, monkeypatch):
    monkeypatch.setattr(crypto, "_get", _fake_get())
    client.post("/demo/seed", headers=auth)
    assert client.get("/crypto/overview", headers=auth).json()["data_mode"] == "live"
    demo_id = next(w["id"] for w in client.get("/crypto/wallets", headers=auth).json()["wallets"] if w["demo"])
    assert client.get(f"/crypto/overview?wallet_id={demo_id}", headers=auth).json()["data_mode"] == "demo"


def test_normalize_address_rejects_bad_input():
    assert crypto.normalize_address(USDC) == USDC
    for bad in ("", "0x123", "hello", "0x" + "z" * 40):
        with pytest.raises(ValueError):
            crypto.normalize_address(bad)
    assert crypto.normalize_address("0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48") == USDC   # correct checksum: accepted
    with pytest.raises(ValueError):                                              # same letters, one case flipped: typo caught
        crypto.normalize_address("0xa0B86991c6218b36c1d19D4a2e9Eb0cE3606eB48")
