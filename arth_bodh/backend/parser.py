"""
Document parsing + confusing-term detection for Arth Bodh.

Step 1 (Parse) and Step 2 (Detect) from the brief: the AI model reads the
document directly (no separate OCR tool). This module builds Findings from
whatever raw text was extracted — either by the LLM (if configured) or, for
offline/testing, from a lightweight local heuristic pass so the pipeline is
runnable without any external key.
"""
from __future__ import annotations
import os
import re
from dataclasses import dataclass

from shared_engine import Finding, Evidence

FEE_TERMS = {
    "late payment fee": "Charged when a bill isn't paid by its due date.",
    "annual percentage rate": "The yearly cost of borrowing, including interest and fees.",
    "minimum finance charge": "A flat fee charged even if your interest calculation is very small.",
    "over-limit fee": "Charged when spending goes past your credit limit.",
    "foreign transaction fee": "Extra charge for purchases made in another currency.",
    "cash advance fee": "Charged for withdrawing cash against a credit line.",
}

AMOUNT_RE = re.compile(r"(?:₹|Rs\.?|INR)\s?([\d,]+(?:\.\d{1,2})?)")


@dataclass
class ParsedDocument:
    raw_text: str
    findings: list[Finding]


def _to_amount(s: str) -> float:
    return float(s.replace(",", ""))


def parse_statement_text(raw_text: str, doc_id: str = "doc") -> ParsedDocument:
    """Heuristic, evidence-producing parse. Every Finding below carries a
    source_ref pointing at the character offset it came from, so nothing here
    is a guess disconnected from the actual document."""
    findings: list[Finding] = []
    lower = raw_text.lower()

    # Detect known fee/confusing terms with surrounding context + nearby amount
    for term, definition in FEE_TERMS.items():
        for m in re.finditer(re.escape(term), lower):
            start, end = m.start(), m.end()
            window = raw_text[max(0, start - 60): end + 60]
            amt_match = AMOUNT_RE.search(window)
            evidence = [
                Evidence(label="term", value=raw_text[start:end], source_ref=f"{doc_id}:{start}-{end}"),
                Evidence(label="definition", value=definition, source_ref="glossary"),
            ]
            if amt_match:
                evidence.append(Evidence(
                    label="amount", value=_to_amount(amt_match.group(1)),
                    source_ref=f"{doc_id}:{start}-{end}", raw_context=window.strip(),
                ))
                kind = "fee"
            else:
                kind = "hidden_fee"
            findings.append(Finding(
                finding_id=f"{doc_id}-term-{start}",
                domain="arth_bodh",
                kind=kind,
                evidence=evidence,
                reasons=["matched known fee/charge terminology"],
            ))

    # Detect repeating charge amounts (same amount appears 3+ times)
    amounts = [(m.start(), _to_amount(m.group(1))) for m in AMOUNT_RE.finditer(raw_text)]
    from collections import Counter
    counts = Counter(v for _, v in amounts)
    for value, occ in counts.items():
        if occ >= 3:
            offsets = [str(pos) for pos, v in amounts if v == value]
            findings.append(Finding(
                finding_id=f"{doc_id}-repeat-{value}",
                domain="arth_bodh",
                kind="repeating_charge",
                evidence=[
                    Evidence(label="amount", value=value, source_ref=f"{doc_id}:{','.join(offsets)}"),
                    Evidence(label="occurrences", value=occ, source_ref=f"{doc_id}:{','.join(offsets)}"),
                ],
                reasons=[f"identical amount {value} repeats {occ} times"],
            ))

    # Credit utilization: look for "X% utilization" or limit/balance pair
    util_match = re.search(r"utilization[^\d]{0,30}(\d{1,3})\s?%", lower)
    if util_match:
        pct = float(util_match.group(1))
        findings.append(Finding(
            finding_id=f"{doc_id}-utilization",
            domain="arth_bodh",
            kind="credit_utilization",
            evidence=[Evidence(label="utilization_pct", value=pct, source_ref=f"{doc_id}:{util_match.start()}")],
            reasons=["explicit utilization percentage found in statement"],
        ))

    return ParsedDocument(raw_text=raw_text, findings=findings)


def parse_with_model(raw_text_or_image_note: str, doc_id: str = "doc") -> ParsedDocument:
    """Placeholder hook: in production this step feeds the document
    (PDF/photo) directly to the LLM's vision input for extraction, per the
    brief ("no separate OCR tool needed"). Wire this to call the model with
    an image/PDF block when ANTHROPIC_API_KEY is set and a file is supplied;
    for now, text documents go through parse_statement_text directly, which
    is itself model-independent and fully working offline."""
    return parse_statement_text(raw_text_or_image_note, doc_id)
