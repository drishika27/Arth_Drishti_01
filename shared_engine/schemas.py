"""
ArthDrishti shared trust engine — core data shapes.

Both products reduce their very different raw inputs down to the same
shape before the engine touches them: a Finding, backed by real Evidence.
The engine never sees "a bank fee" or "a token approval" — only this.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional
import time


class Severity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Language(str, Enum):
    ENGLISH = "en"
    HINDI = "hi"
    HINGLISH = "hinglish"


class Depth(str, Enum):
    SIMPLE = "simple"
    DETAILED = "detailed"


@dataclass
class Evidence:
    """A single piece of real, already-computed evidence backing a finding.

    `source_ref` is how a caller can trace this back to the raw input
    (a byte offset in a document, an on-chain tx hash, a log index...).
    This is what makes "never invent a figure" enforceable rather than
    aspirational: every number the engine explains must point at one of
    these.
    """
    label: str
    value: Any
    source_ref: str
    raw_context: Optional[str] = None


@dataclass
class Finding:
    """The one shape the shared engine understands, regardless of domain."""
    finding_id: str
    domain: str                 # "arth_bodh" | "arth_raksha"
    kind: str                   # e.g. "hidden_fee", "unlimited_approval"
    evidence: list[Evidence]
    reasons: list[str] = field(default_factory=list)   # short machine reasons, pre-LLM
    suggested_action: Optional[str] = None
    severity: Severity = Severity.INFO
    score: float = 0.0
    created_at: float = field(default_factory=time.time)

    def has_evidence(self) -> bool:
        return len(self.evidence) > 0


@dataclass
class GroundedExplanation:
    """Output of the grounded explanation agent. Never free-floating text —
    always tied back to the Finding it was generated from."""
    finding_id: str
    text: str
    language: Language
    depth: Depth
    grounded: bool               # False if the model could not ground it
    citations: list[str] = field(default_factory=list)  # evidence source_refs used
