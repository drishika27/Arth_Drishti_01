"""
Tests for the Neo4j approval-graph layer (arth_raksha/backend/graph.py).

These run against a real Neo4j instance — set NEO4J_PASSWORD (and
NEO4J_URI/NEO4J_USER if not using the defaults) to run them. They skip
(not fail) when Neo4j isn't configured/reachable, so the default test
suite (`pytest tests/`) stays green without any graph database running.

Verified during development against a real, local Neo4j 5.24 Community
server (no Docker daemon was available in that environment, so it was run
directly via the Neo4j distribution + a local JRE — see README). The
docker-compose.neo4j.yml path is what's documented for everyone else.

All writes here are idempotent (MERGE keyed by tx_hash), so re-running
this file against a persistent Neo4j instance never accumulates
duplicate state — the assertions hold whether this is the first run or
the hundredth.
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("NEO4J_PASSWORD"), reason="NEO4J_PASSWORD not set — no Neo4j instance configured"
)


def _make_store():
    from arth_raksha.backend.graph import Neo4jGraphStore
    store = Neo4jGraphStore()
    try:
        store.verify_connectivity()
    except Exception as exc:
        pytest.skip(f"Neo4j configured but not reachable: {exc}")
    store.ensure_constraints()
    return store


def test_connects_and_ensures_constraints():
    store = _make_store()
    store.close()


def test_record_approval_is_idempotent_and_builds_a_real_timeline():
    from arth_raksha.backend.graph import ApprovalEvent

    store = _make_store()
    wallet, spender = "0xTestWalletTimeline", "0xTestSpenderTimeline"

    event1 = ApprovalEvent(tx_hash="0xtimeline_tx1", token_address="0xTokenA",
                            amount=2**256 - 1, is_unlimited=True, block_number=1000)
    event2 = ApprovalEvent(tx_hash="0xtimeline_tx2", token_address="0xTokenA",
                            amount=0, is_unlimited=False, block_number=2000)

    store.record_approval(wallet, spender, event1)
    store.record_approval(wallet, spender, event2)
    store.record_approval(wallet, spender, event1)  # re-record: must not duplicate

    timeline = store.get_approval_timeline(wallet, spender)
    assert len(timeline) == 2, "re-recording the same tx_hash must not create a duplicate edge"
    assert timeline[0]["block_number"] == 1000
    assert timeline[1]["block_number"] == 2000
    # The real uint256 max value must survive as an exact string, not overflow/truncate.
    assert timeline[0]["amount"] == str(2**256 - 1)
    assert timeline[0]["is_unlimited"] is True
    assert timeline[1]["is_unlimited"] is False

    store.close()


def test_wallet_summary_aggregates_across_spenders():
    from arth_raksha.backend.graph import ApprovalEvent

    store = _make_store()
    wallet = "0xTestWalletSummary"
    store.record_approval(wallet, "0xTestSpenderRepeat", ApprovalEvent(
        tx_hash="0xsummary_tx1", token_address="0xTokenA", amount=100, is_unlimited=False, block_number=1,
    ))
    store.record_approval(wallet, "0xTestSpenderRepeat", ApprovalEvent(
        tx_hash="0xsummary_tx2", token_address="0xTokenA", amount=0, is_unlimited=False, block_number=2,
    ))
    store.record_approval(wallet, "0xTestSpenderOnce", ApprovalEvent(
        tx_hash="0xsummary_tx3", token_address="0xTokenB", amount=2**256 - 1, is_unlimited=True, block_number=3,
    ))
    store.update_spender_flags("0xTestSpenderOnce", verified=False, is_scam=True)

    summary = store.get_wallet_summary(wallet)
    assert summary["distinct_spenders"] == 2
    assert summary["spenders_with_repeated_approvals"] == 1
    assert summary["spenders_ever_unlimited"] == 1
    assert summary["known_scam_spenders"] == 1

    store.close()


def test_risk_engine_attaches_real_graph_history_and_rule_fires():
    from arth_raksha.backend import risk_engine, rules
    from arth_raksha.backend.graph import ApprovalEvent
    from arth_raksha.backend.wallet_reader import Approval, WalletHistory

    store = _make_store()
    wallet, spender = "0xTestWalletRiskEngine", "0xTestSpenderRiskEngine"
    for i, block in enumerate([10, 20, 30]):
        store.record_approval(wallet, spender, ApprovalEvent(
            tx_hash=f"0xrisk_engine_tx{i}", token_address="0xTokenA",
            amount=0 if i % 2 else 2**256 - 1, is_unlimited=(i % 2 == 0), block_number=block,
        ))

    history = WalletHistory(address=wallet, data_source="live", approvals=[
        Approval(token_address="0xTokenA", spender=spender, amount=2**256 - 1,
                 tx_hash="0xrisk_engine_tx2", block_number=30, spender_verified=True),
    ])
    # spender_verified=True on the Approval so the ML path is skipped (this
    # test is about the graph signal specifically, and shouldn't depend on
    # network-bound ML feature extraction).
    findings = risk_engine.build_findings(history, w3=None, graph_store=store)
    assert len(findings) == 1
    history_evidence = next((e for e in findings[0].evidence if e.label == "approval_history_count"), None)
    assert history_evidence is not None
    assert history_evidence.value == 3

    hit = rules.rule_repeated_approval_cycle(findings[0])
    assert hit is not None
    assert "3" in hit.reason

    store.close()
