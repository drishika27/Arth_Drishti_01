"""Receipt OCR: parser correctness on realistic receipt text, a REAL image
run through the local OCR engine, and the scan -> confirm API flow."""
import io
from datetime import date

import pytest

from arth_core import ocr

CCD = """CAFE COFFEE DAY
Koramangala, Bengaluru
GSTIN: 29ABCDE1234F1Z5
Bill Date: 19/09/2026  Time 18:42
Cappuccino x2      320.00
Sandwich           180.00
Sub Total          500.00
CGST @2.5%          12.50
SGST @2.5%          12.50
Grand Total        525.00
Thank you, visit again
"""


def test_parser_extracts_all_fields_from_typical_receipt():
    r = ocr.parse_receipt_text(CCD)
    assert r.merchant == "Cafe Coffee Day"
    assert r.amount == 525.0                      # grand total, not subtotal / not the GSTIN digits
    assert r.tax == 25.0                          # CGST + SGST, percentages ignored
    assert r.date == date(2026, 9, 19)
    assert r.category == "Food"
    assert r.warnings == [] and r.confidence == "high"


def test_parser_handles_indian_number_format_and_totals_on_next_line():
    r = ocr.parse_receipt_text("Reliance Digital\n12-Aug-2025\nTotal Amount\nRs. 1,24,999.00\n")
    assert r.amount == 124999.0 and r.date == date(2025, 8, 12)


def test_parser_pasted_one_liner():
    r = ocr.parse_receipt_text("Cafe Coffee Day ₹540 19 Sep")
    assert r.merchant == "Cafe Coffee Day" and r.amount == 540.0 and r.category == "Food"
    assert r.date is not None and (r.date.month, r.date.day) == (9, 19)


def test_parser_never_invents_missing_fields():
    r = ocr.parse_receipt_text("just some words with no numbers")
    assert r.amount is None and r.date is None
    assert any("total amount" in w for w in r.warnings) and any("date" in w for w in r.warnings)


def test_tax_that_exceeds_total_is_discarded():
    r = ocr.parse_receipt_text("Shop\nGST 900.00\nTotal 100.00")
    assert r.amount == 100.0 and r.tax is None


def test_scan_rejects_bad_input_with_actionable_errors():
    with pytest.raises(ocr.OcrError) as e:
        ocr.scan(data=b"not an image at all")
    assert e.value.status_code == 415
    with pytest.raises(ocr.OcrError) as e:
        ocr.scan(data=b"x" * (ocr.MAX_UPLOAD_BYTES + 1))
    assert e.value.status_code == 413
    with pytest.raises(ocr.OcrError):
        ocr.scan()


def _receipt_png() -> bytes:
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (900, 620), "white")
    d = ImageDraw.Draw(img)
    f = ImageFont.load_default(size=34)
    lines = ["BIGBASKET", "Date: 12/09/2026", "Milk 2L            120.00", "Rice 5kg           450.00",
             "GST 5%              28.50", "Total Amount       598.50"]
    for i, ln in enumerate(lines):
        d.text((40, 30 + i * 90), ln, fill="black", font=f)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def test_real_image_through_local_ocr_engine():
    pytest.importorskip("rapidocr_onnxruntime")
    r = ocr.scan(data=_receipt_png(), engine="local")
    assert r.engine == "local"
    assert r.merchant and "bigbasket" in r.merchant.lower()
    assert r.amount == 598.5
    assert r.date == date(2026, 9, 12)


def test_scan_confirm_flow_creates_ocr_expense_once(client, auth, auth2):
    r = client.post("/receipts/scan", data={"text": CCD}, headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert body["extracted"]["amount"] == 525.0 and body["engine"] == "text"

    edited = {**{k: body["extracted"][k] for k in ("merchant", "amount", "tax", "category", "date")}, "amount": 530.0}
    # another user can't confirm my receipt
    assert client.post(f"/receipts/{body['receipt_id']}/confirm", json=edited, headers=auth2).status_code == 404
    ok = client.post(f"/receipts/{body['receipt_id']}/confirm", json=edited, headers=auth)
    assert ok.status_code == 201 and ok.json()["source"] == "ocr" and ok.json()["amount"] == 530.0
    assert client.post(f"/receipts/{body['receipt_id']}/confirm", json=edited, headers=auth).status_code == 409
    items = client.get("/expenses", headers=auth).json()["items"]
    assert len(items) == 1 and items[0]["tax"] == 25.0


def test_scan_api_reports_failures_as_retryable_json(client, auth):
    r = client.post("/receipts/scan", files={"file": ("x.jpg", b"garbage", "image/jpeg")}, headers=auth)
    assert r.status_code == 415
    assert r.json()["detail"]["message"] and r.json()["detail"]["retryable"] is False
    assert client.post("/receipts/scan", headers=auth).status_code == 422
