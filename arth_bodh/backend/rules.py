"""Arth Bodh's domain-specific scoring rules, run through the shared engine."""
from shared_engine import Finding, RuleHit

def rule_high_fee(f: Finding):
    if f.kind != "fee":
        return None
    amt = next((e.value for e in f.evidence if e.label == "amount"), None)
    if isinstance(amt, (int, float)) and amt >= 500:
        return RuleHit("high_fee", weight=2.0, reason=f"Fee of {amt} is unusually large")
    return None

def rule_repeating_charge(f: Finding):
    if f.kind != "repeating_charge":
        return None
    count = next((e.value for e in f.evidence if e.label == "occurrences"), 0)
    if isinstance(count, (int, float)) and count >= 3:
        return RuleHit("repeating_charge", weight=1.5 * (count / 3), reason=f"Same charge appears {count} times")
    return None

def rule_high_utilization(f: Finding):
    if f.kind != "credit_utilization":
        return None
    pct = next((e.value for e in f.evidence if e.label == "utilization_pct"), None)
    if isinstance(pct, (int, float)) and pct >= 30:
        weight = 1.0 if pct < 50 else (3.0 if pct < 80 else 5.0)
        return RuleHit("high_utilization", weight=weight, reason=f"Credit utilization at {pct}%")
    return None

def rule_hidden_fee_language(f: Finding):
    if f.kind != "hidden_fee":
        return None
    return RuleHit("hidden_fee", weight=3.0, reason="Fee term found with no clear plain-language definition nearby")

ALL_RULES = [rule_high_fee, rule_repeating_charge, rule_high_utilization, rule_hidden_fee_language]
