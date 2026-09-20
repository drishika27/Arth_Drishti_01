"""AI insights + chat, grounded in the signed-in user's own transactions."""
from __future__ import annotations

import json
import os

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import config
from ..db import get_db
from ..deps import get_current_user
from ..insights import answer_question, compute_insights
from ..models import User

router = APIRouter(tags=["insights"])

_SYSTEM = ("You are Arth AI, a personal-finance assistant. Answer ONLY from the JSON facts provided. "
           "Never invent amounts, merchants, dates or trends. If the facts don't cover the question, "
           "say so plainly. Be concise (2-4 sentences) and use ₹ for amounts.")


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)


@router.get("/insights")
def insights(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return compute_insights(db, user)


@router.post("/ai/chat")
def ai_chat(req: ChatRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    facts = compute_insights(db, user)
    fallback = answer_question(req.question, facts)
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key or facts["transaction_count"] == 0:
        return {"answer": fallback, "grounded_in": "your saved transactions", "engine": "rules"}
    try:
        import anthropic
        resp = anthropic.Anthropic(api_key=key, timeout=30).messages.create(
            model=config.anthropic_model(), max_tokens=350, system=_SYSTEM,
            messages=[{"role": "user", "content": f"Facts:\n{json.dumps(facts, default=str)}\n\nQuestion: {req.question}"}])
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
        if text:
            return {"answer": text, "grounded_in": "your saved transactions", "engine": "claude"}
    except Exception:
        pass    # fall through: deterministic answer, never an error the user can't act on
    return {"answer": fallback, "grounded_in": "your saved transactions", "engine": "rules"}
