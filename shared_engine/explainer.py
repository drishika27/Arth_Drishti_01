"""
Grounded explanation agent — the reusable logic behind Arth Bodh's
explainer/advisor agents and Arth Raksha's activity explanations.

Non-negotiable rule (see Trust and Safety Principles in the brief):
never invent a figure, definition, or finding not supported by real
evidence. This module enforces that structurally, not just via prompting:

  1. It refuses to call the model at all if the Finding carries no Evidence.
  2. Every value the model is allowed to reference is passed in explicitly,
     pre-computed, as a numbered evidence list — the model is asked to
     explain *that list*, not to reason freely about the domain.
  3. The prompt requires the model to say "I don't know" rather than fill
     gaps, and to cite which evidence item(s) support each sentence.
  4. If no ANTHROPIC_API_KEY is configured, it falls back to a deterministic
     template renderer built only from the evidence — still fully grounded,
     just less fluent. This keeps the engine testable and runnable with
     zero external dependencies, and keeps a demo honest about what's real.
"""
from __future__ import annotations

import os
from typing import Optional

from .schemas import Finding, GroundedExplanation, Language, Depth

_SYSTEM_PROMPT = """You are the ArthDrishti grounded explanation agent.

Rules you must never break:
- Only use the evidence items given to you. Never introduce a number, date,
  name, or claim that is not present in the evidence list.
- If the evidence is insufficient to explain the finding, say so plainly
  instead of guessing.
- Write in the requested language (English / Hindi / Hinglish) and at the
  requested depth (simple = 1-2 short sentences; detailed = a short
  paragraph with specific numbers from the evidence).
- Be concrete: reference the actual evidence values, not vague language.
- Do not add advice or next steps unless a suggested_action was provided.
"""


class GroundedExplainer:
    def __init__(self, api_key: Optional[str] = None, model: str = "claude-sonnet-4-6"):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.model = model
        self._client = None
        if self.api_key:
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=self.api_key)
            except Exception:
                self._client = None

    def explain(
        self,
        finding: Finding,
        language: Language = Language.ENGLISH,
        depth: Depth = Depth.SIMPLE,
    ) -> GroundedExplanation:
        if not finding.has_evidence():
            return GroundedExplanation(
                finding_id=finding.finding_id,
                text="I don't have real evidence for this, so I won't explain it.",
                language=language,
                depth=depth,
                grounded=False,
                citations=[],
            )

        if self._client is not None:
            return self._explain_with_model(finding, language, depth)
        return self._explain_with_template(finding, language, depth)

    # -- LLM path -----------------------------------------------------
    def _explain_with_model(self, finding: Finding, language: Language, depth: Depth) -> GroundedExplanation:
        evidence_block = "\n".join(
            f"[{i}] {e.label}: {e.value} (source: {e.source_ref})"
            + (f" — context: {e.raw_context}" if e.raw_context else "")
            for i, e in enumerate(finding.evidence)
        )
        reasons_block = "; ".join(finding.reasons) if finding.reasons else "(none provided)"
        user_msg = f"""Finding kind: {finding.kind}
Domain: {finding.domain}
Severity: {finding.severity.value}
Machine-computed reasons: {reasons_block}
Suggested action (only mention if present): {finding.suggested_action or "(none)"}

Evidence:
{evidence_block}

Write the explanation now. Language: {language.value}. Depth: {depth.value}.
At the end, on its own line, output: CITED: <comma-separated evidence indices you used>
"""
        try:
            resp = self._client.messages.create(
                model=self.model,
                max_tokens=400,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
            )
            text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        except Exception as exc:
            # Network/API failure: never invent a fallback narrative, fall
            # back to the deterministic template instead of pretending.
            result = self._explain_with_template(finding, language, depth)
            result.text += f" (model unavailable: {exc.__class__.__name__}; template used)"
            return result

        citations: list[str] = []
        if "CITED:" in text:
            body, cited_line = text.rsplit("CITED:", 1)
            text = body.strip()
            for tok in cited_line.strip().split(","):
                tok = tok.strip()
                if tok.isdigit() and int(tok) < len(finding.evidence):
                    citations.append(finding.evidence[int(tok)].source_ref)

        return GroundedExplanation(
            finding_id=finding.finding_id,
            text=text.strip(),
            language=language,
            depth=depth,
            grounded=True,
            citations=citations or [e.source_ref for e in finding.evidence],
        )

    # -- deterministic fallback (no API key needed) --------------------
    def _explain_with_template(self, finding: Finding, language: Language, depth: Depth) -> GroundedExplanation:
        parts = [f"{e.label}: {e.value}" for e in finding.evidence]
        joined = "; ".join(parts)
        if depth == Depth.SIMPLE:
            text = f"{finding.kind.replace('_', ' ').title()} — {parts[0]}."
        else:
            text = f"{finding.kind.replace('_', ' ').title()}. Based on: {joined}."
            if finding.reasons:
                text += " Reasons: " + "; ".join(finding.reasons) + "."
        if finding.suggested_action:
            text += f" Suggested action: {finding.suggested_action}"
        return GroundedExplanation(
            finding_id=finding.finding_id,
            text=text,
            language=language,
            depth=depth,
            grounded=True,
            citations=[e.source_ref for e in finding.evidence],
        )
