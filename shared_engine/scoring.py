"""
Explainable scoring framework — shared by Arth Bodh (anomaly detection) and
Arth Raksha (wallet risk scoring).

Design: a Rule is a small, named, independently-testable function that looks
at a Finding's evidence and returns a (weight, reason) pair or nothing. The
ScoringEngine only ever sums weighted rule hits and keeps every reason string
that fired — so a resulting score can never appear without a printable list
of exactly why. This is the "not a black box" requirement from the brief.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from .schemas import Finding, Severity


@dataclass
class RuleHit:
    rule_name: str
    weight: float
    reason: str


@dataclass
class ScoredResult:
    finding_id: str
    total_score: float
    severity: Severity
    hits: list[RuleHit]

    def reasons(self) -> list[str]:
        return [h.reason for h in self.hits]


Rule = Callable[[Finding], Optional[RuleHit]]


class ScoringEngine:
    """Domain-agnostic. Arth Bodh and Arth Raksha each register their own
    rules; the engine logic (summing, thresholding, explaining) is identical
    for both, per the brief's "same scoring engine logic" requirement."""

    def __init__(self, name: str):
        self.name = name
        self._rules: list[Rule] = []
        # severity thresholds are shared defaults; domains may override
        self.thresholds: dict[Severity, float] = {
            Severity.LOW: 1.0,
            Severity.MEDIUM: 3.0,
            Severity.HIGH: 6.0,
            Severity.CRITICAL: 10.0,
        }

    def register(self, rule: Rule) -> None:
        self._rules.append(rule)

    def score(self, finding: Finding) -> ScoredResult:
        hits: list[RuleHit] = []
        for rule in self._rules:
            hit = rule(finding)
            if hit is not None:
                hits.append(hit)
        total = sum(h.weight for h in hits)
        severity = Severity.INFO
        for sev in (Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW):
            if total >= self.thresholds[sev]:
                severity = sev
                break
        return ScoredResult(
            finding_id=finding.finding_id,
            total_score=round(total, 3),
            severity=severity,
            hits=hits,
        )

    def score_all(self, findings: list[Finding]) -> list[ScoredResult]:
        return [self.score(f) for f in findings]
