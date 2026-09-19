"""
Tests for the Etherscan-based full-fidelity feature extractor
(arth_raksha/backend/wallet_features.py::compute_features_etherscan) —
previously entirely untested since this environment has no Etherscan API
key. Mocking requests.get lets the parsing/aggregation logic itself be
verified for real without needing a live key or network access.
"""
from __future__ import annotations

import pytest

from arth_raksha.backend import wallet_features as wf

ADDRESS = "0xaBC000000000000000000000000000000000DEaD"


def test_raises_clearly_without_an_api_key(monkeypatch):
    monkeypatch.delenv("ETHERSCAN_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="No ETHERSCAN_API_KEY"):
        wf.compute_features_etherscan(ADDRESS)


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def test_computes_real_features_from_mocked_etherscan_responses(monkeypatch):
    addr_lower = ADDRESS.lower()

    txlist = {
        "status": "1", "message": "OK",
        "result": [
            {"from": addr_lower, "to": "0xspender1", "value": str(10**18), "timeStamp": "1000",
             "contractAddress": ""},
            {"from": "0xsender2", "to": addr_lower, "value": str(2 * 10**18), "timeStamp": "1600",
             "contractAddress": ""},
            {"from": addr_lower, "to": "0xnewcontract", "value": "0", "timeStamp": "2200",
             "contractAddress": "0xnewcontract"},
        ],
    }
    tokentx = {
        "status": "1", "message": "OK",
        "result": [
            {"from": addr_lower, "to": "0xtokenrecipient", "timeStamp": "1100"},
            {"from": "0xtokensender", "to": addr_lower, "timeStamp": "1700"},
        ],
    }

    def fake_get(url, params=None, timeout=None):
        if params["action"] == "txlist":
            return _FakeResponse(txlist)
        return _FakeResponse(tokentx)

    monkeypatch.setattr(wf.requests, "get", fake_get)
    monkeypatch.setattr(wf.time, "sleep", lambda *_: None)  # skip the real rate-limit delay in tests

    result = wf.compute_features_etherscan(ADDRESS, api_key="test-key")
    f = result.features

    assert result.source == "etherscan_full"
    assert f["Sent_tnx"] == 2.0     # the two txs sent from addr_lower
    assert f["Received_Tnx"] == 1.0
    assert f["Number_of_Created_Contracts"] == 1.0
    assert f["Total_ERC20_tnxs"] == 2.0
    assert f["total_transactions_(including_tnx_to_create_contract)"] == 3.0
    assert f["total_Ether_sent"] == pytest.approx(1.0)   # 1 ETH sent, the contract-creation tx sent 0
    assert f["total_ether_received"] == pytest.approx(2.0)
    assert f["Unique_Received_From_Addresses"] == 1.0
    assert f["Time_Diff_between_first_and_last_(Mins)"] == pytest.approx((2200 - 1000) / 60.0)


def test_no_transactions_found_is_treated_as_empty_not_an_error(monkeypatch):
    empty = {"status": "0", "message": "No transactions found", "result": []}
    monkeypatch.setattr(wf.requests, "get", lambda *a, **kw: _FakeResponse(empty))
    monkeypatch.setattr(wf.time, "sleep", lambda *_: None)

    result = wf.compute_features_etherscan(ADDRESS, api_key="test-key")
    assert result.features["Sent_tnx"] == 0.0
    assert result.features["Total_ERC20_tnxs"] == 0.0


def test_real_etherscan_error_raises_with_message(monkeypatch):
    error_payload = {"status": "0", "message": "NOTOK", "result": "Invalid API Key"}
    monkeypatch.setattr(wf.requests, "get", lambda *a, **kw: _FakeResponse(error_payload))
    monkeypatch.setattr(wf.time, "sleep", lambda *_: None)

    with pytest.raises(RuntimeError, match="Invalid API Key"):
        wf.compute_features_etherscan(ADDRESS, api_key="bad-key")
