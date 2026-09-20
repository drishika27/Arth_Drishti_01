"""AI insights + chat, grounded in the signed-in user's own transactions, accounts and wallet."""
from __future__ import annotations

import json
import os
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import assistant, config
from ..db import get_db
from ..deps import get_current_user
from ..insights import compute_insights
from ..models import User

router = APIRouter(tags=["insights"])

_SYSTEM = ("You are Arth AI, a friendly personal-finance assistant inside the ArthDrishti app. Answer ONLY from the JSON "
           "facts and the computed answer provided. Never invent amounts, merchants, dates, prices or trends; if the facts "
           "don't cover the question, say so plainly and suggest what the user can add or connect. Keep numbers exactly as "
           "given (₹ amounts). Be concise and conversational (short paragraph or a few bullet lines). "
           "Reply in the language requested. This is information, not financial advice.")


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    context: Optional[dict] = None          # returned by the previous answer, enables follow-ups


@router.get("/insights")
def insights(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return compute_insights(db, user)


@router.post("/ai/chat")
def ai_chat(req: ChatRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    result = assistant.respond(db, user, req.question, req.context)
    base = {"grounded_in": "your saved transactions, accounts and wallet", "intent": result["intent"], "context": result["context"]}
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return {**base, "answer": result["answer"], "engine": "rules"}
    try:
        import anthropic
        facts = assistant.llm_facts(db, user)
        lang = "Hindi" if user.language == "हिंदी" else "English"
        resp = anthropic.Anthropic(api_key=key, timeout=30).messages.create(
            model=config.anthropic_model(), max_tokens=500, system=_SYSTEM,
            messages=[{"role": "user", "content": (
                f"Language: {lang}\nFacts:\n{json.dumps(facts, default=str)}\n\n"
                f"Computed answer (verified from the user's data):\n{result['answer']}\n\nUser question: {req.question}")}])
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
        if text:
            return {**base, "answer": text, "engine": "claude"}
    except Exception:
        pass    # fall through to the verified rule-based answer — never an error the user can't act on
    return {**base, "answer": result["answer"], "engine": "rules"}
