from shared_engine import Finding, Evidence, GroundedExplainer

def test_no_evidence_refuses_to_explain():
    explainer = GroundedExplainer(api_key=None)
    finding = Finding(finding_id="f1", domain="arth_bodh", kind="fee", evidence=[])
    result = explainer.explain(finding)
    assert result.grounded is False
    assert "won't" in result.text or "don't" in result.text

def test_template_fallback_only_uses_given_evidence():
    explainer = GroundedExplainer(api_key=None)
    finding = Finding(
        finding_id="f2", domain="arth_bodh", kind="fee",
        evidence=[Evidence(label="amount", value=750, source_ref="doc:10-20")],
    )
    result = explainer.explain(finding)
    assert result.grounded is True
    assert "750" in result.text
    # must not invent any other number
    assert "1000" not in result.text
