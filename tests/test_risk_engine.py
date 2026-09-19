from arth_raksha.backend.wallet_reader import MockWalletReader
from arth_raksha.backend.risk_engine import score_wallet

def test_mock_wallet_flags_unlimited_approval():
    history = MockWalletReader().get_history("0xUserWallet")
    findings, scored, overall = score_wallet(history)
    assert overall > 0
    unlimited_hits = [s for s in scored if any(h.rule_name == "unlimited_approval" for h in s.hits)]
    assert unlimited_hits, "unlimited approval in mock fixture should be flagged"

def test_every_finding_has_a_suggested_action_when_risky():
    history = MockWalletReader().get_history("0xUserWallet")
    findings, scored, overall = score_wallet(history)
    risky = [f for f, s in zip(findings, scored) if s.total_score > 0]
    for f in risky:
        assert f.suggested_action is not None
