"""
Tests for the trained scam-behavior classifier (arth_raksha/ml/) and its
integration as a scored, explained signal in risk_engine.py — never a bare
number, per the brief's "not a black box" requirement.
"""
from __future__ import annotations

import json
import os

from arth_raksha.backend import risk_engine
from arth_raksha.backend.ml_signal import get_signal
from arth_raksha.backend.rules import rule_ml_scam_signal
from arth_raksha.backend.wallet_features import FeatureExtractionResult
from arth_raksha.backend.wallet_reader import Approval, WalletHistory
from shared_engine import Finding, Evidence

_MODEL_DIR = os.path.join(os.path.dirname(__file__), "..", "arth_raksha", "ml", "model")


def test_model_artifacts_exist_and_report_real_metrics():
    metrics_path = os.path.join(_MODEL_DIR, "metrics.json")
    assert os.path.exists(metrics_path), "run `python -m arth_raksha.ml.train` first"
    with open(metrics_path) as f:
        metrics = json.load(f)
    assert metrics["n_train"] > 0 and metrics["n_test"] > 0
    gb = metrics["gradient_boosting"]
    # Real, held-out precision/recall — not asserting a specific number
    # (that would be re-testing sklearn), just that training actually ran
    # and produced a usable, evaluated classifier.
    assert 0.0 <= gb["precision"] <= 1.0
    assert 0.0 <= gb["recall"] <= 1.0
    assert gb["roc_auc"] > 0.5, "classifier should beat random guessing on held-out data"


def test_signal_loads_and_scores_a_known_pattern():
    signal = get_signal()
    assert signal.available, "model must be trained (python -m arth_raksha.ml.train) for this test to be meaningful"

    # A feature vector shaped like the dataset's fraud-flagged addresses:
    # very high ERC20 transaction count is the model's single strongest
    # real signal (see permutation importance in metrics.json).
    scam_like = {"Total_ERC20_tnxs": 500.0, "Unique_Received_From_Addresses": 200.0}
    result = signal.score(scam_like)
    assert 0.0 <= result.probability <= 1.0
    assert result.features_used == 2
    assert result.features_imputed > 0  # honest: most of the ~48 features weren't given

    # Ablation-based explanation must be real and non-empty when inputs
    # differ from the training median.
    assert result.top_contributors, "expected at least one ablation-based contributor"
    for name, delta in result.top_contributors:
        assert isinstance(name, str) and isinstance(delta, float)


def test_ml_rule_fires_only_above_threshold_and_cites_signals():
    high_prob_finding = Finding(
        finding_id="f1", domain="arth_raksha", kind="approval",
        evidence=[
            Evidence(label="ml_scam_probability", value=0.91, source_ref="ml_model:gradient_boosting_v1"),
            Evidence(label="ml_top_signals", value=["Total_ERC20_tnxs (+0.400 probability)"],
                      source_ref="ml_model:gradient_boosting_v1"),
        ],
    )
    hit = rule_ml_scam_signal(high_prob_finding)
    assert hit is not None
    assert "91%" in hit.reason
    assert "Total_ERC20_tnxs" in hit.reason

    low_prob_finding = Finding(
        finding_id="f2", domain="arth_raksha", kind="approval",
        evidence=[Evidence(label="ml_scam_probability", value=0.1, source_ref="ml_model:gradient_boosting_v1")],
    )
    assert rule_ml_scam_signal(low_prob_finding) is None


def test_ml_rule_absent_without_evidence_never_invents_a_score():
    finding = Finding(
        finding_id="f3", domain="arth_raksha", kind="approval",
        evidence=[Evidence(label="token", value="0xabc", source_ref="tx:1")],
    )
    assert rule_ml_scam_signal(finding) is None


def test_ml_lookups_are_capped_per_request_without_network(monkeypatch):
    """A wallet with many distinct, never-before-seen spenders must not
    turn a risk check into dozens of real RPC round-trips — discovered as
    a genuine performance issue when this was tested against a real,
    unusually hyperactive wallet (231 approvals to many spenders took over
    a minute end-to-end before this cap existed). This test verifies the
    cap logic itself, fast and offline, by faking the RPC-dependent feature
    extractor rather than depending on network timing."""
    calls = []

    def fake_extract(w3, address, from_block, to_block):
        calls.append(address)
        return FeatureExtractionResult(features={"Total_ERC20_tnxs": 1.0}, features_computed=["Total_ERC20_tnxs"])

    monkeypatch.setattr("arth_raksha.backend.wallet_features.compute_features_from_rpc", fake_extract)

    class _FakeEth:
        block_number = 20_000_000

    class _FakeW3:
        eth = _FakeEth()

    n_spenders = risk_engine.MAX_ML_LOOKUPS_PER_REQUEST + 5
    approvals = [
        Approval(
            token_address="0xToken", spender=f"0xSpender{i:040d}", amount=1000,
            tx_hash=f"0xtx{i}", block_number=100 + i,
        )
        for i in range(n_spenders)
    ]
    history = WalletHistory(address="0xOwner", approvals=approvals, data_source="live")

    findings = risk_engine.build_findings(history, w3=_FakeW3())

    assert len(calls) == risk_engine.MAX_ML_LOOKUPS_PER_REQUEST, (
        "expected exactly the capped number of real feature-extraction attempts, "
        f"got {len(calls)}"
    )
    scored_findings = [f for f in findings if any(e.label == "ml_scam_probability" for e in f.evidence)]
    skipped_findings = [f for f in findings if any(e.label == "ml_signal_skipped" for e in f.evidence)]
    assert len(scored_findings) == risk_engine.MAX_ML_LOOKUPS_PER_REQUEST
    assert len(skipped_findings) == n_spenders - risk_engine.MAX_ML_LOOKUPS_PER_REQUEST
