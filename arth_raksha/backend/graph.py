"""
Neo4j graph layer for a wallet's OWN approval/connection graph.

Schema (see docker-compose.neo4j.yml for a local instance):

    (:Wallet {address})-[:APPROVED {tx_hash, amount, is_unlimited,
                                     token_address, block_number, ts}]
                        ->(:Spender {address, verified, is_scam})

Multiple :APPROVED relationships can exist between the same Wallet and
Spender (one per real on-chain approval event, deduplicated by tx_hash) —
that's what makes this a genuine timeline rather than a snapshot: querying
all edges between a wallet and a spender, ordered by block_number, shows
exactly how that approval changed over time (e.g. granted unlimited,
revoked, re-granted with a cap).

Only ever represents the connected wallet's OWN approvals — there is no
query here that accepts or compares a second party's wallet, consistent
with the platform-wide rule enforced throughout arth_raksha/backend/.

Every write is idempotent (MERGE keyed by tx_hash for edges, by address
for nodes), so re-scanning the same block range twice is safe.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class ApprovalEvent:
    tx_hash: str
    token_address: str
    amount: int
    is_unlimited: bool
    block_number: int
    spender_verified: bool = False
    is_scam: bool = False


class Neo4jGraphStore:
    """Thin wrapper around the official neo4j driver. Construct with an
    explicit uri/user/password, or rely on NEO4J_URI / NEO4J_USER /
    NEO4J_PASSWORD env vars (matching docker-compose.neo4j.yml)."""

    def __init__(self, uri: Optional[str] = None, user: Optional[str] = None, password: Optional[str] = None):
        from neo4j import GraphDatabase
        self.uri = uri or os.environ.get("NEO4J_URI", "bolt://localhost:7687")
        user = user or os.environ.get("NEO4J_USER", "neo4j")
        password = password or os.environ.get("NEO4J_PASSWORD")
        if not password:
            raise RuntimeError(
                "No Neo4j password configured. Set NEO4J_PASSWORD (matching "
                "docker-compose.neo4j.yml, or your own instance's password)."
            )
        self._driver = GraphDatabase.driver(self.uri, auth=(user, password))

    def close(self) -> None:
        self._driver.close()

    def verify_connectivity(self) -> None:
        self._driver.verify_connectivity()

    def ensure_constraints(self) -> None:
        """Idempotent — safe to call on every startup. Uniqueness
        constraints double as indexes in Neo4j, which is what keeps
        lookups fast for a wallet with a long approval history."""
        statements = [
            "CREATE CONSTRAINT wallet_address IF NOT EXISTS FOR (w:Wallet) REQUIRE w.address IS UNIQUE",
            "CREATE CONSTRAINT spender_address IF NOT EXISTS FOR (s:Spender) REQUIRE s.address IS UNIQUE",
            "CREATE CONSTRAINT approval_event_id IF NOT EXISTS FOR ()-[r:APPROVED]-() REQUIRE r.event_id IS UNIQUE",
            "CREATE INDEX approval_block_number IF NOT EXISTS FOR ()-[r:APPROVED]-() ON (r.block_number)",
        ]
        with self._driver.session() as session:
            for stmt in statements:
                session.run(stmt)

    def record_approval(self, wallet_address: str, spender_address: str, event: ApprovalEvent) -> None:
        """Idempotent: re-recording the same tx_hash is a no-op (MERGE on
        the relationship key), so re-scanning overlapping block ranges
        never creates duplicate timeline entries.

        `amount` is a uint256 on-chain (an "unlimited" approval is
        typically 2**256-1) and Neo4j's Bolt protocol only supports
        64-bit signed integers — storing it as a native int would
        silently overflow. It's stored as a decimal string instead, which
        preserves the exact real value; `is_unlimited` (a plain bool) is
        what queries and scoring actually branch on.

        The relationship's uniqueness key is (tx_hash, token_address,
        spender_address), not tx_hash alone — discovered live while
        testing this against a real wallet: a single transaction can emit
        several distinct Approval events (e.g. a batch/multicall
        approving several tokens at once), so tx_hash alone collides.
        """
        event_id = f"{event.tx_hash}:{event.token_address.lower()}:{spender_address.lower()}"
        query = """
        MERGE (w:Wallet {address: $wallet})
        MERGE (s:Spender {address: $spender})
        SET s.verified = $verified, s.is_scam = $is_scam
        MERGE (w)-[r:APPROVED {event_id: $event_id}]->(s)
        SET r.tx_hash = $tx_hash,
            r.token_address = $token_address,
            r.amount = $amount,
            r.is_unlimited = $is_unlimited,
            r.block_number = $block_number
        """
        with self._driver.session() as session:
            session.run(
                query,
                wallet=wallet_address.lower(),
                spender=spender_address.lower(),
                verified=event.spender_verified,
                is_scam=event.is_scam,
                event_id=event_id,
                tx_hash=event.tx_hash,
                token_address=event.token_address,
                amount=str(event.amount),
                is_unlimited=event.is_unlimited,
                block_number=event.block_number,
            )

    def update_spender_flags(self, spender_address: str, verified: bool, is_scam: bool) -> None:
        """Separate from record_approval on purpose: wallet_reader.py knows
        raw on-chain facts (who approved whom, how much, when) but not
        verification/scam status — that judgment is computed later by
        risk_engine.py against the maintained allow-list and scam list,
        and only that layer should be writing it."""
        with self._driver.session() as session:
            session.run(
                "MERGE (s:Spender {address: $spender}) SET s.verified = $verified, s.is_scam = $is_scam",
                spender=spender_address.lower(), verified=verified, is_scam=is_scam,
            )

    def get_approval_timeline(self, wallet_address: str, spender_address: str) -> list[dict]:
        """All recorded approval events between this wallet and this
        spender, oldest first — the actual "history, not just a snapshot"
        the brief asks for. A wallet that approved unlimited, revoked
        (amount=0), then re-approved with a cap shows up here as three
        distinct rows, not one overwritten value."""
        query = """
        MATCH (w:Wallet {address: $wallet})-[r:APPROVED]->(s:Spender {address: $spender})
        RETURN r.tx_hash AS tx_hash, r.amount AS amount, r.is_unlimited AS is_unlimited,
               r.token_address AS token_address, r.block_number AS block_number
        ORDER BY r.block_number ASC
        """
        with self._driver.session() as session:
            result = session.run(query, wallet=wallet_address.lower(), spender=spender_address.lower())
            return [dict(record) for record in result]

    def get_wallet_summary(self, wallet_address: str) -> dict:
        """Aggregate, graph-derived signals a flat approval list can't
        answer cheaply: how many distinct spenders has this wallet ever
        approved, and how many of those approval relationships have more
        than one historical event (i.e. were revoked/re-approved at least
        once) — a real behavioral signal, not available from a single
        RPC snapshot."""
        query = """
        MATCH (w:Wallet {address: $wallet})-[r:APPROVED]->(s:Spender)
        WITH s, count(r) AS edge_count, max(r.is_unlimited) AS ever_unlimited, max(s.is_scam) AS is_scam
        RETURN count(s) AS distinct_spenders,
               sum(CASE WHEN edge_count > 1 THEN 1 ELSE 0 END) AS spenders_with_repeated_approvals,
               sum(CASE WHEN ever_unlimited THEN 1 ELSE 0 END) AS spenders_ever_unlimited,
               sum(CASE WHEN is_scam THEN 1 ELSE 0 END) AS known_scam_spenders
        """
        with self._driver.session() as session:
            record = session.run(query, wallet=wallet_address.lower()).single()
            return dict(record) if record else {
                "distinct_spenders": 0, "spenders_with_repeated_approvals": 0,
                "spenders_ever_unlimited": 0, "known_scam_spenders": 0,
            }
