"""Arth Raksha's domain-specific risk-scoring rules, run through the shared engine."""
from shared_engine import Finding, RuleHit

def rule_unlimited_approval(f: Finding):
    if f.kind != "approval":
        return None
    unlimited = next((e.value for e in f.evidence if e.label == "is_unlimited"), False)
    if unlimited:
        return RuleHit("unlimited_approval", weight=4.0, reason="Unlimited spending approval granted")
    return None

def rule_unverified_spender(f: Finding):
    if f.kind != "approval":
        return None
    verified = next((e.value for e in f.evidence if e.label == "spender_verified"), True)
    if not verified:
        return RuleHit("unverified_spender", weight=2.5, reason="Approval given to an unverified/unrecognised contract")
    return None

def rule_known_scam(f: Finding):
    if f.kind != "approval":
        return None
    is_scam = next((e.value for e in f.evidence if e.label == "is_known_scam"), False)
    if is_scam:
        return RuleHit("known_scam_address", weight=8.0, reason="Spender matches a known scam/phishing address")
    return None

def rule_ml_scam_signal(f: Finding):
    """Blends the trained scam-behavior classifier (arth_raksha/ml/train.py)
    in as one more scored, explained signal — never a bare probability.
    Only fires when risk_engine.py actually attached an ml_scam_probability
    evidence item (i.e. live chain data + a trained model were available);
    absent for mock/offline wallets, by design."""
    if f.kind != "approval":
        return None
    prob = next((e.value for e in f.evidence if e.label == "ml_scam_probability"), None)
    if prob is None or prob < 0.6:
        return None
    signals = next((e.value for e in f.evidence if e.label == "ml_top_signals"), [])
    signal_str = "; ".join(signals) if signals else "no single dominant signal in this prediction"
    weight = round(3.0 + 4.0 * (prob - 0.6) / 0.4, 2)  # 3.0 at the 0.6 threshold, up to 7.0 at prob=1.0
    return RuleHit(
        "ml_scam_signal", weight=weight,
        reason=f"ML scam-behavior classifier flags this spender with {prob:.0%} probability — top signals: {signal_str}",
    )

def rule_repeated_approval_cycle(f: Finding):
    """Fed by the Neo4j approval-timeline graph (risk_engine._attach_graph_history)
    — fires when this spender has been approved, revoked, and re-approved
    by this wallet more than once. Not fatal on its own (many legitimate
    dApps do prompt a fresh approval after a revoke), but worth surfacing:
    it's exactly the pattern some drainer dApps rely on ("please re-approve,
    something went wrong") to get a second shot at an unlimited approval."""
    if f.kind != "approval":
        return None
    count = next((e.value for e in f.evidence if e.label == "approval_history_count"), None)
    if count is None or count <= 1:
        return None
    return RuleHit(
        "repeated_approval_cycle", weight=1.0 + 0.5 * (count - 2),
        reason=f"This spender has been approved/revoked {count} times by this wallet historically",
    )

ALL_RULES = [
    rule_unlimited_approval, rule_unverified_spender, rule_known_scam,
    rule_ml_scam_signal, rule_repeated_approval_cycle,
]
