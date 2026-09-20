"""Receipt OCR endpoints: scan (extract) -> user reviews/edits -> confirm (saves
as an expense in the same system as manual + bank entries)."""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from .. import ocr
from ..categorizer import CATEGORIES
from ..db import get_db
from ..deps import get_current_user
from ..models import Expense, Receipt, User
from .expenses import MAX_AMOUNT, _check_category, _check_date, expense_out

router = APIRouter(prefix="/receipts", tags=["receipts"])


class ConfirmRequest(BaseModel):
    merchant: str = Field(min_length=1, max_length=200)
    amount: float = Field(gt=0, lt=MAX_AMOUNT)
    tax: Optional[float] = Field(default=None, ge=0, lt=MAX_AMOUNT)
    category: str
    date: date
    note: str = Field(default="", max_length=500)

    @field_validator("category")
    @classmethod
    def _cat(cls, v):
        return _check_category(v)

    @field_validator("date")
    @classmethod
    def _d(cls, v):
        return _check_date(v)


@router.post("/scan")
async def scan_receipt(
    file: Optional[UploadFile] = File(None),
    text: Optional[str] = Form(None),
    engine: Literal["auto", "claude", "local"] = Form("auto"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    data = None
    filename = mime = ""
    if file is not None:
        filename = (file.filename or "")[:255]
        data = await file.read(ocr.MAX_UPLOAD_BYTES + 1)   # bounded read: never buffer an unbounded upload
    try:
        result = await _run_in_thread(data, text, engine)
    except ocr.OcrError as exc:
        db.add(Receipt(user_id=user.id, filename=filename, status="failed", error=exc.message))
        db.commit()
        raise HTTPException(exc.status_code, detail={"message": exc.message, "retryable": exc.retryable})

    if data:
        mime = ocr.sniff_type(data) or ""
    rec = Receipt(user_id=user.id, filename=filename, mime=mime, engine=result.engine,
                  status="done", raw_text=result.raw_text[:20000],
                  extracted_json=json.dumps(result.fields()))
    db.add(rec)
    db.commit()
    return {
        "receipt_id": rec.id, "engine": result.engine, "confidence": result.confidence,
        "extracted": result.fields(), "raw_text": result.raw_text, "warnings": result.warnings,
    }


async def _run_in_thread(data, text, engine):
    # OCR is CPU-heavy; keep it off the event loop so other requests stay responsive.
    from starlette.concurrency import run_in_threadpool
    return await run_in_threadpool(ocr.scan, data, text, engine)


@router.post("/{receipt_id}/confirm", status_code=201)
def confirm_receipt(receipt_id: str, req: ConfirmRequest,
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rec = db.get(Receipt, receipt_id)
    if rec is None or rec.user_id != user.id or rec.status != "done":
        raise HTTPException(404, "Receipt not found.")
    if rec.expense_id:
        raise HTTPException(409, "This receipt was already saved as an expense.")
    e = Expense(
        user_id=user.id, source="ocr", kind="expense", merchant=req.merchant.strip(),
        amount=Decimal(str(req.amount)), tax=Decimal(str(req.tax)) if req.tax is not None else None,
        currency=user.currency, category=req.category, category_source="user",
        date=req.date, note=req.note.strip(), receipt_id=rec.id, user_edited=True,
    )
    db.add(e)
    db.flush()
    rec.expense_id = e.id
    db.commit()
    return expense_out(e)
