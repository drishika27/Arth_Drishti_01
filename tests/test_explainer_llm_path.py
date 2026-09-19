"""
Tests for GroundedExplainer's LLM path (shared_engine/explainer.py) —
previously entirely untested since this environment has no
ANTHROPIC_API_KEY. The real Anthropic client is swapped for a fake one
(no network involved) so the citation-parsing and fallback-on-failure
logic — the part of this module actually worth testing — gets exercised
for real instead of being dead code.
"""
from __future__ import annotations

from dataclasses import dataclass

from shared_engine import Depth, Evidence, Finding, Language
from shared_engine.explainer import GroundedExplainer


@dataclass
class _FakeTextBlock:
    text: str
    type: str = "text"


class _FakeMessages:
    def __init__(self, response_text=None, exc=None):
        self._response_text = response_text
        self._exc = exc

    def create(self, **kwargs):
        if self._exc:
            raise self._exc
        return type("Resp", (), {"content": [_FakeTextBlock(self._response_text)]})()


class _FakeClient:
    def __init__(self, response_text=None, exc=None):
        self.messages = _FakeMessages(response_text, exc)


def _finding() -> Finding:
    return Finding(
        finding_id="f1", domain="arth_bodh", kind="fee",
        evidence=[
            Evidence(label="term", value="Late Payment Fee", source_ref="doc:0-10"),
            Evidence(label="amount", value=750, source_ref="doc:10-20"),
        ],
        reasons=["matched known fee terminology"],
    )


def test_llm_response_with_citation_line_is_parsed_correctly():
    explainer = GroundedExplainer(api_key="fake")
    explainer._client = _FakeClient(response_text="This fee of 750 is a late payment charge.\nCITED: 0,1")

    result = explainer.explain(_finding(), language=Language.ENGLISH, depth=Depth.DETAILED)
    assert result.grounded is True
    assert "CITED:" not in result.text  # the citation line is stripped from the visible text
    assert "750" in result.text
    assert result.citations == ["doc:0-10", "doc:10-20"]


def test_llm_response_without_citation_line_defaults_to_all_evidence():
    explainer = GroundedExplainer(api_key="fake")
    explainer._client = _FakeClient(response_text="This fee of 750 is a late payment charge.")

    result = explainer.explain(_finding())
    assert result.citations == ["doc:0-10", "doc:10-20"]
    assert "750" in result.text


def test_llm_failure_falls_back_to_template_never_inventing_a_narrative():
    explainer = GroundedExplainer(api_key="fake")
    explainer._client = _FakeClient(exc=ConnectionError("simulated network failure"))

    result = explainer.explain(_finding(), depth=Depth.DETAILED)
    assert result.grounded is True  # template fallback is still grounded, just less fluent
    assert "model unavailable: ConnectionError" in result.text
    assert "750" in result.text  # the template fallback still cites real evidence


def test_out_of_range_citation_index_is_ignored_not_crashed():
    explainer = GroundedExplainer(api_key="fake")
    explainer._client = _FakeClient(response_text="Explanation text.\nCITED: 0,5,abc")

    result = explainer.explain(_finding())
    assert result.citations == ["doc:0-10"]  # index 5 and "abc" silently ignored, index 0 kept
