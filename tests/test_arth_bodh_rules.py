"""
Direct unit tests for Arth Bodh's scoring rules (arth_bodh/backend/rules.py)
— previously only exercised indirectly through parser output, leaving the
weight-scaling logic (e.g. utilization tiers, per-occurrence scaling)
untested on its own.
"""
from __future__ import annotations

from shared_engine import Evidence, Finding
from arth_bodh.backend.rules import (
    rule_high_fee, rule_repeating_charge, rule_high_utilization, rule_hidden_fee_language,
)


def _finding(kind: str, **evidence_kv) -> Finding:
    return Finding(
        finding_id="f", domain="arth_bodh", kind=kind,
        evidence=[Evidence(label=k, value=v, source_ref="doc:0-1") for k, v in evidence_kv.items()],
    )


def test_high_fee_fires_at_threshold_not_below():
    assert rule_high_fee(_finding("fee", amount=499)) is None
    hit = rule_high_fee(_finding("fee", amount=500))
    assert hit is not None and hit.weight == 2.0


def test_high_fee_ignores_non_fee_kind():
    assert rule_high_fee(_finding("hidden_fee", amount=9999)) is None


def test_repeating_charge_scales_with_occurrence_count():
    assert rule_repeating_charge(_finding("repeating_charge", occurrences=2)) is None
    hit3 = rule_repeating_charge(_finding("repeating_charge", occurrences=3))
    hit6 = rule_repeating_charge(_finding("repeating_charge", occurrences=6))
    assert hit3.weight == 1.5
    assert hit6.weight == 3.0  # double the occurrences -> double the weight


def test_utilization_tiers_are_correctly_bucketed():
    assert rule_high_utilization(_finding("credit_utilization", utilization_pct=29)) is None
    assert rule_high_utilization(_finding("credit_utilization", utilization_pct=40)).weight == 1.0
    assert rule_high_utilization(_finding("credit_utilization", utilization_pct=60)).weight == 3.0
    assert rule_high_utilization(_finding("credit_utilization", utilization_pct=90)).weight == 5.0


def test_hidden_fee_language_always_fires_for_its_kind():
    hit = rule_hidden_fee_language(_finding("hidden_fee"))
    assert hit is not None and hit.weight == 3.0
    assert rule_hidden_fee_language(_finding("fee")) is None
