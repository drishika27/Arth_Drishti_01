"""
Real crypto-wallet data for Arth Raksha — read-only, address-only.

Sources (all free, no API key required):
  - Blockscout (eth.blockscout.com): balances, token holdings, transaction and
    token-transfer history — an indexer over the real Ethereum chain.
  - CoinGecko: INR prices + 24h change, and daily price history.

Nothing here can move funds: it only ever takes a public address. Nothing is
invented: if a price or a data source is unavailable the field is None and the
response says so, instead of substituting a made-up number.

Spam protection: airdrop-spam tokens carry fake "prices" that would wildly
inflate a portfolio. A token is only counted if CoinGecko (which lists real,
market-listed assets) recognises its contract, or it is on the built-in list
of major tokens. Everything else is hidden and counted in
`hidden_unverified_tokens`.
"""
from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlencode

import httpx
from eth_utils import is_address, to_checksum_address

BLOCKSCOUT = os.environ.get("BLOCKSCOUT_API_URL", "https://eth.blockscout.com/api/v2").rstrip("/")
COINGECKO = os.environ.get("COINGECKO_API_URL", "https://api.coingecko.com/api/v3").rstrip("/")
EXPLORER_TX = "https://etherscan.io/tx/"

# Major ERC-20 contracts (lowercase) that are always treated as recognised.
MAJOR_TOKENS = {
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": "USDC",
    "0xdac17f958d2ee523a2206206994597c13d831ec7": "USDT",
    "0x6b175474e89094c44da98b954eedeac495271d0f": "DAI",
    "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599": "WBTC",
    "0x514910771af9ca656af840dff83e8264ecf986ca": "LINK",
    "0x1f9840a85d5af5bf1d1762f925bdaddc4201f984": "UNI",
    "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2": "WETH",
    "0xae7ab96520de3a18e5e111b5eaab095312d7fe84": "stETH",
    "0x7fc66500c84a76ad7e9c93437bfc5ac33e2ddae9": "AAVE",
}
# CoinGecko ids for the majors, used if the full coin list can't be fetched.
MAJOR_IDS = {
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": "usd-coin", "0xdac17f958d2ee523a2206206994597c13d831ec7": "tether",
    "0x6b175474e89094c44da98b954eedeac495271d0f": "dai", "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599": "wrapped-bitcoin",
    "0x514910771af9ca656af840dff83e8264ecf986ca": "chainlink", "0x1f9840a85d5af5bf1d1762f925bdaddc4201f984": "uniswap",
    "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2": "weth", "0xae7ab96520de3a18e5e111b5eaab095312d7fe84": "staked-ether",
    "0x7fc66500c84a76ad7e9c93437bfc5ac33e2ddae9": "aave",
}


class ChainDataError(Exception):
    """A data provider was unreachable or returned something unusable."""


class NotIndexed(Exception):
    """Provider has never seen this address (a brand-new, empty wallet)."""


# --------------------------------------------------------------------------
# HTTP with a small TTL cache + retry/backoff (free providers rate-limit)
# --------------------------------------------------------------------------
_client = httpx.Client(timeout=25, follow_redirects=True, headers={"accept": "application/json"})
_cache: dict[str, tuple[float, Any]] = {}
_failed: dict[str, float] = {}
_overviews: dict[tuple, tuple[float, dict]] = {}
_lock = threading.Lock()
OVERVIEW_TTL = 120


def _get(url: str, params: Optional[dict] = None, ttl: int = 60) -> Any:
    key = url + "?" + urlencode(sorted((params or {}).items()))
    now = time.time()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
        if now - _failed.get(key, 0) < 45:      # don't hammer a provider that just rate-limited us
            raise ChainDataError(f"{url.split('/')[2]} is rate-limiting requests; try again shortly")
    headers = {}
    if "coingecko" in url and os.environ.get("COINGECKO_API_KEY"):
        headers["x-cg-demo-api-key"] = os.environ["COINGECKO_API_KEY"]
    last: Exception | None = None
    for attempt in range(2):
        try:
            r = _client.get(url, params=params, headers=headers)
        except httpx.HTTPError as exc:
            last = exc
            time.sleep(0.8)
            continue
        if r.status_code == 404:
            raise NotIndexed(url)
        if r.status_code == 429 or r.status_code >= 500:
            last = ChainDataError(f"{r.status_code} from {url.split('/')[2]}")
            time.sleep(1.5)
            continue
        if r.status_code >= 400:
            raise ChainDataError(f"{r.status_code} from {url.split('/')[2]}")
        data = r.json()
        with _lock:
            _cache[key] = (time.time(), data)
        return data
    with _lock:
        _failed[key] = time.time()
    raise ChainDataError(f"Data provider unavailable ({url.split('/')[2]}): {last}")


def clear_cache() -> None:
    with _lock:
        _cache.clear()
        _failed.clear()
        _overviews.clear()


# --------------------------------------------------------------------------
def normalize_address(address: str) -> str:
    """Returns the lowercase 0x address, or raises ValueError."""
    a = (address or "").strip()
    if not (a.startswith("0x") and len(a) == 42 and is_address(a)):
        raise ValueError("Enter a valid Ethereum address (0x followed by 40 hex characters).")
    if a != a.lower() and a != to_checksum_address(a):
        raise ValueError("That address has an invalid checksum — check for typos.")
    return a.lower()


def _f(v) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


# ---- Blockscout ----------------------------------------------------------
def _address_info(addr: str) -> dict:
    try:
        return _get(f"{BLOCKSCOUT}/addresses/{addr}") or {}
    except NotIndexed:
        return {}          # never-used address: empty, not an error


def _token_holdings(addr: str) -> list[dict]:
    try:
        rows = _get(f"{BLOCKSCOUT}/addresses/{addr}/token-balances") or []
    except NotIndexed:
        return []
    out = []
    for row in rows:
        t = row.get("token") or {}
        if t.get("type") != "ERC-20":
            continue
        try:
            dec, raw = int(t.get("decimals") or 0), int(row.get("value") or 0)
        except (TypeError, ValueError):
            continue
        contract = (t.get("address_hash") or t.get("address") or "").lower()
        if raw <= 0 or not 0 <= dec <= 36 or not contract:
            continue
        amount = raw / 10 ** dec
        rate = _f(t.get("exchange_rate"))
        out.append({"contract": contract, "symbol": (t.get("symbol") or "?")[:12], "name": (t.get("name") or t.get("symbol") or "")[:40],
                    "decimals": dec, "amount": amount, "rough_usd": amount * rate if rate else 0.0})
    return out


def _transactions(addr: str) -> list[dict]:
    try:
        return (_get(f"{BLOCKSCOUT}/addresses/{addr}/transactions") or {}).get("items", [])
    except NotIndexed:
        return []


def _token_transfers(addr: str) -> list[dict]:
    try:
        return (_get(f"{BLOCKSCOUT}/addresses/{addr}/token-transfers", {"type": "ERC-20"}) or {}).get("items", [])
    except NotIndexed:
        return []


# ---- CoinGecko -----------------------------------------------------------
def _eth_price() -> dict:
    d = _get(f"{COINGECKO}/simple/price", {"ids": "ethereum", "vs_currencies": "inr", "include_24hr_change": "true"}, ttl=60)
    e = d.get("ethereum") or {}
    return {"price_inr": _f(e.get("inr")), "change_24h_pct": _f(e.get("inr_24h_change"))}


def _coin_ids() -> dict[str, str]:
    """contract(lowercase) -> CoinGecko id, for every Ethereum token CoinGecko lists (cached 24h).
    Membership is what "recognised" means: airdrop-spam tokens aren't in this list.
    CoinGecko's free tier prices only ONE contract per request, so we map contracts to ids
    once and then price many tokens in a single /simple/price call."""
    ids = dict(MAJOR_IDS)
    try:
        for row in _get(f"{COINGECKO}/coins/list", {"include_platform": "true"}, ttl=86400) or []:
            c = ((row.get("platforms") or {}).get("ethereum") or "").lower()
            if c.startswith("0x") and len(c) == 42:
                ids.setdefault(c, row["id"])
    except ChainDataError:
        pass        # fall back to the built-in majors
    return ids


def _top_market_ids() -> set[str]:
    """CoinGecko ids of the ~500 largest Ethereum-ecosystem assets by market cap (cached 6h).
    Only these are counted in the portfolio total: a listed-but-tiny token can carry an
    unrealisable "price" (e.g. billions of airdropped meme tokens) that would inflate the total."""
    ids: set[str] = set()
    try:
        for page in ("1", "2"):
            rows = _get(f"{COINGECKO}/coins/markets", {"vs_currency": "inr", "category": "ethereum-ecosystem",
                                                       "order": "market_cap_desc", "per_page": "250", "page": page}, ttl=21600)
            ids.update(r["id"] for r in rows or [])
    except ChainDataError:
        pass
    return ids


def warm() -> None:
    """Pre-load the big cached lists so a user's first request isn't slow. Never raises."""
    try:
        _coin_ids()
        _top_market_ids()
    except Exception:
        pass


def _prices_by_id(cg_ids: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    uniq = list(dict.fromkeys(cg_ids))
    for i in range(0, len(uniq), 40):
        d = _get(f"{COINGECKO}/simple/price", {"ids": ",".join(uniq[i:i + 40]), "vs_currencies": "inr",
                                               "include_24hr_change": "true"}, ttl=60)
        for cid, v in (d or {}).items():
            if _f(v.get("inr")) is not None:
                out[cid] = {"price_inr": _f(v["inr"]), "change_24h_pct": _f(v.get("inr_24h_change"))}
    return out


def _history(cg_id: str) -> list[float]:
    d = _get(f"{COINGECKO}/coins/{cg_id}/market_chart", {"vs_currency": "inr", "days": "30", "interval": "daily"}, ttl=600)
    return [p[1] for p in d.get("prices", []) if len(p) == 2][-30:]


# --------------------------------------------------------------------------
def _iso(ts: Optional[str]) -> Optional[str]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
    except ValueError:
        return None


def _short(a: str) -> str:
    return f"{a[:6]}…{a[-4:]}" if a else ""


def build_assets(addr: str, info: dict, holdings: list[dict], eth: dict, notes: list[str]) -> tuple[list[dict], list[dict], int, dict]:
    """Native ETH + recognised tokens, priced. Returns (counted_assets, other_recognised_assets,
    hidden_unrecognised_count, price_map). Only `counted_assets` make up the portfolio total."""
    eth_amount = int(info.get("coin_balance") or 0) / 1e18
    assets: list[dict] = [{"symbol": "ETH", "name": "Ethereum", "contract": None, "amount": eth_amount,
                           "price_inr": eth["price_inr"], "change_24h_pct": eth["change_24h_pct"]}]

    # A token counts only if CoinGecko lists its contract (or it is a built-in major).
    by_contract = {h["contract"]: h for h in holdings}
    cg = _coin_ids()
    recognised_held = sorted((c for c in by_contract if c in cg), key=lambda c: -by_contract[c]["rough_usd"])[:40]
    prices_by_id: dict[str, dict] = {}
    try:
        prices_by_id = _prices_by_id([cg[c] for c in recognised_held]) if recognised_held else {}
    except ChainDataError as exc:
        notes.append(f"Token prices are unavailable right now ({exc}); token balances are shown without values.")
    top_ids = _top_market_ids()
    for c in recognised_held:
        h, p = by_contract[c], prices_by_id.get(cg[c], {})
        assets.append({"symbol": h["symbol"], "name": h["name"], "contract": c, "cg_id": cg[c], "amount": h["amount"],
                       "price_inr": p.get("price_inr"), "change_24h_pct": p.get("change_24h_pct"),
                       "counted": c in MAJOR_TOKENS or cg[c] in top_ids})
    hidden = len(holdings) - len(recognised_held)
    assets[0]["cg_id"], assets[0]["counted"] = "ethereum", True
    recognised_prices = {c: prices_by_id.get(cg[c], {}) for c in recognised_held}
    recognised_prices["__ids__"] = cg          # lets the caller recognise tokens that appear only in transfers

    for a in assets:
        a["value_inr"] = round(a["amount"] * a["price_inr"], 2) if a["price_inr"] is not None else None
    key = lambda a: (a["value_inr"] is None, -(a["value_inr"] or 0), -a["amount"])  # noqa: E731
    counted = sorted((a for a in assets if a["counted"] and (a["amount"] > 0 or a["symbol"] == "ETH")), key=key)
    others = sorted((a for a in assets if not a["counted"] and a["amount"] > 0), key=key)[:15]
    total = sum(a["value_inr"] for a in counted if a["value_inr"] is not None)
    for a in counted:
        a["allocation_pct"] = round(a["value_inr"] / total * 100, 1) if total and a["value_inr"] is not None else None
    for a in others:
        a["allocation_pct"] = None
    return counted, others, hidden, recognised_prices


def _portfolio_change(assets: list[dict]) -> Optional[float]:
    """Exact value-weighted 24h change over assets that have both a value and a change figure."""
    now = prev = 0.0
    for a in assets:
        if a["value_inr"] and a["change_24h_pct"] is not None and a["change_24h_pct"] > -100:
            now += a["value_inr"]
            prev += a["value_inr"] / (1 + a["change_24h_pct"] / 100)
    return round((now - prev) / prev * 100, 2) if prev else None


def _performance(assets: list[dict]) -> Optional[dict]:
    """Current holdings valued at each of the last 30 days' prices (NOT the wallet's true history,
    which would need historical balances). Only returned when the priced holdings cover most of the value."""
    priced = [a for a in assets if a["value_inr"]]
    total = sum(a["value_inr"] for a in priced)
    if not total:
        return None
    series: list[tuple[float, list[float]]] = []
    covered = 0.0
    for a in priced[:3]:
        try:
            hist = _history(a["cg_id"])
        except (ChainDataError, NotIndexed, KeyError):
            continue
        if len(hist) >= 7:
            series.append((a["amount"], hist))
            covered += a["value_inr"]
    if not series or covered / total < 0.5:
        return None
    n = min(len(h) for _, h in series)
    today = datetime.now(timezone.utc).date()
    points = []
    for i in range(n):
        d = today.toordinal() - (n - 1 - i)
        points.append({"day": datetime.fromordinal(d).date().isoformat(),
                       "value_inr": round(sum(amt * h[len(h) - n + i] for amt, h in series), 2)})
    return {"points": points, "coverage_pct": round(covered / total * 100, 1),
            "note": "Your current holdings valued at each day's market price."}


def _normalize_transactions(addr: str, native: list[dict], transfers: list[dict], eth_price: Optional[float],
                            recognised: dict[str, Optional[dict]], include_unverified: bool) -> tuple[list[dict], int]:
    rows: list[dict] = []
    for t in native:
        frm = ((t.get("from") or {}).get("hash") or "").lower()
        to = ((t.get("to") or {}).get("hash") or "").lower()
        value = int(t.get("value") or 0) / 1e18
        fee = int((t.get("fee") or {}).get("value") or 0) / 1e18
        status = {"ok": "Confirmed", "error": "Failed"}.get(t.get("status"), "Pending")
        if frm == addr and to == addr:
            kind = "Self"
        elif frm == addr:
            kind = "Sent" if value > 0 else "Contract call"
        else:
            kind = "Received"
        rows.append({
            "id": f"{t.get('hash')}:eth", "hash": t.get("hash"), "hash_short": _short(t.get("hash") or ""),
            "type": kind, "asset": "ETH", "amount": value,
            "value_now_inr": round(value * eth_price, 2) if eth_price and value else None,
            "from": _short(frm), "to": _short(to), "network": "Ethereum", "status": status,
            "gas_inr": round(fee * eth_price, 2) if eth_price and frm == addr else None,
            "date": _iso(t.get("timestamp")), "explorer_url": EXPLORER_TX + (t.get("hash") or ""),
            "method": t.get("method"), "verified_token": True,
        })
    hidden = 0
    for t in transfers:
        tok = t.get("token") or {}
        contract = (tok.get("address_hash") or tok.get("address") or "").lower()
        ok = contract in MAJOR_TOKENS or contract in recognised.get("__ids__", {})
        if not ok and not include_unverified:
            hidden += 1
            continue
        tot = t.get("total") or {}
        try:
            amount = int(tot.get("value") or 0) / 10 ** int(tot.get("decimals") or tok.get("decimals") or 0)
        except (TypeError, ValueError):
            continue
        frm = ((t.get("from") or {}).get("hash") or "").lower()
        to = ((t.get("to") or {}).get("hash") or "").lower()
        price = (recognised.get(contract) or {}).get("price_inr")
        h = t.get("transaction_hash")
        rows.append({
            "id": f"{h}:{t.get('log_index')}", "hash": h, "hash_short": _short(h or ""),
            "type": "Sent" if frm == addr else "Received", "asset": (tok.get("symbol") or "?")[:12], "amount": amount,
            "value_now_inr": round(amount * price, 2) if price else None,
            "from": _short(frm), "to": _short(to), "network": "Ethereum", "status": "Confirmed", "gas_inr": None,
            "date": _iso(t.get("timestamp")), "explorer_url": EXPLORER_TX + (h or ""),
            "method": t.get("method"), "verified_token": ok,
        })
    rows.sort(key=lambda r: r["date"] or "", reverse=True)
    return rows[:60], hidden


# --------------------------------------------------------------------------
def get_overview(address: str, verified_owner: bool = False, include_unverified: bool = False,
                 force: bool = False) -> dict:
    """Everything the Arth Raksha pages show for one real address (cached for OVERVIEW_TTL seconds).
    The 30-day chart is loaded separately via get_performance() — it needs slow price-history calls."""
    addr = normalize_address(address)
    ck = (addr, verified_owner, include_unverified)
    with _lock:
        hit = _overviews.get(ck)
    if hit and not force and time.time() - hit[0] < OVERVIEW_TTL:
        return hit[1]
    data = _build_overview(addr, verified_owner, include_unverified)
    with _lock:
        _overviews[ck] = (time.time(), data)
    return data


def get_performance(address: str, verified_owner: bool = False) -> dict:
    """30-day value of the wallet's current holdings. `available` is False when the price
    provider can't supply enough history right now (never fabricated)."""
    ov = get_overview(address, verified_owner)
    try:
        perf = _performance(ov["assets"])
    except Exception:
        perf = None
    if perf is None:
        return {"available": False, "reason": "Price history is unavailable right now or doesn't cover enough of this portfolio."}
    return {"available": True, **perf}


def _build_overview(addr: str, verified_owner: bool, include_unverified: bool) -> dict:
    notes: list[str] = []
    try:
        with ThreadPoolExecutor(max_workers=5) as pool:
            f_info = pool.submit(_address_info, addr)
            f_hold = pool.submit(_token_holdings, addr)
            f_txs = pool.submit(_transactions, addr)
            f_tt = pool.submit(_token_transfers, addr)
            f_eth = pool.submit(_eth_price)
            info, holdings, txs, tts = f_info.result(), f_hold.result(), f_txs.result(), f_tt.result()
            try:
                eth = f_eth.result()
            except ChainDataError as exc:
                eth = {"price_inr": None, "change_24h_pct": None}
                notes.append(f"Prices are unavailable right now ({exc}); balances are shown without values.")
    except ChainDataError as exc:
        raise ChainDataError(f"Could not read the blockchain data provider: {exc}") from exc

    assets, other_assets, hidden_tokens, recognised = build_assets(addr, info, holdings, eth, notes)
    # Tokens seen only in transfers (no longer held) are priced too, so history shows values for real tokens.
    ids = recognised.get("__ids__", {})
    seen = [c for c in dict.fromkeys(((t.get("token") or {}).get("address_hash") or "").lower() for t in tts)
            if c in ids and c not in recognised][:30]
    if seen:
        try:
            by_id = _prices_by_id([ids[c] for c in seen])
            recognised.update({c: by_id.get(ids[c], {}) for c in seen})
        except ChainDataError:
            pass
    txn, hidden_txns = _normalize_transactions(addr, txs, tts, eth["price_inr"], recognised, include_unverified)

    total = sum(a["value_inr"] for a in assets if a["value_inr"] is not None)
    priced_all = all(a["value_inr"] is not None for a in assets if a["amount"] > 0)
    is_scam = bool(info.get("is_scam"))
    return {
        "data_mode": "live", "connected": True,
        "wallet": {"address": addr, "network": "Ethereum Mainnet", "watch_only": not verified_owner,
                   "verified": verified_owner, "ens": info.get("ens_domain_name"), "is_contract": bool(info.get("is_contract"))},
        "total_value_inr": round(total, 2) if (total or priced_all) else None,
        "change_24h_pct": _portfolio_change(assets), "assets": assets, "other_assets": other_assets,
        "other_assets_note": ("Small or illiquid tokens are listed here but NOT counted in your total — their "
                              "quoted prices often can't actually be realised (e.g. airdropped tokens)." if other_assets else None),
        "transactions": txn, "performance_30d": None,
        "hidden_unverified_tokens": hidden_tokens, "hidden_unverified_transfers": hidden_txns,
        "security": {
            "risk_label": "Flagged" if is_scam else "Not scanned", "approvals": None, "approvals_scanned": False,
            "address_checks": None,
            "checks": [
                {"ok": True, "title": "Address format", "detail": "Valid Ethereum address"},
                {"ok": not is_scam, "title": "Known scam flag", "detail": "Flagged as a scam address by the block explorer" if is_scam else "Not flagged by the block explorer"},
                {"ok": True, "title": "Account type", "detail": "Smart-contract wallet" if info.get("is_contract") else "Standard wallet (EOA)"},
                {"ok": verified_owner, "title": "Ownership", "detail": "You proved control by signing in with this wallet" if verified_owner else "Watch-only — connect this wallet to prove ownership"},
                {"ok": hidden_tokens == 0, "title": "Suspicious tokens", "detail": f"{hidden_tokens} unrecognised tokens were hidden (likely airdrop spam — don't interact with them)" if hidden_tokens else "None detected"},
            ],
        },
        "notes": notes,
        "sources": {"balances_and_history": "Blockscout (Ethereum mainnet)", "prices": "CoinGecko"},
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
