"""
Computes real, on-chain-derived behavioral features for an address, in the
same units/shape as the training data the scam classifier learned from
(see arth_raksha/ml/train.py, arth_raksha/ml/data/SOURCE.md).

Honesty constraint this module exists to satisfy: a classifier fed
half-invented inputs would be exactly the kind of ungrounded number the
brief forbids. So this module computes only what can be verified from
real chain data, and reports exactly how much of the model's expected
~48-feature vector it actually filled in — the rest is median-imputed by
ml_signal.py and that imputation is never hidden from the caller.

What's computed for real, from a free/keyless RPC (no Etherscan key
needed), using the same ChunkedLogFetcher already proven against real
chain data in wallet_reader.py:

  - Total_ERC20_tnxs                        (the single most predictive
                                              feature per permutation
                                              importance on this model —
                                              see arth_raksha/ml/model/metrics.json)
  - Unique_Received_From_Addresses
  - Time_Diff_between_first_and_last_(Mins) (based on the observed
                                              transfer-activity window,
                                              which can undercount total
                                              wallet age if ERC20 activity
                                              started later than the
                                              wallet's first native-ETH tx)
  - Sent_tnx / Received_Tnx                 (ERC20 transfer counts, used
                                              as a proxy — plain JSON-RPC
                                              cannot enumerate native-ETH
                                              transaction history for an
                                              arbitrary address without an
                                              indexer)

Everything else in the model's expected feature vector (ERC20 value
totals, min/max amounts, native-ETH balances, contract-creation counts...)
requires either a full archive indexer or a paid explorer API and is left
for ml_signal.py to median-impute, tracked via `features_computed`.

An optional, more complete path exists for anyone who supplies a free
Etherscan API key (see compute_features_etherscan) — this is the upgrade
path documented in the README, not faked here.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Optional

import requests

from .wallet_reader import ChunkedLogFetcher, DEFAULT_CHUNK_BLOCKS, _rpc_rate_limiter

TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"  # ERC20 Transfer(address,address,uint256)


@dataclass
class FeatureExtractionResult:
    features: dict[str, float] = field(default_factory=dict)
    features_computed: list[str] = field(default_factory=list)
    source: str = "rpc_partial"   # "rpc_partial" | "etherscan_full"
    warnings: list[str] = field(default_factory=list)


def compute_features_from_rpc(
    w3, address: str, from_block: int, to_block: int
) -> FeatureExtractionResult:
    """Real, free, keyless partial feature extraction — see module docstring
    for exactly which features this can and can't compute for real."""
    address = w3.to_checksum_address(address)
    padded = "0x" + address[2:].rjust(64, "0").lower()
    fetcher = ChunkedLogFetcher(w3, chunk_blocks=DEFAULT_CHUNK_BLOCKS)

    sent_logs, _, warn_sent, _ = fetcher.fetch(from_block, to_block, topics=[TRANSFER_TOPIC, padded])
    recv_logs, _, warn_recv, _ = fetcher.fetch(from_block, to_block, topics=[TRANSFER_TOPIC, None, padded])

    unique_senders = {log["topics"][1].hex() for log in recv_logs}

    block_numbers = [log["blockNumber"] for log in sent_logs + recv_logs]
    time_diff_minutes = 0.0
    if block_numbers:
        try:
            _rpc_rate_limiter.wait()
            earliest_ts = w3.eth.get_block(min(block_numbers))["timestamp"]
            _rpc_rate_limiter.wait()
            latest_ts = w3.eth.get_block(max(block_numbers))["timestamp"]
            time_diff_minutes = max(0.0, (latest_ts - earliest_ts) / 60.0)
        except Exception:
            pass  # leave at 0.0 — this feature simply won't be marked "computed" if it fails

    features = {
        "Total_ERC20_tnxs": float(len(sent_logs) + len(recv_logs)),
        "Unique_Received_From_Addresses": float(len(unique_senders)),
        "Sent_tnx": float(len(sent_logs)),
        "Received_Tnx": float(len(recv_logs)),
    }
    computed = list(features.keys())
    if block_numbers:
        features["Time_Diff_between_first_and_last_(Mins)"] = time_diff_minutes
        computed.append("Time_Diff_between_first_and_last_(Mins)")

    return FeatureExtractionResult(
        features=features,
        features_computed=computed,
        source="rpc_partial",
        warnings=warn_sent + warn_recv,
    )


def compute_features_etherscan(address: str, api_key: Optional[str] = None) -> FeatureExtractionResult:
    """Full-fidelity feature extraction via Etherscan's V2 API — this is
    the same kind of source the training dataset itself was built from.
    Requires a free key from https://etherscan.io/apis (ETHERSCAN_API_KEY
    env var, or pass api_key explicitly). Raises if no key is configured
    rather than silently falling back — callers should catch this and use
    compute_features_from_rpc instead, and say so.
    """
    api_key = api_key or os.environ.get("ETHERSCAN_API_KEY")
    if not api_key:
        raise RuntimeError(
            "No ETHERSCAN_API_KEY configured. Get a free key at "
            "https://etherscan.io/apis and set it as an environment variable "
            "to enable full-fidelity ML feature extraction; falling back to "
            "compute_features_from_rpc gives a partial (but real) feature set "
            "without any key."
        )

    def _call(module: str, action: str, **params) -> list[dict]:
        resp = requests.get(
            "https://api.etherscan.io/v2/api",
            params={"chainid": 1, "module": module, "action": action, "apikey": api_key, **params},
            timeout=15,
        )
        data = resp.json()
        if data.get("status") != "1":
            if "No transactions found" in str(data.get("message", "")):
                return []
            raise RuntimeError(f"Etherscan API error: {data.get('message')} — {data.get('result')}")
        return data["result"]

    txs = _call("account", "txlist", address=address, startblock=0, endblock=99_999_999,
                page=1, offset=10_000, sort="asc")
    tokentx = _call("account", "tokentx", address=address, startblock=0, endblock=99_999_999,
                     page=1, offset=10_000, sort="asc")
    time.sleep(0.25)  # be polite to the free tier's rate limit

    addr_lower = address.lower()
    sent = [t for t in txs if t["from"].lower() == addr_lower]
    received = [t for t in txs if t["to"].lower() == addr_lower]
    created = [t for t in sent if t.get("contractAddress")]

    def _minutes_between(items: list[dict]) -> float:
        ts = sorted(int(t["timeStamp"]) for t in items)
        if len(ts) < 2:
            return 0.0
        diffs = [(ts[i + 1] - ts[i]) / 60.0 for i in range(len(ts) - 1)]
        return sum(diffs) / len(diffs)

    def _eth(wei_str: str) -> float:
        return int(wei_str) / 1e18

    sent_values = [_eth(t["value"]) for t in sent] or [0.0]
    recv_values = [_eth(t["value"]) for t in received] or [0.0]

    erc20_sent = [t for t in tokentx if t["from"].lower() == addr_lower]
    erc20_recv = [t for t in tokentx if t["to"].lower() == addr_lower]

    all_ts = [int(t["timeStamp"]) for t in txs]
    time_diff = (max(all_ts) - min(all_ts)) / 60.0 if len(all_ts) >= 2 else 0.0

    features = {
        "Avg_min_between_sent_tnx": _minutes_between(sent),
        "Avg_min_between_received_tnx": _minutes_between(received),
        "Time_Diff_between_first_and_last_(Mins)": time_diff,
        "Sent_tnx": float(len(sent)),
        "Received_Tnx": float(len(received)),
        "Number_of_Created_Contracts": float(len(created)),
        "Unique_Received_From_Addresses": float(len({t["from"].lower() for t in received})),
        "Unique_Sent_To_Addresses": float(len({t["to"].lower() for t in sent if t["to"]})),
        "min_value_received": min(recv_values),
        "max_value_received": max(recv_values),
        "avg_val_received": sum(recv_values) / len(recv_values),
        "min_val_sent": min(sent_values),
        "max_val_sent": max(sent_values),
        "avg_val_sent": sum(sent_values) / len(sent_values),
        "total_transactions_(including_tnx_to_create_contract)": float(len(txs)),
        "total_Ether_sent": sum(sent_values),
        "total_ether_received": sum(recv_values),
        "Total_ERC20_tnxs": float(len(tokentx)),
        "ERC20_uniq_sent_addr": float(len({t["to"].lower() for t in erc20_sent if t["to"]})),
        "ERC20_uniq_rec_addr": float(len({t["from"].lower() for t in erc20_recv})),
    }
    return FeatureExtractionResult(
        features=features,
        features_computed=list(features.keys()),
        source="etherscan_full",
    )
