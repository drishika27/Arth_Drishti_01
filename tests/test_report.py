"""
Tests for the shared exportable report (shared_engine/report.py) and its
wiring into both backends' /report endpoints.
"""
from __future__ import annotations

import io

import pypdf
from fastapi.testclient import TestClient

from shared_engine import Evidence, Finding, ReportSection, Severity, render_markdown, render_pdf
from shared_engine.scoring import ScoredResult, RuleHit
from shared_engine.auth import _DEV_FALLBACK_KEY
from arth_raksha.backend.main import app as raksha_app
from arth_bodh.backend.main import app as bodh_app


def _sample_section(explanation: str, kind: str = "fee") -> ReportSection:
    finding = Finding(
        finding_id="f1", domain="test", kind=kind,
        evidence=[Evidence(label="amount", value=750, source_ref="doc:10-20")],
        suggested_action="Review this charge",
    )
    scored = ScoredResult(finding_id="f1", total_score=3.0, severity=Severity.MEDIUM,
                           hits=[RuleHit("high_fee", 3.0, "Fee is unusually large")])
    return ReportSection(finding=finding, scored=scored, explanation=explanation)


def test_markdown_report_includes_all_real_content():
    section = _sample_section("Fee of 750 flagged as unusually large.")
    md = render_markdown("Test Report", "Subtitle line", 3.0, [section], "Footer disclaimer.")
    assert "Test Report" in md
    assert "Subtitle line" in md
    assert "Fee is unusually large" in md
    assert "Fee of 750 flagged as unusually large." in md
    assert "Review this charge" in md
    assert "amount: 750" in md
    assert "Footer disclaimer." in md


def test_pdf_report_round_trips_english_hindi_and_hinglish_text():
    sections = [
        _sample_section("English: Late Payment Fee of Rs. 750 is unusually large."),
        _sample_section("हिंदी में: देर से भुगतान शुल्क 750 रुपये असामान्य रूप से अधिक है।", kind="hidden_fee"),
        _sample_section("Hinglish: Yeh fee normal se zyada hai, isliye flag kiya gaya.", kind="repeating_charge"),
    ]
    pdf_bytes = render_pdf("Test Report", "Wallet: 0xTest", 9.0, sections, "Footer disclaimer.")
    assert pdf_bytes[:4] == b"%PDF"  # a real PDF, not a stub

    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    text = "\n".join(page.extract_text() for page in reader.pages)
    assert "Late Payment Fee of Rs. 750" in text
    assert "देर से भुगतान शुल्क" in text  # real Devanagari, not boxes/mojibake
    assert "Yeh fee normal se zyada hai" in text
    assert "Footer disclaimer." in text


def test_arth_raksha_report_endpoint_markdown_and_pdf(monkeypatch):
    monkeypatch.delenv("ARTHDRISHTI_API_KEYS", raising=False)
    client = TestClient(raksha_app)
    token = client.post("/auth/token", json={"api_key": _DEV_FALLBACK_KEY}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    client.post("/wallet/connect", json={"address": "0xReportWallet"}, headers=headers)

    md_resp = client.get("/wallet/0xReportWallet/report", headers=headers)
    assert md_resp.status_code == 200
    assert md_resp.headers["content-type"].startswith("text/markdown")
    assert "Arth Raksha Wallet Safety Report" in md_resp.text

    pdf_resp = client.get("/wallet/0xReportWallet/report?format=pdf", headers=headers)
    assert pdf_resp.status_code == 200
    assert pdf_resp.headers["content-type"] == "application/pdf"
    assert pdf_resp.content[:4] == b"%PDF"
    reader = pypdf.PdfReader(io.BytesIO(pdf_resp.content))
    assert "Arth Raksha Wallet Safety Report" in reader.pages[0].extract_text()


def test_arth_bodh_report_endpoint_markdown_and_pdf(monkeypatch):
    monkeypatch.delenv("ARTHDRISHTI_API_KEYS", raising=False)
    client = TestClient(bodh_app)
    token = client.post("/auth/token", json={"api_key": _DEV_FALLBACK_KEY}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    doc_id = client.post(
        "/parse", json={"text": "Late Payment Fee of Rs. 750 charged on 12 Jan."}, headers=headers
    ).json()["doc_id"]

    md_resp = client.get(f"/doc/{doc_id}/report", headers=headers)
    assert md_resp.status_code == 200
    assert "Arth Bodh Statement Report" in md_resp.text

    pdf_resp = client.get(f"/doc/{doc_id}/report?format=pdf", headers=headers)
    assert pdf_resp.status_code == 200
    assert pdf_resp.content[:4] == b"%PDF"


def test_report_rejects_unknown_format(monkeypatch):
    monkeypatch.delenv("ARTHDRISHTI_API_KEYS", raising=False)
    client = TestClient(raksha_app)
    token = client.post("/auth/token", json={"api_key": _DEV_FALLBACK_KEY}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    client.post("/wallet/connect", json={"address": "0xReportWallet2"}, headers=headers)
    resp = client.get("/wallet/0xReportWallet2/report?format=xml", headers=headers)
    assert resp.status_code == 422
