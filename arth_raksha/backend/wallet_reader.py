"""
Reads a wallet's OWN transaction and approval history from-chain.

Real implementation using web3.py + standard JSON-RPC (eth_getLogs) with
proper eth_getLogs pagination — see ChunkedLogFetcher below. Verified live
against real Ethereum mainnet RPC endpoints (September 2026):

  - https://rpc.mevblocker.io — free, no API key, genuinely unrestricted
    topic-only eth_getLogs (does not require an "address" filter) with real
    archive-depth data. Its only real constraint, confirmed by a live probe,
    is a 10,000-block range per call ("range N exceeds limit of 10000") —
    exactly the kind of limit ChunkedLogFetcher below is built to discover
    and chunk around automatically. This is the default RECOMMENDED_RPC_URL.
  - https://ethereum-rpc.publicnode.com — free, no API key, but rejects
    topic-only queries ("Please specify an address in your request") and
    additionally refuses to look back more than a few thousand blocks
    without a paid "archive" token. Kept as a documented fallback that
    still works if you pass explicit token_addresses and a shallow lookback.
  - Your own Infura/Alchemy/QuickNode/Ankr URL (set via rpc_url or the
    ETH_RPC_URL env var) works too and typically allows deeper archive
    history at a larger or smaller block-range limit — ChunkedLogFetcher
    adapts to whatever limit the provider reports rather than assuming one.

This was tested against real wallets with real approval history from this
build environment — see tests/test_wallet_reader_live.py, which is skipped
automatically when there is no network access, and prints the real
transaction hashes and block numbers it found when there is.
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from typing import Optional, Protocol

APPROVAL_TOPIC = "0x8c5be1e5ebec7d5bd14f71427d1e84f3dd0314c0f7b2291e5b200ac8c7c3b925"  # ERC20 Approval(address,address,uint256)
UNLIMITED_APPROVAL_THRESHOLD = 2 ** 96  # treat anything absurdly large as "unlimited"

RECOMMENDED_RPC_URL = "https://rpc.mevblocker.io"
DEFAULT_CHUNK_BLOCKS = 10_000       # matches mevblocker's real, verified limit
DEFAULT_LOOKBACK_BLOCKS = 50_000    # ~1 week; keeps an interactive API call fast
MAX_RETRIES = 4
CACHE_TTL_SECONDS = 60              # short-lived: this is a safety tool, not a ticker
MIN_RPC_CALL_INTERVAL_SECONDS = 0.12  # a real throttle, not just a cache — see RateLimiter


class RateLimiter:
    """A minimum-interval throttle shared across every RPC call this
    backend makes, so scoring a wallet with many spenders (see
    risk_engine.py's MAX_ML_LOOKUPS_PER_REQUEST, added after a real
    hyperactive-wallet request took over a minute) doesn't also look like
    a burst of abuse to a shared free public RPC. One process-wide
    instance is shared by every Web3WalletReader — the point is being a
    good citizen of the *provider*, not of any one wallet's scan."""

    def __init__(self, min_interval_seconds: float = MIN_RPC_CALL_INTERVAL_SECONDS):
        self.min_interval = min_interval_seconds
        # None, not 0.0 — a real monotonic clock never returns exactly 0.0,
        # but a fake/mocked one easily could, which would make the very
        # first call wrongly think a previous call happened at time zero.
        self._last_call: Optional[float] = None

    def wait(self) -> None:
        now = time.monotonic()
        if self._last_call is not None:
            elapsed = now - self._last_call
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
        self._last_call = time.monotonic()


_rpc_rate_limiter = RateLimiter()


@dataclass
class Approval:
    token_address: str
    spender: str
    amount: int
    tx_hash: str
    block_number: int
    spender_verified: bool = False

    @property
    def is_unlimited(self) -> bool:
        return self.amount >= UNLIMITED_APPROVAL_THRESHOLD


@dataclass
class WalletHistory:
    address: str
    approvals: list[Approval] = field(default_factory=list)
    tx_count: int = 0
    # Honest metadata about what was actually scanned — never silently
    # partial. Populated by Web3WalletReader; left at defaults by the mock.
    data_source: str = "mock"
    chain_head_block: Optional[int] = None
    scanned_from_block: Optional[int] = None
    scanned_to_block: Optional[int] = None
    archive_limit_reached: bool = False
    rpc_url: Optional[str] = None
    warnings: list[str] = field(default_factory=list)


class WalletReader(Protocol):
    def get_history(self, address: str) -> WalletHistory: ...


# -- error-message parsing -------------------------------------------------
# Every public RPC phrases its eth_getLogs block-range limit differently.
# Rather than hardcoding one provider's limit, we parse whatever number the
# node itself reports and shrink to that — verified against real error
# strings from mevblocker.io, publicnode, 1rpc.io and blastapi.io.
_RANGE_LIMIT_PATTERNS = [
    re.compile(r"exceeds limit of (\d+)", re.IGNORECASE),
    re.compile(r"limited to (\d+) blocks", re.IGNORECASE),
    re.compile(r"maximum allowed is (\d+)", re.IGNORECASE),
    re.compile(r"must not exceed (\d+) blocks", re.IGNORECASE),
    re.compile(r"0\s*-\s*(\d+)\s*blocks range", re.IGNORECASE),
    re.compile(r"range\s+is\s+too\s+large.*?(\d+)", re.IGNORECASE),
]


def _extract_range_limit(message: str) -> Optional[int]:
    for pattern in _RANGE_LIMIT_PATTERNS:
        m = pattern.search(message)
        if m:
            return int(m.group(1))
    return None


def _is_archive_required(message: str) -> bool:
    lowered = message.lower()
    return "archive" in lowered or "personal token" in lowered


def _is_rate_limited(message: str) -> bool:
    lowered = message.lower()
    return any(s in lowered for s in ("rate limit", "too many requests", "compute units", "429"))


class ChunkedLogFetcher:
    """Paginates eth_getLogs over a block range, adapting chunk size down
    when the RPC reports a smaller limit than we guessed, retrying with
    backoff on transient/rate-limit errors, and stopping (without raising)
    the moment the node says it needs an archive/paid tier for older data
    — recording exactly where it stopped rather than silently truncating.
    """

    def __init__(self, w3, chunk_blocks: int = DEFAULT_CHUNK_BLOCKS):
        self.w3 = w3
        self.chunk_blocks = chunk_blocks

    def fetch(self, from_block: int, to_block: int, topics: list, address: list[str] | None = None):
        logs: list = []
        warnings: list[str] = []
        archive_limit_reached = False
        actual_from = from_block
        chunk = self.chunk_blocks

        current_to = to_block
        while current_to >= from_block:
            current_from = max(from_block, current_to - chunk + 1)
            filt = {"fromBlock": current_from, "toBlock": current_to, "topics": topics}
            if address:
                filt["address"] = address

            attempt = 0
            while True:
                try:
                    _rpc_rate_limiter.wait()
                    chunk_logs = self.w3.eth.get_logs(filt)
                    logs.extend(chunk_logs)
                    break
                except Exception as exc:  # noqa: BLE001 - provider errors vary in type
                    msg = str(exc)
                    if _is_archive_required(msg):
                        archive_limit_reached = True
                        actual_from = current_to + 1  # we never got below here
                        warnings.append(
                            f"Stopped at block {current_to}: provider requires a paid/archive "
                            f"token for older data ({msg[:120]})"
                        )
                        current_from = from_block - 1  # sentinel: break outer loop below
                        break
                    smaller = _extract_range_limit(msg)
                    if smaller and smaller < chunk:
                        chunk = max(1, smaller)
                        filt["fromBlock"] = current_from = max(from_block, current_to - chunk + 1)
                        continue  # retry immediately with the corrected chunk size
                    if _is_rate_limited(msg) and attempt < MAX_RETRIES:
                        attempt += 1
                        time.sleep(min(2 ** attempt * 0.25, 5))
                        continue
                    if attempt < MAX_RETRIES:
                        attempt += 1
                        time.sleep(0.5)
                        continue
                    warnings.append(f"Giving up on blocks {current_from}-{current_to}: {msg[:150]}")
                    break

            if archive_limit_reached and current_from == from_block - 1:
                break
            current_to = current_from - 1

        return logs, actual_from, warnings, archive_limit_reached


class Web3WalletReader:
    """Real reader. Construct with an RPC url; call get_history(address)."""

    def __init__(self, rpc_url: str | None = None, chain_name: str = "ethereum"):
        from web3 import Web3
        self.rpc_url = rpc_url or os.environ.get("ETH_RPC_URL") or RECOMMENDED_RPC_URL
        self.chain_name = chain_name
        self.w3 = Web3(Web3.HTTPProvider(self.rpc_url, request_kwargs={"timeout": 15}))
        self._cache: dict[str, tuple[float, WalletHistory]] = {}

    def get_history(
        self,
        address: str,
        from_block: Optional[int] = None,
        to_block: str | int = "latest",
        lookback_blocks: int = DEFAULT_LOOKBACK_BLOCKS,
        token_addresses: Optional[list[str]] = None,
        graph_store=None,
    ) -> WalletHistory:
        """`graph_store`, if given (a Neo4jGraphStore), records every
        approval discovered in this scan into the graph — raw on-chain
        facts only (see graph.py: verification/scam flags are a separate,
        later write owned by risk_engine.py). A graph write failure never
        breaks the scan itself; it's appended to `warnings` instead."""
        address = self.w3.to_checksum_address(address)

        cache_key = f"{address}:{from_block}:{to_block}:{lookback_blocks}"
        cached = self._cache.get(cache_key)
        if cached and (time.time() - cached[0]) < CACHE_TTL_SECONDS:
            return cached[1]

        _rpc_rate_limiter.wait()
        head = self.w3.eth.block_number
        resolved_to = head if to_block == "latest" else int(to_block)
        resolved_from = from_block if from_block is not None else max(0, resolved_to - lookback_blocks)

        padded_owner = "0x" + address[2:].rjust(64, "0").lower()
        fetcher = ChunkedLogFetcher(self.w3, chunk_blocks=DEFAULT_CHUNK_BLOCKS)
        raw_logs, actual_from, warnings, archive_hit = fetcher.fetch(
            resolved_from, resolved_to,
            topics=[APPROVAL_TOPIC, padded_owner],
            address=token_addresses,
        )

        approvals = []
        for log in raw_logs:
            # HexBytes.hex() drops the "0x" prefix as of web3.py v7+ / newer
            # hexbytes — normalize explicitly rather than depending on that.
            topic_hex = log["topics"][2].hex()
            spender = "0x" + topic_hex[-40:]
            amount = int(log["data"].hex(), 16) if log["data"] else 0
            tx_hash = log["transactionHash"].hex()
            if not tx_hash.startswith("0x"):
                tx_hash = "0x" + tx_hash
            approvals.append(Approval(
                token_address=log["address"],
                spender=self.w3.to_checksum_address(spender),
                amount=amount,
                tx_hash=tx_hash,
                block_number=log["blockNumber"],
            ))
        approvals.sort(key=lambda a: a.block_number)

        if graph_store is not None:
            from .graph import ApprovalEvent
            for a in approvals:
                try:
                    graph_store.record_approval(address, a.spender, ApprovalEvent(
                        tx_hash=a.tx_hash, token_address=a.token_address, amount=a.amount,
                        is_unlimited=a.is_unlimited, block_number=a.block_number,
                    ))
                except Exception as exc:
                    warnings.append(f"Graph write failed for {a.tx_hash}: {exc}")

        _rpc_rate_limiter.wait()
        tx_count = self.w3.eth.get_transaction_count(address)
        history = WalletHistory(
            address=address,
            approvals=approvals,
            tx_count=tx_count,
            data_source="live",
            chain_head_block=head,
            scanned_from_block=actual_from,
            scanned_to_block=resolved_to,
            archive_limit_reached=archive_hit,
            rpc_url=self.rpc_url,
            warnings=warnings,
        )
        self._cache[cache_key] = (time.time(), history)
        return history

    def clear_cache(self) -> None:
        self._cache.clear()


class MockWalletReader:
    """Deterministic, offline reader for demo/testing. Returns a small
    realistic-looking history so the risk-scoring pipeline, API, and
    frontend all have real (if synthetic) data to work with without any
    network access. Clearly labelled as mock everywhere it's surfaced."""

    def __init__(self, fixture: WalletHistory | None = None):
        self._fixture = fixture

    def get_history(self, address: str) -> WalletHistory:
        if self._fixture is not None:
            return self._fixture
        return WalletHistory(
            address=address,
            tx_count=42,
            data_source="mock",
            approvals=[
                Approval(
                    token_address="0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
                    spender="0x00000000000000000000000000000000DeaDBeef",
                    amount=2 ** 256 - 1,  # unlimited
                    tx_hash="0xmockunlimitedapproval0001",
                    block_number=18000001,
                    spender_verified=False,
                ),
                Approval(
                    token_address="0xdAC17F958D2ee523a2206206994597C13D831ec7",
                    spender="0x1111111254EEB25477B68fb85Ed929f73A960582",
                    amount=1_000_000,
                    tx_hash="0xmockcapapproval0002",
                    block_number=18010002,
                    spender_verified=True,
                ),
            ],
        )
