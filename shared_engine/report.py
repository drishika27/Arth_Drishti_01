"""
Exportable plain-language safety/findings report — Markdown always
available, PDF via fpdf2. Shared by both products since both reduce
their findings to the same Finding/ScoredResult shape (see schemas.py) —
this module never sees a bank fee or a token approval directly, only
that shared shape, exactly like scoring.py and explainer.py.

For the user's own records: everything here is grounded in the same
Evidence already attached to each Finding — this module renders and
formats, it never computes a new number or claim.

PDF text rendering is script-aware: any string containing a character
outside Latin-1 (i.e., not plain English/European text) is rendered with
an embedded Noto Sans Devanagari font (shared_engine/fonts/, OFL-licensed
— see fonts/LICENSE.txt) so real Hindi explanations render as real
Devanagari glyphs, not boxes; everything else uses the PDF's built-in
Helvetica. Verified round-trip (generate -> extract text -> compare) for
English, Hindi, and Hinglish content — see tests/test_report.py.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass

from .schemas import Finding
from .scoring import ScoredResult

_FONT_PATH = os.path.join(os.path.dirname(__file__), "fonts", "NotoSansDevanagari-Regular.ttf")
_NON_LATIN1_THRESHOLD = 0x00FF  # anything beyond Latin-1 needs the Devanagari font


@dataclass
class ReportSection:
    finding: Finding
    scored: ScoredResult
    explanation: str


def _needs_unicode_font(text: str) -> bool:
    return any(ord(ch) > _NON_LATIN1_THRESHOLD for ch in text)


def render_markdown(title: str, subtitle: str, overall_score: float,
                     sections: list[ReportSection], footer_note: str) -> str:
    lines = [
        f"# {title}", "", subtitle, "",
        f"_Generated {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}_", "",
        f"**Overall score: {overall_score}**", "",
    ]
    for s in sections:
        lines.append(f"## {s.finding.kind.replace('_', ' ').title()} — "
                      f"{s.scored.severity.value.upper()} (score {s.scored.total_score})")
        lines.append("")
        for r in s.scored.reasons():
            lines.append(f"- {r}")
        if s.scored.reasons():
            lines.append("")
        lines.append(s.explanation)
        if s.finding.suggested_action:
            lines.append("")
            lines.append(f"**Suggested action:** {s.finding.suggested_action}")
        lines.append("")
        lines.append("**Evidence:**")
        for e in s.finding.evidence:
            lines.append(f"- {e.label}: {e.value}")
        lines.append("")
        lines.append("---")
        lines.append("")
    lines.append(footer_note)
    return "\n".join(lines)


def render_pdf(title: str, subtitle: str, overall_score: float,
                sections: list[ReportSection], footer_note: str) -> bytes:
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.add_font("NotoDevanagari", "", _FONT_PATH)

    def write(text: str, style: str = "", size: int = 11, height: int = 7):
        font = "NotoDevanagari" if _needs_unicode_font(text) else "Helvetica"
        # NotoDevanagari was only embedded as a Regular weight — bold
        # styling silently has no effect for Devanagari text, which is a
        # cosmetic gap, not a correctness one (the glyphs themselves are
        # unaffected either way).
        pdf.set_font(font, style if font == "Helvetica" else "", size)
        pdf.multi_cell(0, height, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    write(title, style="B", size=18, height=10)
    write(subtitle, size=11)
    pdf.ln(1)
    write(f"Generated {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}", size=9)
    pdf.ln(3)
    write(f"Overall score: {overall_score}", style="B", size=13)
    pdf.ln(3)

    for s in sections:
        write(f"{s.finding.kind.replace('_', ' ').title()} - "
              f"{s.scored.severity.value.upper()} (score {s.scored.total_score})", style="B", size=13)
        for r in s.scored.reasons():
            write(f"- {r}", size=10)
        pdf.ln(1)
        write(s.explanation, size=10)
        if s.finding.suggested_action:
            write(f"Suggested action: {s.finding.suggested_action}", style="B", size=10)
        pdf.ln(1)
        for e in s.finding.evidence:
            write(f"{e.label}: {e.value}", size=9)
        pdf.ln(4)

    write(footer_note, style="I", size=8)
    return bytes(pdf.output())
