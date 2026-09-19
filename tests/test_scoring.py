from shared_engine import ScoringEngine, Finding, Evidence, Severity

def test_scoring_sums_weighted_hits_and_keeps_reasons():
    engine = ScoringEngine("test")
    def rule_a(f):
        from shared_engine.scoring import RuleHit
        if f.kind == "x":
            return RuleHit("rule_a", 2.0, "reason a")
        return None
    def rule_b(f):
        from shared_engine.scoring import RuleHit
        if f.kind == "x":
            return RuleHit("rule_b", 5.0, "reason b")
        return None
    engine.register(rule_a)
    engine.register(rule_b)

    finding = Finding(finding_id="f1", domain="test", kind="x",
                       evidence=[Evidence("v", 1, "src:0")])
    result = engine.score(finding)
    assert result.total_score == 7.0
    assert result.severity == Severity.HIGH
    assert set(result.reasons()) == {"reason a", "reason b"}

def test_no_rules_fire_gives_info_severity():
    engine = ScoringEngine("test")
    finding = Finding(finding_id="f2", domain="test", kind="unmatched", evidence=[])
    result = engine.score(finding)
    assert result.total_score == 0
    assert result.severity == Severity.INFO
