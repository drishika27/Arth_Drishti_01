"""
Arth Bodh backend — FastAPI app.

Endpoints:
  POST /auth/token -> trade an API key for a 1-hour bearer token
  POST /parse    -> upload/paste statement text, get back grounded findings [auth]
  POST /explain  -> explain a specific finding in a chosen language/depth   [auth]
  POST /chat     -> ask a follow-up question, grounded in the parsed document [auth]
  GET  /doc/{doc_id}/report -> export the parsed findings as Markdown/PDF   [auth]
  GET  /health

[auth] endpoints require `Authorization: Bearer <token>` — see
shared_engine/auth.py. Full interactive docs at /docs once running.

Run:
  uvicorn arth_bodh.backend.main:app --reload --port 8001
"""
from __future__ import annotations

import os
import sys
import uuid
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

from contextlib import asynccontextmanager

from shared_engine import (
    ScoringEngine, GroundedExplainer, Language, Depth, issue_token, require_auth,
    ReportSection, render_markdown, render_pdf,
)
from arth_core import config as core_config
from arth_core.db import init_db
from arth_core.api import (
    auth as account_api, expenses as expenses_api, receipts as receipts_api, insights as insights_api,
    demo as demo_api, crypto as crypto_api, bank as bank_api,
)
from arth_core.bank import sync as bank_sync_service
from arth_core import crypto as crypto_service
from .parser import parse_statement_text, ParsedDocument
from .rules import ALL_RULES


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()   # creates any missing tables (SQLite locally, Postgres on Render)
    import threading
    threading.Thread(target=crypto_service.warm, daemon=True).start()   # pre-load token lists in the background
    import asyncio
    sync_task = asyncio.create_task(bank_sync_service.sync_loop())      # automatic bank transaction sync
    try:
        yield
    finally:
        sync_task.cancel()


app = FastAPI(
    title="Arth Bodh API",
    version="0.3.0",
    lifespan=lifespan,
    description=(
        "ArthDrishti application API: accounts, expenses (manual + receipt OCR + "
        "bank sync), crypto portfolio and AI insights, plus the original grounded "
        "statement explainer. Sign in via POST /auth/login (or /auth/register); "
        "POST /auth/token remains for API-key clients."
    ),
)
app.add_middleware(
    CORSMiddleware, allow_origins=core_config.cors_origins(),
    allow_methods=["*"], allow_headers=["*"],
)
app.include_router(account_api.router)
app.include_router(expenses_api.router)
app.include_router(receipts_api.router)
app.include_router(insights_api.router)
app.include_router(demo_api.router)
app.include_router(crypto_api.router)
app.include_router(bank_api.router)

_AUTH = [Depends(require_auth)]

_engine = ScoringEngine("arth_bodh")
for r in ALL_RULES:
    _engine.register(r)
_explainer = GroundedExplainer()

# in-memory session store: {doc_id: ParsedDocument}. A real deployment would
# use a DB; kept in-memory here so the app runs with zero infra.
_DOCS: dict[str, ParsedDocument] = {}


class TokenRequest(BaseModel):
    api_key: str = Field(..., description="Server-configured API key (see ARTHDRISHTI_API_KEYS).")


class ParseRequest(BaseModel):
    text: str
    language: Language = Language.ENGLISH


class ExplainRequest(BaseModel):
    doc_id: str
    finding_id: str
    language: Language = Language.ENGLISH
    depth: Depth = Depth.SIMPLE


class ChatRequest(BaseModel):
    doc_id: str
    question: str
    language: Language = Language.ENGLISH


@app.get("/health", summary="Liveness check — no auth required")
def health():
    return {"status": "ok", "model_configured": bool(os.environ.get("ANTHROPIC_API_KEY"))}


@app.post("/auth/token", summary="Trade an API key for a 1-hour bearer token")
def get_token(req: TokenRequest):
    try:
        return issue_token(req.api_key)
    except PermissionError as exc:
        raise HTTPException(401, str(exc))


@app.post("/parse", dependencies=_AUTH)
def parse(req: ParseRequest):
    doc_id = str(uuid.uuid4())[:8]
    parsed = parse_statement_text(req.text, doc_id=doc_id)
    _DOCS[doc_id] = parsed
    scored = _engine.score_all(parsed.findings)
    score_by_id = {s.finding_id: s for s in scored}

    out = []
    for f in parsed.findings:
        s = score_by_id[f.finding_id]
        out.append({
            "finding_id": f.finding_id,
            "kind": f.kind,
            "severity": s.severity.value,
            "score": s.total_score,
            "reasons": s.reasons(),
            "evidence": [{"label": e.label, "value": e.value, "source_ref": e.source_ref} for e in f.evidence],
        })
    return {"doc_id": doc_id, "finding_count": len(out), "findings": out}


@app.post("/explain", dependencies=_AUTH)
def explain(req: ExplainRequest):
    doc = _DOCS.get(req.doc_id)
    if doc is None:
        raise HTTPException(404, "Unknown doc_id — call /parse first")
    finding = next((f for f in doc.findings if f.finding_id == req.finding_id), None)
    if finding is None:
        raise HTTPException(404, "Unknown finding_id for this document")
    expl = _explainer.explain(finding, language=req.language, depth=req.depth)
    return {
        "finding_id": expl.finding_id,
        "text": expl.text,
        "grounded": expl.grounded,
        "citations": expl.citations,
    }


@app.post("/chat", dependencies=_AUTH)
def chat(req: ChatRequest):
    doc = _DOCS.get(req.doc_id)
    if doc is None:
        raise HTTPException(404, "Unknown doc_id — call /parse first")
    # Grounded chat: only ever answer from this document's own findings.
    # No general knowledge, no invented figures — if nothing in the parsed
    # findings is relevant, say so honestly.
    relevant = [f for f in doc.findings if any(
        w in f.kind or any(w in str(e.value).lower() for e in f.evidence)
        for w in req.question.lower().split()
    )]
    if not relevant:
        return {"answer": "I couldn't find anything in your statement related to that question, "
                           "so I won't guess. Try asking about a specific fee or charge you saw flagged."}
    answers = []
    for f in relevant[:3]:
        expl = _explainer.explain(f, language=req.language, depth=Depth.DETAILED)
        answers.append(expl.text)
    return {"answer": " ".join(answers)}




# NOTE: the earlier canned /ocr, /ai/chat, /dashboard, /wallet, /portfolio and
# /security endpoints were replaced by real, per-user implementations in
# arth_core (receipts, insights, expenses/summary).

@app.get("/doc/{doc_id}/report", dependencies=_AUTH)
def doc_report(doc_id: str, format: str = "markdown", language: Language = Language.ENGLISH):
    if format not in ("markdown", "pdf"):
        raise HTTPException(422, "format must be 'markdown' or 'pdf'")
    doc = _DOCS.get(doc_id)
    if doc is None:
        raise HTTPException(404, "Unknown doc_id — call /parse first")

    scored = _engine.score_all(doc.findings)
    score_by_id = {s.finding_id: s for s in scored}
    sections = [
        ReportSection(
            finding=f, scored=score_by_id[f.finding_id],
            explanation=_explainer.explain(f, language=language, depth=Depth.DETAILED).text,
        )
        for f in doc.findings
    ]
    overall = round(sum(s.total_score for s in scored), 2)
    footer = (
        "This report reflects only what was found in the statement text you provided. "
        "It is not financial or legal advice."
    )

    if format == "markdown":
        content = render_markdown("Arth Bodh Statement Report", f"Document: {doc_id}", overall, sections, footer)
        return Response(
            content=content, media_type="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="arth_bodh_report_{doc_id}.md"'},
        )
    else:
        content = render_pdf("Arth Bodh Statement Report", f"Document: {doc_id}", overall, sections, footer)
        return Response(
            content=content, media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="arth_bodh_report_{doc_id}.pdf"'},
        )
