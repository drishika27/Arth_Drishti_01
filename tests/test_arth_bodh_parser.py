from arth_bodh.backend.parser import parse_statement_text

SAMPLE = """
Your statement shows a Late Payment Fee of Rs. 750 charged on 12 Jan.
Foreign Transaction Fee: Rs. 200. Foreign Transaction Fee: Rs. 200.
Foreign Transaction Fee: Rs. 200. Credit utilization is currently 82%.
"""

def test_parser_finds_fee_terms_with_evidence():
    parsed = parse_statement_text(SAMPLE, doc_id="doc1")
    kinds = [f.kind for f in parsed.findings]
    assert "fee" in kinds or "hidden_fee" in kinds
    for f in parsed.findings:
        assert f.has_evidence()

def test_parser_detects_repeating_charge():
    parsed = parse_statement_text(SAMPLE, doc_id="doc1")
    assert any(f.kind == "repeating_charge" for f in parsed.findings)

def test_parser_detects_high_utilization():
    parsed = parse_statement_text(SAMPLE, doc_id="doc1")
    util = [f for f in parsed.findings if f.kind == "credit_utilization"]
    assert util
    assert util[0].evidence[0].value == 82.0
