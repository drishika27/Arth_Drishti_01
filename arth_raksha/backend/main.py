"""
Arth Raksha backend — FastAPI app.

Endpoints:
  POST /auth/token           -> trade an API key for a 1-hour bearer token
  POST /wallet/connect       -> read wallet history (mock reader by default;
                                 pass "live": true for a real chain)      [auth]
  GET  /wallet/{addr}/risk   -> risk score + findings for a connected wallet [auth]
  POST /address-book         -> add a saved contact                      [auth]
  GET  /address-book/{addr}  -> list this wallet's own saved contacts    [auth]
  POST /send/draft           -> draft a transaction from natural language [auth]
  POST /send/{draft_id}/confirm -> user confirms; returns wallet-provider payload [auth]
  POST /revoke/draft         -> draft one or more approval revocations   [auth]
  POST /revoke/{draft_id}/confirm -> user confirms; returns wallet-provider payload [auth]
  GET  /wallet/{addr}/report -> export the risk findings as Markdown/PDF [auth]
  GET  /health

[auth] endpoints require `Authorization: Bearer <token>` — see
shared_engine/auth.py. Full interactive docs (including how to
authorize) at /docs once running.

Run:
  uvicorn arth_raksha.backend.main:app --reload --port 8002

The AI NEVER signs anything here. Signing happens client-side, in the
frontend, via the user's own wallet (MetaMask/WalletConnect) after they
review the confirmation screen — see transaction.py for the enforcement.
"""
from __future__ import annotations

import os
import sys
import uuid

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

from shared_engine import (
    GroundedExplainer, Language, Depth, issue_token, require_auth,
    ReportSection, render_markdown, render_pdf,
)
from .wallet_reader import MockWalletReader, Web3WalletReader, WalletHistory
from .risk_engine import score_wallet
from .address_book import AddressBook, Contact
from .transaction import draft_transaction, simulate_transaction, UnknownRecipientError, TransactionDraft
from .revoke import draft_revoke, simulate_revoke, RevokeDraft

app = FastAPI(
    title="Arth Raksha API",
    version="0.2.0",
    description=(
        "Wallet safety for the wallet's OWN owner only — reads and explains a "
        "connected wallet's own approval history and risk, and drafts (never "
        "signs) sends/revokes for the user's own wallet to sign themselves. "
        "Most endpoints require a bearer token — call POST /auth/token first."
    ),
)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

_AUTH = [Depends(require_auth)]

_explainer = GroundedExplainer()
_address_books: dict[str, AddressBook] = {}   # keyed by wallet address
_wallet_cache: dict[str, WalletHistory] = {}
_wallet_rpc_url: dict[str, str] = {}          # keyed by wallet address; only set for live connections
_drafts: dict[str, TransactionDraft] = {}
_revoke_drafts: dict[str, RevokeDraft] = {}


def _live_w3_for(wallet_address: str):
    """Returns a live web3 connection for simulation if this wallet was
    connected with live=True, else None — simulation is simply skipped
    (never faked) for mock wallets, exactly like the ML signal."""
    rpc_url = _wallet_rpc_url.get(wallet_address.lower())
    return Web3WalletReader(rpc_url).w3 if rpc_url else None


def _get_graph_store():
    """Lazily connects to Neo4j (see graph.py / docker-compose.neo4j.yml).
    Returns None — never raises — if NEO4J_PASSWORD isn't set or the
    instance isn't reachable, so the whole API keeps working with graph
    features simply absent, exactly like every other optional signal here."""
    if not os.environ.get("NEO4J_PASSWORD"):
        return None
    if not hasattr(_get_graph_store, "_instance"):
        try:
            from .graph import Neo4jGraphStore
            store = Neo4jGraphStore()
            store.verify_connectivity()
            store.ensure_constraints()
            _get_graph_store._instance = store
        except Exception:
            _get_graph_store._instance = None
    return _get_graph_store._instance


class TokenRequest(BaseModel):
    api_key: str = Field(..., description="Server-configured API key (see ARTHDRISHTI_API_KEYS).")


class ConnectRequest(BaseModel):
    address: str
    live: bool = False           # if True, read real on-chain data instead of the mock fixture
    rpc_url: str | None = None   # override the default free RPC (rpc.mevblocker.io); implies live=True
    lookback_blocks: int | None = None  # how far back from to_block to scan (default ~50k blocks)
    from_block: int | None = None       # explicit start block (overrides lookback_blocks)
    to_block: int | None = None         # explicit end block (default: chain head)


class ContactRequest(BaseModel):
    wallet_address: str
    name: str
    address: str
    chain: str = "ethereum"


class DraftRequest(BaseModel):
    wallet_address: str
    request: str


class RevokeApprovalRef(BaseModel):
    token_address: str
    spender_address: str


class RevokeDraftRequest(BaseModel):
    wallet_address: str
    approvals: list[RevokeApprovalRef]   # batch: one or more approvals to revoke
    chain: str = "ethereum"


@app.get("/health", summary="Liveness check — no auth required")
def health():
    return {"status": "ok"}


@app.post("/auth/token", summary="Trade an API key for a 1-hour bearer token")
def get_token(req: TokenRequest):
    try:
        return issue_token(req.api_key)
    except PermissionError as exc:
        raise HTTPException(401, str(exc))


@app.post("/wallet/connect", dependencies=_AUTH)
def connect(req: ConnectRequest):
    if req.live or req.rpc_url:
        reader = Web3WalletReader(req.rpc_url)
        kwargs = {}
        if req.lookback_blocks:
            kwargs["lookback_blocks"] = req.lookback_blocks
        if req.from_block is not None:
            kwargs["from_block"] = req.from_block
        if req.to_block is not None:
            kwargs["to_block"] = req.to_block
        graph_store = _get_graph_store()
        if graph_store is not None:
            kwargs["graph_store"] = graph_store
        try:
            history = reader.get_history(req.address, **kwargs)
        except Exception as exc:
            raise HTTPException(502, f"Could not reach RPC: {exc}")
        _wallet_rpc_url[req.address.lower()] = reader.rpc_url
    else:
        history = MockWalletReader().get_history(req.address)
        _wallet_rpc_url.pop(req.address.lower(), None)
    _wallet_cache[req.address.lower()] = history
    _address_books.setdefault(req.address.lower(), AddressBook())
    return {
        "address": history.address,
        "tx_count": history.tx_count,
        "approval_count": len(history.approvals),
        "data_source": history.data_source,
        "chain_head_block": history.chain_head_block,
        "scanned_from_block": history.scanned_from_block,
        "scanned_to_block": history.scanned_to_block,
        "archive_limit_reached": history.archive_limit_reached,
        "rpc_url": history.rpc_url,
        "warnings": history.warnings,
    }


def _score_and_explain(address: str, language: Language, depth: Depth, use_ml: bool):
    """Shared by /risk and /report so both render from exactly the same
    computation — a report that could ever disagree with the live risk
    view would be its own kind of ungrounded claim."""
    history = _wallet_cache.get(address.lower())
    if history is None:
        raise HTTPException(404, "Connect this wallet first via /wallet/connect")

    # The ML scam-classifier signal (arth_raksha/ml/) only ever runs against
    # a real spender's real on-chain activity — it needs a live connection,
    # so it's simply absent (not faked) for mock wallets or when use_ml=false.
    w3 = None
    rpc_url = _wallet_rpc_url.get(address.lower())
    if use_ml and rpc_url:
        w3 = Web3WalletReader(rpc_url).w3

    findings, scored, overall = score_wallet(history, w3=w3, graph_store=_get_graph_store())
    score_by_id = {s.finding_id: s for s in scored}
    explanations = {f.finding_id: _explainer.explain(f, language=language, depth=depth).text for f in findings}
    return history, findings, score_by_id, explanations, overall


@app.get("/wallet/{address}/risk", dependencies=_AUTH)
def risk(address: str, language: Language = Language.ENGLISH, depth: Depth = Depth.SIMPLE, use_ml: bool = True):
    _history, findings, score_by_id, explanations, overall = _score_and_explain(address, language, depth, use_ml)

    out = []
    for f in findings:
        s = score_by_id[f.finding_id]
        out.append({
            "finding_id": f.finding_id,
            "kind": f.kind,
            "severity": s.severity.value,
            "score": s.total_score,
            "reasons": s.reasons(),
            "suggested_action": f.suggested_action,
            "explanation": explanations[f.finding_id],
            "evidence": [{"label": e.label, "value": e.value} for e in f.evidence],
        })
    return {"address": address, "overall_score": round(overall, 2), "findings": out}


@app.get("/wallet/{address}/report", dependencies=_AUTH)
def wallet_report(address: str, format: str = "markdown",
                   language: Language = Language.ENGLISH, depth: Depth = Depth.DETAILED):
    if format not in ("markdown", "pdf"):
        raise HTTPException(422, "format must be 'markdown' or 'pdf'")

    history, findings, score_by_id, explanations, overall = _score_and_explain(
        address, language, depth, use_ml=True
    )
    sections = [ReportSection(finding=f, scored=score_by_id[f.finding_id], explanation=explanations[f.finding_id])
                for f in findings]
    subtitle = (
        f"Wallet: {history.address}\n"
        f"Data source: {history.data_source}"
        + (f" (blocks {history.scanned_from_block}-{history.scanned_to_block})" if history.data_source == "live" else "")
    )
    footer = (
        "This report reflects only what was found in this wallet's own on-chain approval "
        "history at the time it was generated. It is not financial or legal advice, and a "
        "clean report does not guarantee this wallet is risk-free — only that nothing in "
        "the checks above was flagged."
    )

    if format == "markdown":
        content = render_markdown("Arth Raksha Wallet Safety Report", subtitle, round(overall, 2), sections, footer)
        return Response(
            content=content, media_type="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="arth_raksha_report_{address}.md"'},
        )
    else:
        content = render_pdf("Arth Raksha Wallet Safety Report", subtitle, round(overall, 2), sections, footer)
        return Response(
            content=content, media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="arth_raksha_report_{address}.pdf"'},
        )


@app.post("/address-book", dependencies=_AUTH)
def add_contact(req: ContactRequest):
    book = _address_books.setdefault(req.wallet_address.lower(), AddressBook())
    book.add(Contact(name=req.name, address=req.address, chain=req.chain))
    return {"ok": True, "contacts": [c.name for c in book.all()]}


@app.get("/address-book/{address}", dependencies=_AUTH)
def list_contacts(address: str):
    """Lists this wallet's own saved contacts — the set draft_transaction
    is only ever allowed to resolve a name against. Added specifically so
    the frontend can show a real picker instead of asking the user to
    retype a name/address they already saved."""
    book = _address_books.get(address.lower())
    if book is None:
        return {"contacts": []}
    return {"contacts": [{"name": c.name, "address": c.address, "chain": c.chain} for c in book.all()]}


@app.post("/send/draft", dependencies=_AUTH)
def send_draft(req: DraftRequest):
    book = _address_books.get(req.wallet_address.lower())
    if book is None:
        raise HTTPException(404, "No address book for this wallet — connect it first")
    try:
        draft = draft_transaction(req.request, book)
    except UnknownRecipientError as exc:
        raise HTTPException(400, str(exc))
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    draft_id = str(uuid.uuid4())[:8]
    _drafts[draft_id] = draft

    # Simulation preview happens now, before confirm — the user sees the
    # expected outcome (or a likely-revert warning) before ever signing.
    # Belt-and-suspenders try/except: simulation is a nice-to-have preview
    # and must never be able to sink draft creation itself, even if some
    # future bug in simulate_transaction breaks its own internal handling
    # (as one already did — see transaction.py's fix notes).
    w3 = _live_w3_for(req.wallet_address)
    if w3 is not None:
        try:
            simulate_transaction(w3, req.wallet_address, draft)
        except Exception as exc:
            draft.simulated_outcome = f"Simulation preview unavailable: {exc}"

    return {
        "draft_id": draft_id,
        "recipient_name": draft.recipient_name,
        "recipient_address": draft.recipient_address,
        "amount": draft.amount,
        "token": draft.token,
        "chain": draft.chain,
        "warnings": draft.warnings,
        "simulated_outcome": draft.simulated_outcome,
        "confirmed": draft.confirmed,
    }


@app.post("/send/{draft_id}/confirm", dependencies=_AUTH)
def confirm_draft(draft_id: str):
    draft = _drafts.get(draft_id)
    if draft is None:
        raise HTTPException(404, "Unknown draft")
    draft.confirm()
    # This payload goes to the frontend, which hands it to the user's own
    # connected wallet (MetaMask/WalletConnect) for the user to sign. The
    # backend/AI never sees or holds a private key.
    return draft.to_wallet_provider_payload()


@app.post("/revoke/draft", dependencies=_AUTH)
def revoke_draft(req: RevokeDraftRequest):
    """One bad address in a batch must not sink the rest — each approval
    is drafted (and simulated) independently, with a per-item error
    surfaced instead of failing the whole request. Discovered as a real
    bug: an earlier version called draft_batch_revoke as a single
    all-or-nothing list comprehension, so one malformed checksum address
    in a batch of otherwise-valid revokes returned a bare 500 for all of
    them."""
    w3 = _live_w3_for(req.wallet_address)
    out = []
    for approval in req.approvals:
        try:
            draft = draft_revoke(approval.token_address, approval.spender_address, chain=req.chain)
        except Exception as exc:
            out.append({
                "token_address": approval.token_address,
                "spender_address": approval.spender_address,
                "error": str(exc),
            })
            continue
        if w3 is not None:
            try:
                simulate_revoke(w3, req.wallet_address, draft)
            except Exception as exc:
                draft.simulated_outcome = f"Simulation preview unavailable: {exc}"
        draft_id = str(uuid.uuid4())[:8]
        _revoke_drafts[draft_id] = draft
        out.append({
            "draft_id": draft_id,
            "token_address": draft.token_address,
            "spender_address": draft.spender_address,
            "chain": draft.chain,
            "simulated_outcome": draft.simulated_outcome,
            "confirmed": draft.confirmed,
        })
    return {"drafts": out}


@app.post("/revoke/{draft_id}/confirm", dependencies=_AUTH)
def confirm_revoke(draft_id: str):
    draft = _revoke_drafts.get(draft_id)
    if draft is None:
        raise HTTPException(404, "Unknown revoke draft")
    draft.confirm()
    return draft.to_wallet_provider_payload()
