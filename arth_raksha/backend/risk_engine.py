"""Turns a WalletHistory into Findings, then scores them via the shared engine."""
from __future__ import annotations

from shared_engine import Finding, Evidence, ScoringEngine
from .wallet_reader import WalletHistory, _rpc_rate_limiter
from .known_scam_addresses import is_known_scam
from .known_verified_contracts import is_verified_contract
from .rules import ALL_RULES
from .ml_signal import get_signal

_engine = ScoringEngine("arth_raksha")
for r in ALL_RULES:
    _engine.register(r)

ML_SCAM_PROBABILITY_THRESHOLD = 0.6
ML_FEATURE_LOOKBACK_BLOCKS = 10_000  # bounded window so scoring one spender stays fast
MAX_ML_LOOKUPS_PER_REQUEST = 8        # each lookup costs 2-4 real RPC round-trips; cap total request latency


def _attach_ml_signal(evidence: list[Evidence], spender: str, w3, cache: dict) -> bool:
    """Scores `spender`'s own on-chain behavior with the trained classifier
    and appends evidence for it. Returns True if the ML signal itself
    considers this spender scam-like, so the caller can factor it into
    suggested_action. Never raises — a feature-extraction or scoring
    failure just means no ML evidence is attached for this spender,
    exactly like "no evidence" anywhere else in this engine."""
    if spender not in cache:
        cache[spender] = None
        try:
            from .wallet_features import compute_features_from_rpc
            _rpc_rate_limiter.wait()
            head = w3.eth.block_number
            extraction = compute_features_from_rpc(
                w3, spender, max(0, head - ML_FEATURE_LOOKBACK_BLOCKS), head
            )
            result = get_signal().score(extraction.features)
            cache[spender] = (extraction, result)
        except Exception:
            pass  # honest silence, not a fabricated score

    cached = cache[spender]
    if cached is None:
        return False
    extraction, result = cached
    total_features = result.features_used + result.features_imputed
    evidence.append(Evidence(
        label="ml_scam_probability",
        value=round(result.probability, 4),
        source_ref="ml_model:gradient_boosting_v1",
        raw_context=(
            f"{result.features_used} of {total_features} behavioral features "
            f"computed from real on-chain data ({extraction.source}); rest "
            f"median-imputed from the training distribution"
        ),
    ))
    if result.top_contributors:
        evidence.append(Evidence(
            label="ml_top_signals",
            value=[f"{name} ({'+' if delta > 0 else ''}{delta:.3f} probability)"
                   for name, delta in result.top_contributors],
            source_ref="ml_model:gradient_boosting_v1",
        ))
    return result.probability >= ML_SCAM_PROBABILITY_THRESHOLD


def _attach_graph_history(evidence: list[Evidence], wallet_address: str, spender: str,
                           verified: bool, scam: bool, graph_store) -> None:
    """Writes this spender's verification/scam judgment into the graph
    (graph_store.update_spender_flags — see graph.py for why this is a
    separate write from wallet_reader.py's raw-fact recording), then reads
    back the full approval timeline between this wallet and this spender.
    A wallet that approved, was revoked, and re-approved the same spender
    shows up as >1 timeline entries here — a real behavioral signal a
    single RPC snapshot can't see. Never raises: a graph read/write
    failure just means this evidence is absent, same as anywhere else."""
    try:
        graph_store.update_spender_flags(spender, verified, scam)
        timeline = graph_store.get_approval_timeline(wallet_address, spender)
    except Exception:
        return
    if len(timeline) > 1:
        evidence.append(Evidence(
            label="approval_history_count", value=len(timeline),
            source_ref="neo4j:approval_timeline",
            raw_context=f"{len(timeline)} recorded approval events between this wallet and this spender over time",
        ))


def build_findings(history: WalletHistory, w3=None, graph_store=None) -> list[Finding]:
    """`w3` is an optional live web3 connection used only to score each
    approval's spender with the ML signal (see _attach_ml_signal). It's
    None for mock/offline wallets, in which case the ML rule simply never
    fires — no network, no invented probability.

    ML lookups are skipped for spenders that already have a clear signal
    (a known-scam match, or a match on our verified-contract allow-list) —
    they don't need a third opinion, and it keeps requests fast. Lookups
    are also capped per request (MAX_ML_LOOKUPS_PER_REQUEST); once the cap
    is hit, remaining approvals are marked with an honest
    ml_signal_skipped evidence item rather than silently omitted."""
    findings = []
    ml_cache: dict[str, tuple | None] = {}
    signal_available = w3 is not None and get_signal().available
    ml_lookups_done = 0

    for a in history.approvals:
        scam = is_known_scam(a.spender)
        # A live reader has no way to know contract verification on its own;
        # we look it up against our maintained allow-list here instead of
        # ever inventing it. `spender_verified` on the Approval itself is
        # only ever set by fixtures (MockWalletReader) — OR'ing it in keeps
        # those illustrative fixtures working without letting the live path
        # silently default to "unverified" when we do recognise the spender.
        verified = a.spender_verified or is_verified_contract(a.spender)

        evidence = [
            Evidence(label="token", value=a.token_address, source_ref=a.tx_hash),
            Evidence(label="spender", value=a.spender, source_ref=a.tx_hash),
            Evidence(label="amount", value=a.amount, source_ref=a.tx_hash),
            Evidence(label="is_unlimited", value=a.is_unlimited, source_ref=a.tx_hash),
            Evidence(label="spender_verified", value=verified, source_ref=a.tx_hash),
            Evidence(label="is_known_scam", value=scam, source_ref=a.tx_hash),
            Evidence(label="block_number", value=a.block_number, source_ref=a.tx_hash),
        ]

        ml_flagged = False
        if signal_available and not scam and not verified:
            if a.spender in ml_cache or ml_lookups_done < MAX_ML_LOOKUPS_PER_REQUEST:
                if a.spender not in ml_cache:
                    ml_lookups_done += 1
                ml_flagged = _attach_ml_signal(evidence, a.spender, w3, ml_cache)
            else:
                evidence.append(Evidence(
                    label="ml_signal_skipped",
                    value=f"lookup cap ({MAX_ML_LOOKUPS_PER_REQUEST} distinct spenders) reached for this request",
                    source_ref="ml_model:gradient_boosting_v1",
                ))

        if graph_store is not None:
            _attach_graph_history(evidence, history.address, a.spender, verified, scam, graph_store)

        action = "Revoke this approval" if (a.is_unlimited or not verified or scam or ml_flagged) else None
        findings.append(Finding(
            finding_id=f"approval-{a.tx_hash}",
            domain="arth_raksha",
            kind="approval",
            evidence=evidence,
            suggested_action=action,
        ))
    return findings


def score_wallet(history: WalletHistory, w3=None, graph_store=None):
    findings = build_findings(history, w3=w3, graph_store=graph_store)
    scored = _engine.score_all(findings)
    overall = sum(s.total_score for s in scored)
    return findings, scored, overall
