"""Statement import: real bank statements (CSV / Excel / PDF) -> transactions, then preview + import."""
import io
from datetime import date, timedelta

import pytest

from arth_core import statements


def _d(days_ago: int, fmt="%d/%m/%y") -> str:
    return (date.today() - timedelta(days=days_ago)).strftime(fmt)


def hdfc_csv() -> bytes:
    return (
        "HDFC BANK LIMITED\nStatement of account for A/C 50100xxxx\n\n"
        "Date,Narration,Chq./Ref.No.,Value Dt,Withdrawal Amt.,Deposit Amt.,Closing Balance\n"
        f"{_d(5)},UPI-SWIGGY-swiggy@icici-4581923-Dinner,0000458,{_d(5)},420.00,,84580.00\n"
        f"{_d(4)},NEFT CR-ACME PVT LTD-SALARY,000123,{_d(4)},,97000.00,181580.00\n"
        f"{_d(3)},POS 4421 AMAZON PAY INDIA,000777,{_d(3)},\"1,890.50\",,179689.50\n"
        f"{_d(2)},UPI-UBER INDIA-uber@hdfc-99123-Trip,000778,{_d(2)},280.00,,179409.50\n"
        "Closing balance,,,,,,179409.50\n"
    ).encode()


def test_hdfc_style_csv_with_separate_debit_credit_columns():
    r = statements.parse_statement(hdfc_csv(), "hdfc_stmt.csv")
    assert r.bank_hint == "HDFC Bank" and len(r.txns) == 4
    by_desc = {t.description.split("-")[1] if "-" in t.description else t.description: t for t in r.txns}
    swiggy = next(t for t in r.txns if "SWIGGY" in t.description)
    salary = next(t for t in r.txns if "SALARY" in t.description)
    amazon = next(t for t in r.txns if "AMAZON" in t.description)
    assert swiggy.amount == -420.0 and salary.amount == 97000.0 and amazon.amount == -1890.5   # commas + sign handled
    assert r.closing_balance == 179409.50 and r.skipped_rows >= 1                              # footer row skipped, not imported
    assert len({t.external_id for t in r.txns}) == 4


def test_icici_style_headers_and_single_amount_with_drcr():
    icici = ("Transaction Date,Transaction Remarks,Withdrawal Amount (INR),Deposit Amount (INR),Balance (INR)\n"
             f"{_d(3, '%d-%m-%Y')},IMPS/ZOMATO/1234,350.00,,10000.00\n").encode()
    assert statements.parse_statement(icici).txns[0].amount == -350.0
    drcr = ("Date;Description;Amount;Type;Balance\n"
            f"{_d(3, '%d %b %Y')};Salary ACME;50,000.00;CR;60000.00\n"
            f"{_d(2, '%d %b %Y')};ATM WDL;2,000.00;DR;58000.00\n").encode()
    t = statements.parse_statement(drcr).txns
    assert [x.amount for x in t] == [50000.0, -2000.0]


def test_xlsx_statement():
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(["Account Statement"])
    ws.append(["Txn Date", "Description", "Debit", "Credit", "Balance"])
    ws.append([date.today() - timedelta(days=2), "UPI/BLINKIT/778/Grocery", 640.0, None, 5000.0])
    ws.append([date.today() - timedelta(days=1), "Interest paid", None, 12.5, 5012.5])
    buf = io.BytesIO()
    wb.save(buf)
    t = statements.parse_statement(buf.getvalue(), "s.xlsx").txns
    assert [x.amount for x in t] == [-640.0, 12.5]


def _pdf(lines: list[str]) -> bytes:
    from fpdf import FPDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=9)
    for ln in lines:
        pdf.cell(0, 5, ln, new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


def statement_pdf() -> bytes:
    return _pdf([
        "HDFC BANK - Statement of Account", "Date Narration Chq/Ref Value Dt Withdrawal Deposit Balance",
        f"{_d(5)} UPI-SWIGGY-swiggy@icici-4581923 0000458 {_d(5)} 420.00 84,580.00",
        f"{_d(4)} NEFT CR-ACME PVT LTD-SALARY 000123 {_d(4)} 97,000.00 1,81,580.00",
        f"{_d(3)} POS AMAZON PAY INDIA 000777 {_d(3)} 1,890.50 1,79,689.50",
        "Page 1 of 1",
    ])


def test_pdf_direction_comes_from_the_running_balance():
    r = statements.parse_statement(statement_pdf(), "stmt.pdf")
    assert [t.amount for t in r.txns] == [-420.0, 97000.0, -1890.5]      # credit vs debit inferred from balance change
    assert r.bank_hint == "HDFC Bank"


def test_password_protected_pdf():
    from pypdf import PdfReader, PdfWriter
    w = PdfWriter()
    for p in PdfReader(io.BytesIO(statement_pdf())).pages:
        w.add_page(p)
    w.encrypt("s3cret")
    buf = io.BytesIO()
    w.write(buf)
    locked = buf.getvalue()
    with pytest.raises(statements.StatementError) as e:
        statements.parse_statement(locked)
    assert e.value.code == "password_required"
    with pytest.raises(statements.StatementError) as e:
        statements.parse_statement(locked, password="nope")
    assert e.value.code == "password_wrong"
    assert len(statements.parse_statement(locked, password="s3cret").txns) == 3


def test_bad_input_is_rejected_with_useful_messages():
    with pytest.raises(statements.StatementError) as e:
        statements.parse_statement(b"hello, this is not a statement\nat all")
    assert e.value.code == "no_table"
    with pytest.raises(statements.StatementError) as e:
        statements.parse_statement(b"x" * (statements.MAX_BYTES + 1))
    assert e.value.status_code == 413
    with pytest.raises(statements.StatementError):
        statements.parse_statement(b"")
    with pytest.raises(statements.StatementError) as e:
        statements.parse_statement(_pdf(["nothing useful here"]))
    assert e.value.code == "no_transactions"


def test_same_day_identical_transactions_get_distinct_ids():
    csv = (f"Date,Narration,Debit,Credit,Balance\n{_d(2)},UBER TRIP,100.00,,900.00\n{_d(2)},UBER TRIP,100.00,,900.00\n").encode()
    ids = [t.external_id for t in statements.parse_statement(csv).txns]
    assert len(ids) == 2 and ids[0] != ids[1]


# ---- through the API -----------------------------------------------------------
def _upload(client, auth, data=None, name="stmt.csv", **form):
    return client.post("/bank/statements/parse", files={"file": (name, data or hdfc_csv(), "text/csv")}, data=form, headers=auth)


def _import(client, auth, preview, label="HDFC Savings", **over):
    body = {"account_label": label, "bank_name": preview.get("bank_hint") or "", "closing_balance": preview["closing_balance"],
            "items": [{k: t[k] for k in ("external_id", "date", "description", "merchant", "amount", "kind", "category")}
                      for t in preview["transactions"] if not t["duplicate"]]}
    body.update(over)
    return client.post("/bank/statements/import", json=body, headers=auth)


def test_statement_preview_then_import_end_to_end(client, auth):
    r = _upload(client, auth)
    assert r.status_code == 200
    p = r.json()
    assert p["count"] == 4 and p["new_count"] == 4 and p["duplicate_count"] == 0 and p["bank_hint"] == "HDFC Bank"
    cats = {t["merchant"]: t["category"] for t in p["transactions"]}
    assert cats["Swiggy"] == "Food" and cats["Amazon"] == "Shopping" and cats["Uber"] == "Travel"
    assert cats["Acme Pvt Ltd"] == "Income"                                   # salary shows the employer, not "Cr"
    assert client.get("/expenses", headers=auth).json()["total"] == 0            # preview saves nothing

    imp = _import(client, auth, p)
    assert imp.status_code == 201 and imp.json()["imported"] == 4
    items = client.get("/expenses?kind=all&limit=50", headers=auth).json()["items"]
    assert len(items) == 4 and {i["source"] for i in items} == {"bank"}
    assert any(i["kind"] == "income" and i["amount"] == 97000.0 for i in items)
    accts = client.get("/bank/accounts", headers=auth).json()
    assert accts["accounts"][0]["data_mode"] == "statement" and accts["accounts"][0]["balance"] == 179409.5

    # importing the same statement again adds nothing
    again = _upload(client, auth).json()
    assert again["duplicate_count"] == 4 and again["new_count"] == 0
    assert _import(client, auth, p).json() == {"imported": 0, "duplicates_skipped": 4, "account": imp.json()["account"]}
    assert client.get("/expenses?kind=all", headers=auth).json()["total"] == 4


def test_imported_transactions_can_be_edited_and_the_correction_is_learned(client, auth):
    _import(client, auth, _upload(client, auth).json())
    swiggy = next(i for i in client.get("/expenses", headers=auth).json()["items"] if i["merchant"] == "Swiggy")
    assert swiggy["source"] == "bank" and swiggy["raw_description"].startswith("UPI-SWIGGY")
    r = client.patch(f"/expenses/{swiggy['id']}", json={"category": "Groceries", "note": "family order"}, headers=auth)
    assert r.json()["category"] == "Groceries" and r.json()["source"] == "bank" and r.json()["user_edited"] is True
    new = client.post("/expenses", json={"merchant": "Swiggy", "amount": 99, "date": date.today().isoformat()}, headers=auth).json()
    assert new["category"] == "Groceries"


def test_statement_endpoints_validate_and_isolate(client, auth, auth2):
    bad = _upload(client, auth, data=b"not a statement", name="x.csv")
    assert bad.status_code == 422 and bad.json()["detail"]["message"]
    p = _upload(client, auth).json()
    assert _import(client, auth, p, items=[{**{k: p["transactions"][0][k] for k in ("external_id", "date", "description", "merchant", "amount", "kind")}, "category": "Nope"}]).status_code == 422
    _import(client, auth, p)
    assert client.get("/expenses?kind=all", headers=auth2).json()["total"] == 0
    assert client.get("/bank/accounts", headers=auth2).json()["accounts"] == []
    assert _upload(client, auth2).json()["duplicate_count"] == 0            # A's imports don't mark B's preview as duplicates
    assert client.post("/bank/statements/parse", files={"file": ("a.csv", hdfc_csv())}).status_code in (401, 403)
