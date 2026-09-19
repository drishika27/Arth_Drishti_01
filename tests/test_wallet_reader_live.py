"""
Live-network tests for Web3WalletReader — these actually hit a real public
Ethereum RPC (rpc.mevblocker.io) and a real wallet address with real,
verified approval history. They are the honesty check for Phase 1 of the
brief: "test it against a real wallet address with actual approval history"
means an actual assertion against actual chain data, not a mock.

They skip (not fail) when there is no network access, so the offline test
suite (`pytest tests/`) stays green in restricted environments — but when
network access is available, these run for real and print what they found.
"""
from __future__ import annotations

import socket

import pytest

from arth_raksha.backend.wallet_reader import Web3WalletReader, RECOMMENDED_RPC_URL

# A real address with a real, verified ERC20 Approval event at a known block
# — confirmed live via raw eth_getLogs against rpc.mevblocker.io during
# development of this reader (see tx hash / block below).
REAL_WALLET_WITH_APPROVAL = "0x3208684f96458C540EB08f6F01B9e9afb2B7D4f0"
KNOWN_APPROVAL_BLOCK = 18000001
KNOWN_APPROVAL_TX = "0xed49697ab7d22ae3090affa9de81a63fa8563763339f652d58246bd5edabc091"


def _network_available() -> bool:
    try:
        socket.create_connection(("rpc.mevblocker.io", 443), timeout=4).close()
        return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _network_available(), reason="no network access to rpc.mevblocker.io in this environment"
)


def test_connects_and_reads_chain_head():
    reader = Web3WalletReader(RECOMMENDED_RPC_URL)
    head = reader.w3.eth.block_number
    assert head > 18_000_000, "sanity check: mainnet has passed block 18M long ago"


def test_reads_real_historical_approval_for_a_real_wallet():
    reader = Web3WalletReader(RECOMMENDED_RPC_URL)
    history = reader.get_history(
        REAL_WALLET_WITH_APPROVAL,
        from_block=KNOWN_APPROVAL_BLOCK - 1,
        to_block=KNOWN_APPROVAL_BLOCK + 1,
    )
    assert history.data_source == "live"
    assert history.approvals, "expected at least one real on-chain approval in this exact 3-block window"
    hit = next((a for a in history.approvals if a.tx_hash == KNOWN_APPROVAL_TX), None)
    assert hit is not None, f"expected tx {KNOWN_APPROVAL_TX} in {[a.tx_hash for a in history.approvals]}"
    assert hit.block_number == KNOWN_APPROVAL_BLOCK
    print(f"\nLive approval confirmed: {hit.spender} approved for {hit.amount} "
          f"of token {hit.token_address} at block {hit.block_number}, tx {hit.tx_hash}")


def test_pagination_chunks_a_range_wider_than_the_providers_limit():
    """mevblocker.io's real, live-verified limit is 10,000 blocks per call
    ('range N exceeds limit of 10000'). Ask for 25,000 blocks — more than
    two chunks — and confirm ChunkedLogFetcher pages through all of it
    instead of raising or silently truncating."""
    reader = Web3WalletReader(RECOMMENDED_RPC_URL)
    history = reader.get_history(
        REAL_WALLET_WITH_APPROVAL,
        from_block=KNOWN_APPROVAL_BLOCK - 12_500,
        to_block=KNOWN_APPROVAL_BLOCK + 12_500,
    )
    assert history.scanned_from_block == KNOWN_APPROVAL_BLOCK - 12_500
    assert history.scanned_to_block == KNOWN_APPROVAL_BLOCK + 12_500
    assert any(a.tx_hash == KNOWN_APPROVAL_TX for a in history.approvals)


def test_tx_count_is_real_and_positive():
    reader = Web3WalletReader(RECOMMENDED_RPC_URL)
    history = reader.get_history(REAL_WALLET_WITH_APPROVAL, from_block=18_000_000, to_block=18_000_001)
    assert history.tx_count > 0
