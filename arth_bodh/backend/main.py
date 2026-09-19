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

from shared_engine import (
    ScoringEngine, GroundedExplainer, Language, Depth, issue_token, require_auth,
    ReportSection, render_markdown, render_pdf,
)
from .parser import parse_statement_text, ParsedDocument
from .rules import ALL_RULES

app = FastAPI(
    title="Arth Bodh API",
    version="0.2.0",
    description=(
        "Explains a bank statement's fees and terms in plain language, grounded "
        "only in the document's own evidence. Most endpoints require a bearer "
        "token — call POST /auth/token first."
    ),
)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

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




class SimpleChatRequest(BaseModel):
    question: str

class OCRRequest(BaseModel):
    text: str = ""

@app.post("/ai/chat", dependencies=_AUTH)
def ai_chat(req: SimpleChatRequest):
    q = req.question.lower()
    if "largest" in q or "category" in q:
        return {"answer": "From the demo expense data, Food and Groceries are among the largest recurring categories. You can open Analytics to inspect the exact local breakdown."}
    if "cash" in q or "flow" in q:
        return {"answer": "Your demo snapshot shows ₹97,000 income, ₹8,200 of recent tracked expenses, and ₹38,200 remaining planned budget. These are demo values until a bank connection is configured."}
    if "spend" in q or "expense" in q:
        return {"answer": "I can help review expenses, compare categories, and explain individual charges. For this demo, your recent activity is stored locally in the interface."}
    return {"answer": "I can help with spending, budgets, cash flow, receipt review, and the Arth Raksha wallet demo. Ask me about one of those areas and I’ll keep the answer grounded in the available demo data."}

@app.post("/ocr", dependencies=_AUTH)
def ocr(req: OCRRequest):
    text = req.text.lower()
    amount = 540
    import re
    m = re.search(r"(?:₹|rs\.?\s*)?([0-9]{2,6}(?:\.[0-9]{1,2})?)", text)
    if m:
        amount = float(m.group(1))
    merchant = "Cafe Coffee Day" if "cafe" in text or "coffee" in text else "Receipt merchant (review)"
    category = "Food" if merchant != "Receipt merchant (review)" else "Other"
    return {"merchant": merchant, "amount": amount, "date": "2026-09-19", "category": category, "note": "Mock OCR result — please review before saving."}

@app.get("/dashboard", dependencies=_AUTH)
def dashboard():
    return {"available_funds": 84200, "monthly_income": 97000, "monthly_spend": 8200, "crypto_portfolio": 682940, "security": "Protected", "data_mode": "demo"}

@app.get("/wallet", dependencies=_AUTH)
def wallet():
    return {"address": "0x8c21...77E2", "network": "Ethereum Mainnet", "watch_only": True, "data_mode": "mock-blockchain"}

@app.get("/portfolio", dependencies=_AUTH)
def portfolio():
    return {"currency": "INR", "value": 682940, "change_24h": 4.2, "assets": [{"symbol":"ETH","amount":1.82,"price":291450},{"symbol":"USDC","amount":820,"price":83.5},{"symbol":"USDT","amount":510,"price":83.6}], "data_mode":"mock-blockchain"}

@app.get("/security", dependencies=_AUTH)
def security():
    return {"risk":"Low", "approvals":3, "address_checks":"8 / 8", "seed_phrase_requested":False, "private_key_requested":False, "data_mode":"demo"}

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
