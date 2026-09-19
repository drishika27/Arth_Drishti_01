# ArthDrishti (अर्थ दृष्टि)

One shared trust engine, two products: **Arth Bodh** (bank statement explainer)
and **Arth Raksha** (crypto wallet safety). Built from the project brief.

## What's actually real here vs. what's a documented next step

This is a genuine, running codebase — not a mockup. Be clear-eyed about what's
included at each depth:

**Fully working right now, with tests passing:**
- The shared trust engine (`shared_engine/`): grounded explanation agent,
  explainable rule-based scoring, multilingual scaffolding.
- Arth Bodh backend: parses statement text into evidence-backed findings,
  scores anomalies, explains them, answers grounded follow-up chat.
- Arth Raksha backend: reads a wallet's approval history, scores risk,
  drafts transactions from natural language *only* against a saved address
  book, and never signs/broadcasts anything (see safety tests).
- Three React + Vite + Tailwind frontends matching the brief's design
  system (hub, Arth Bodh, Arth Raksha), all building cleanly.
- 44 automated tests (plus 4 more that run for real against a live
  Neo4j instance when configured — see below), including the
  safety-critical transaction-drafting tests (unknown recipients
  refused, no private key/signature ever produced, unconfirmed drafts
  can't be handed off).

**Works, but needs something from you to go live:**
- **Real LLM explanations**: set `ANTHROPIC_API_KEY` and the explainer calls
  Claude directly; without it, a deterministic template renderer is used
  (still fully grounded — just less fluent). Both paths are implemented.
- **Full-fidelity ML feature extraction**: see the ML section below —
  works fully today with a free RPC and no key for the model's single
  most important feature, but the remaining ~45 behavioral features need
  a free Etherscan API key to compute for real instead of being
  median-imputed.

**Fully working right now, verified live (added in this round of work):**
- **Real on-chain data, actually tested against real chain data.**
  `Web3WalletReader` (`arth_raksha/backend/wallet_reader.py`) defaults to
  `https://rpc.mevblocker.io` — a free, keyless RPC confirmed live (Sep
  2026) to allow full, unrestricted, topic-only `eth_getLogs` with real
  archive-depth history. Its only real limit, also confirmed live, is
  10,000 blocks per call ("range N exceeds limit of 10000"), which
  `ChunkedLogFetcher` discovers from the provider's own error message and
  paginates around automatically — it doesn't hardcode one provider's
  limit, so it adapts to Infura/Alchemy/your own node too if you pass a
  different `rpc_url`. It also detects and stops cleanly (with an honest
  `archive_limit_reached` flag) when a provider like the default
  publicnode endpoint demands a paid archive tier for older blocks,
  instead of silently truncating results.
  Verified with `pytest tests/test_wallet_reader_live.py -v -s`, which
  hits the real network and asserts against a real, named transaction hash
  (`0xed49697a...`, block 18,000,001) — not a mock. It also passed through
  the actual running FastAPI server: `POST /wallet/connect` with
  `{"live": true, "from_block": 17999000, "to_block": 18001000}` against a
  real wallet returned 435 real on-chain approvals, which `/wallet/{addr}/risk`
  then scored and explained for real, citing the real spender addresses.
  A short-lived (60s) per-request cache avoids re-scanning the chain on
  back-to-back calls. `MockWalletReader` still backs the default
  (`live: false`) path so the app runs fully offline with zero setup.

- **A real, trained ML scam-behavior classifier, blended into risk
  scoring as one more explained signal — never a bare number.** See
  `arth_raksha/ml/` for the full writeup. Short version:
  - Trained on a real, labelled, 4,681-address Ethereum fraud dataset
    (`arth_raksha/ml/data/`, provenance and license caveats in
    `data/SOURCE.md`) — not synthetic data.
  - Two models were trained and honestly compared
    (`arth_raksha/ml/train.py`): logistic regression (precision 0.592,
    recall 0.861 on held-out data) and gradient boosting (precision
    0.989, recall 0.985). Gradient boosting is shipped despite being
    less directly interpretable, because the accuracy gap is too large
    to trade away for a safety signal — see `shipped_model_rationale`
    in `arth_raksha/ml/model/metrics.json` for the exact numbers and
    reasoning.
  - Per-prediction explainability comes from single-feature ablation
    (`arth_raksha/backend/ml_signal.py`): each feature is individually
    reset to its training-median and the real resulting change in
    predicted probability is measured and reported — computed fresh per
    prediction, not a cached global importance.
  - `arth_raksha/backend/wallet_features.py` computes the model's single
    most important feature (`Total_ERC20_tnxs`, by a wide margin — see
    permutation importance in the same metrics.json) for real, for free,
    with no API key, by reusing the same verified `ChunkedLogFetcher`
    from Phase 1 against ERC20 `Transfer` logs. The other ~45 features
    the model expects are median-imputed unless you set
    `ETHERSCAN_API_KEY` (free, from https://etherscan.io/apis), which
    unlocks `compute_features_etherscan()` for the full feature set —
    this project doesn't have one, so full-fidelity extraction is
    implemented but untested live; the RPC-only path is what's verified.
  - Verified end-to-end against a real, unusually hyperactive real
    wallet (231 real approvals): scoring correctly rated its most-used
    spender as low-risk (2.9% probability) with a real, correct
    ablation explanation ("Total_ERC20_tnxs" dominant, matching its very
    high real transfer count). This run also surfaced a real performance
    issue — scoring every distinct spender took over a minute — fixed by
    skipping spenders that already have a clear rule-based signal and
    capping lookups per request (`MAX_ML_LOOKUPS_PER_REQUEST` in
    `risk_engine.py`), with any skipped spender marked honestly via an
    `ml_signal_skipped` evidence item rather than silently dropped.
  - `tests/test_ml_classifier.py` covers the trained model's real
    metrics, the ablation explanation, the rule's threshold behavior, and
    the lookup cap (the last one faked-network for speed and determinism).

- **Neo4j graph layer, live-tested against a real local instance.** See
  `arth_raksha/backend/graph.py`. Schema:
  `(:Wallet {address})-[:APPROVED {event_id, tx_hash, token_address,
  amount, is_unlimited, block_number}]->(:Spender {address, verified,
  is_scam})`, with uniqueness constraints (which double as indexes) on
  `Wallet.address`, `Spender.address`, and the relationship's `event_id`
  — needed so wallets with long histories stay fast to query.
  - No Docker daemon was available in this environment, so instead of
    only writing untested schema code, a real Neo4j 5.24 Community
    server was downloaded and run directly (Java 21 was available) and
    every claim below was verified against it live — not simulated.
    `docker-compose.neo4j.yml` is the documented path for everyone else.
  - `wallet_reader.py`'s `Web3WalletReader.get_history()` takes an
    optional `graph_store` and writes every approval it discovers as a
    real graph edge; `risk_engine.py` reads back the full timeline
    between a wallet and a spender (not just the latest snapshot) and
    writes verification/scam judgments separately, since that's a
    different concern than raw fact recording — see the module
    docstrings in both files for the reasoning.
  - **Two real bugs were found and fixed by testing against the live
    instance instead of trusting the code on paper:** (1) approval
    amounts are uint256 (an "unlimited" approval is `2**256-1`), and
    Neo4j's Bolt protocol only supports 64-bit integers — this silently
    overflowed until amounts were stored as exact decimal strings.
    (2) the relationship's original uniqueness key was `tx_hash` alone,
    which broke the first time a real wallet's transaction turned out to
    be a batch approval emitting two different `Approval` events in one
    tx — the key is now `(tx_hash, token_address, spender_address)`.
  - New signal: `rule_repeated_approval_cycle` in `rules.py` fires when
    the graph shows the same spender approved/revoked more than once —
    verified live against a real wallet where one spender had been
    approved 4 separate times, correctly raising that finding's severity
    from low to medium with the real count cited in the reason text.
  - `tests/test_graph_store.py` runs for real against a configured Neo4j
    instance (skips cleanly, like the live RPC tests, when
    `NEO4J_PASSWORD` isn't set) and covers idempotent writes, timeline
    ordering, aggregate wallet summaries, and the risk_engine
    integration.
- **Batch revoke + transaction simulation preview**, verified live
  against real chain state. See `arth_raksha/backend/revoke.py`:
  `draft_revoke`/`draft_batch_revoke` build real, correct
  `approve(spender, 0)` calldata (the ERC20 selector `0x095ea7b3`,
  independently verified via `Web3.keccak`, not memorized) for one or
  more approvals at once — same non-negotiable rules as the send flow:
  no signing capability exists in the module, and a draft can't reach
  `to_wallet_provider_payload()` before `confirm()`.
  `simulate_revoke`/`simulate_transaction` call `eth_call` +
  `eth_estimate_gas` against **current live chain state** before the
  draft is even returned to the caller, so a revert is visible before
  anyone signs anything — confirmed live with a real 26,422-gas estimate
  for a real revoke against a real wallet's real approval.
  A real bug was found and fixed via that live testing: the batch
  endpoint originally drafted all approvals in one list comprehension,
  so a single malformed address anywhere in the batch returned a bare
  500 for the whole request; it now drafts each independently and
  reports a per-item error without sinking the rest.
  `tests/test_revoke_safety.py` mirrors `test_transaction_safety.py`'s
  pattern for this second signable code path.
- **Client-side wallet signing, wired for real and driven end-to-end in
  a real (headless) browser.** See `arth_raksha/frontend/src/wallet.js`:
  `connectWallet()` and `signAndSendPayload()` are thin wrappers around
  `window.ethereum` via ethers.js v6's `BrowserProvider` —
  `eth_requestAccounts` to connect, `signer.sendTransaction()` to hand
  the backend's exact unsigned payload to the wallet, which is where
  MetaMask's own review-and-sign UI appears and does the actual signing.
  This module is the only place in the frontend that touches a wallet
  provider, and it has no code path that could sign without that prompt.
  - Both `transaction.py` and `revoke.py`'s payloads gained a real
    `value` field (hex wei, e.g. `0.05 ETH` → `0xb1a2bc2ec50000`) —
    the previous `value_note` was human-readable only and literally
    couldn't be used to build a real `eth_sendTransaction` call.
  - The Send and Revoke flows were driven through a real headless
    Chromium via Playwright (no MetaMask extension present, so
    "Connect MetaMask" correctly shows a graceful error instead of
    crashing) — screenshots confirmed the connect screen, the risk
    dashboard with a working Revoke button, the draft/simulate/confirm
    sequence, and the honest "demo mode, no wallet connected" fallback
    that shows the real unsigned payload instead of faking a signature.
  - **Two real bugs were found this way and fixed:** (1) this
    environment's Node (20.13.1) was below what Vite 8's Rolldown-based
    bundler requires, breaking `npm run dev`/`build` for all three
    frontends, not just this one — fixed by pinning to Vite 6 +
    `@vitejs/plugin-react` 4, both rollup-based and needing no native
    binding. (2) `MockWalletReader`'s demo fixture had a malformed spender
    address (39 hex chars, not 40) that had silently been an invalid
    Ethereum address all along — invisible until this phase's revoke
    flow actually checksum-validates spender addresses; fixed to a
    genuine 40-char address.
  - **Still honestly untested**: signing against a real MetaMask
    extension in a real browser — this environment has no browser UI/
    extension to click "confirm" in. The code path is standard,
    minimal ethers.js v6 usage with no custom transaction-building logic
    to hide a bug in, but that's a claim, not a substitute for someone
    actually clicking through it once.
- **Authentication (JWT + API keys) on both backends, with an accurate
  OpenAPI schema.** See `shared_engine/auth.py`, shared by both
  `arth_bodh` and `arth_raksha`: `POST /auth/token` trades a
  server-configured API key for a 1-hour bearer token; every other
  endpoint (except `/health`) requires `Authorization: Bearer <token>`
  via FastAPI's `HTTPBearer` security scheme — used specifically (not a
  raw header check) so `/docs` shows a real "Authorize" button and marks
  every protected endpoint with a lock icon, confirmed live in the
  actual `/openapi.json`. `ARTHDRISHTI_API_KEYS` configures real keys;
  if unset, a single well-known dev key is accepted (loudly logged as
  not for production) so the README's own examples and both demo
  frontends work with zero setup. Both frontends now fetch and cache a
  token transparently (`src/api.js` in each) — verified working
  end-to-end in a real browser after this change, not just assumed.
  `tests/test_auth.py` runs both backends' real FastAPI apps via
  `TestClient` (token issuance, wrong/expired/garbage tokens, protected
  endpoints with and without a valid token) — 16 tests, all passing.
- **Exportable Markdown/PDF safety report, shared by both products.**
  See `shared_engine/report.py`: `GET /wallet/{address}/report` (Arth
  Raksha) and `GET /doc/{doc_id}/report` (Arth Bodh) both accept
  `?format=markdown|pdf` and render from the exact same
  findings/scores/explanations the live risk view uses — a report can
  never disagree with what's on screen, by construction (`_score_and_explain`
  in each backend is the one shared computation both read from).
  - PDF export uses fpdf2 with a real, licensed (OFL) embedded Noto Sans
    Devanagari font (`shared_engine/fonts/`) for genuine Hindi rendering
    — not boxes/mojibake — alongside the PDF's built-in Helvetica for
    English, switched per line based on the actual character range in
    that text. Verified by generating a real PDF with English, Hindi,
    and Hinglish content and extracting the text back out with pypdf to
    confirm it round-trips exactly (`tests/test_report.py`) — including
    against a real running server with a real live wallet's real
    findings, not just the test suite.
  - A real fpdf2 API bug was hit and fixed during this: `multi_cell()`
    in the installed version (2.8.8) leaves the cursor at the right
    margin after each call instead of wrapping to the next line, which
    silently broke every call after the first ("not enough horizontal
    space") until fixed with the library's `new_x=XPos.LMARGIN,
    new_y=YPos.NEXT` parameters.
- **Testing and engineering practices — expanded coverage, rate-limiting,
  and a flaky test found and fixed for real.** 75 tests total (71
  always-on + 4 Neo4j-gated), real coverage 77% → 83% on
  `shared_engine/` + both backends after this pass (`pytest --cov`,
  numbers are measured, not asserted): closed the cheapest honest gaps
  by testing previously dead code with mocking rather than skipping it —
  the LLM explainer path (`tests/test_explainer_llm_path.py`, a fake
  Anthropic client, no network), the Etherscan feature-extractor
  (`tests/test_wallet_features_etherscan.py`, mocked `requests.get`,
  verifies the real aggregation math), and Arth Bodh's scoring rules
  in isolation (`tests/test_arth_bodh_rules.py`).
  - `tests/test_api_integration.py` adds HTTP-level (not just dataclass-level)
    checks for the two non-negotiable signing rules: a full send and a
    full revoke flow through the real FastAPI apps, scanning every
    response for private-key/signature-shaped substrings, plus a
    structural scan of the entire OpenAPI schema for the same. This
    sits alongside, not instead of, `test_transaction_safety.py` and
    `test_revoke_safety.py`.
  - `arth_raksha/backend/wallet_reader.py` gained a real `RateLimiter`
    (not just the existing 60s cache) enforcing a minimum interval
    between every RPC call this backend makes — added after the Phase 2
    live testing that generated bursts of dozens of rapid calls against
    the shared free RPC. **A real, subtle bug was found writing its
    test**: the limiter used `0.0` as its "never called yet" sentinel,
    which is indistinguishable from a real first call at time zero on a
    mocked/fake clock (harmless on a real monotonic clock, which never
    returns exactly 0.0, but still a latent correctness bug) — fixed to
    use `None`.
  - **A genuinely flaky test was found and fixed, not just noted**: the
    rate limiter's first test version used real `time.sleep`/`time.monotonic`
    with tens-of-milliseconds margins and intermittently failed under
    full-suite load (scheduler jitter), while always passing in
    isolation — replaced with a fully deterministic fake clock so the
    assertions are exact instead of "probably long enough."
- **UI/UX: the transaction confirmation screen redesigned per the
  platform's own design mandate, plus real violations of that mandate
  found and fixed on existing screens.** The brief requires a written
  design plan and self-critique before any new screen — this hadn't
  been done for the revoke UI and MetaMask button added in Phase 5, so
  it was done retroactively here alongside redesigning the confirmation
  screen itself (the platform's explicitly highest-stakes screen):
  - **Plan**: no new colors (reusing the established `guardian`/`harbor`/
    `deepink`/`amber`/`signal`/`mist` palette — a new palette for one
    screen would fragment identity, not add craft); layout separated into
    three zones a user's eye moves through — a plain-language sentence
    stating what's about to happen, a visually distinct monospace "hard
    facts" block for cross-checking the exact address/amount, and a
    signing checkpoint set apart by an actual `border-double` rule (a
    real CSS double border, no icon/image) — echoing the ledger/seal
    visual language the brand already draws on, marking that zone as a
    deliberate checkpoint rather than the next button in a stack.
  - **Self-critique, honestly**: a plain card with a data table and a
    "Confirm" button is what any wallet UI does; the genericness lives
    in *not* separating the human claim from the verifiable fact, so
    that's the specific thing this redesign targets. Screenshotted and
    verified at both 390×844 (mobile, the primary target) and desktop
    via a real headless browser, console-clean at both.
  - **Three real, pre-existing violations of the platform's own named
    "do not build anything that looks AI-generated" list were found and
    fixed**: a tracked-out uppercase eyebrow label directly above the
    confirmation heading ("REVIEW CAREFULLY BEFORE SIGNING" — the exact
    banned pattern, named as such in the brief), an arrow appended to a
    button label ("Send crypto with a saved contact →"), and meta text
    joined with a middle dot ("HIGH · SCORE 6.5"). Also fixed one
    introduced in Phase 5 (a tracked-out uppercase divider label). All
    four are now plain sentence-case text.
- Real-time alerts and hosted deployment — still pending.

## Project layout

```
shared_engine/        the trust engine both products import
arth_bodh/backend/    FastAPI app — statement parsing, scoring, chat
arth_bodh/frontend/   React app
arth_raksha/backend/  FastAPI app — wallet reading, risk scoring, sending
arth_raksha/frontend/ React app
hub/frontend/         platform landing page, routes to both products
tests/                pytest suite (run from repo root)
```

## Running it

Requires Python 3.11+, Node 18+.

```bash
# 1. Python deps (from repo root)
pip install -r requirements.txt

# 2. Run the tests
pytest tests/ -v
# ...or with a real coverage report (shows the honest numbers, not just pass/fail):
pytest tests/ --cov=shared_engine --cov=arth_raksha/backend --cov=arth_bodh/backend --cov-report=term-missing

# 3. Start both backends (separate terminals)
uvicorn arth_bodh.backend.main:app --reload --port 8001
uvicorn arth_raksha.backend.main:app --reload --port 8002

# 4. Start all three frontends (separate terminals)
cd arth_bodh/frontend && npm install && npm run dev     # :5173
cd arth_raksha/frontend && npm install && npm run dev    # :5174 (set a different port if it clashes)
cd hub/frontend && npm install && npm run dev            # :5175

# 5. Open the hub in your browser and click through to either product.
```
All three frontends pin Vite 6 + `@vitejs/plugin-react` 4 (downgraded
from 8/6 during this round of work) — Vite 8's Rolldown-based bundler
needs a native binding this environment's Node (20.13.1) doesn't meet
the version floor for, which broke `npm run dev`/`build` for all three
until this fix; Vite 6 is Rollup-based and needs no native binding.

Optional: `export ANTHROPIC_API_KEY=sk-...` before starting the backends to
get real LLM-generated explanations instead of the template fallback.

### Auth

Both backends require a bearer token on every endpoint except `/health`.
With zero setup, both demo frontends and these curl examples work using
the built-in dev key:
```bash
curl -X POST localhost:8002/auth/token -H "Content-Type: application/json" \
  -d '{"api_key": "dev-local-key-not-for-production"}'
# -> {"access_token": "...", "token_type": "bearer", "expires_in": 3600}
curl localhost:8002/wallet/0x.../risk -H "Authorization: Bearer <token>"
```
For anything beyond local dev, set real keys before starting the
backends (and match `VITE_API_KEY` in each frontend's `.env` to one of
them):
```bash
export ARTHDRISHTI_API_KEYS=your-real-key-1,your-real-key-2
export JWT_SECRET=$(openssl rand -hex 32)   # stable across restarts/workers
```
See `/docs` on either backend for the full interactive schema, including
the "Authorize" button — the auth requirement is a real part of the
OpenAPI spec, not just documented separately from it.

For Arth Raksha with real chain data instead of the mock fixture, call
`/wallet/connect` with `"live": true`:
```json
{ "address": "0xYourWallet", "live": true }
```
This defaults to the free `rpc.mevblocker.io` endpoint and scans the last
~50,000 blocks (~1 week). To scan a specific historical range (e.g. to
find an old approval), pass explicit `from_block`/`to_block`:
```json
{ "address": "0xYourWallet", "live": true, "from_block": 17999000, "to_block": 18001000 }
```
Or point at your own node/Infura/Alchemy key with `"rpc_url": "https://..."`.
The response tells you exactly what was scanned (`chain_head_block`,
`scanned_from_block`, `scanned_to_block`, `archive_limit_reached`) so a
partial scan is always visible, never silent. See
`tests/test_wallet_reader_live.py` for a live, network-verified example
against a real wallet and a real transaction hash.

### The ML scam classifier

The trained model ships in the repo (`arth_raksha/ml/model/`), so nothing
extra is needed to use it — `GET /wallet/{address}/risk` on a live wallet
already blends it in automatically. To retrain it (e.g. after updating the
dataset) or inspect its real evaluation numbers:
```bash
python -m arth_raksha.ml.train
cat arth_raksha/ml/model/metrics.json
```
By default, only its single most important feature (`Total_ERC20_tnxs`) is
computed from real chain data (free, no key — see
`arth_raksha/backend/wallet_features.py`); everything else is
median-imputed, and every response says exactly how many of the ~48
features were real vs. imputed (`ml_scam_probability`'s evidence
`raw_context`). For the full feature set computed for real, set:
```bash
export ETHERSCAN_API_KEY=your_free_key   # https://etherscan.io/apis
```
This project doesn't have a key configured, so that path is implemented
and documented but not verified live — the RPC-only path is what's been
tested against real chain data.

### Batch revoke + simulation

```json
POST /revoke/draft
{
  "wallet_address": "0xYourWallet",
  "approvals": [
    { "token_address": "0x...", "spender_address": "0x..." },
    { "token_address": "0x...", "spender_address": "0x..." }
  ]
}
```
Returns one draft per approval, each with a real `simulated_outcome` if
the wallet was connected with `"live": true`. Confirm and get the
wallet-provider payload for each with `POST /revoke/{draft_id}/confirm`
— same pattern as `/send/{draft_id}/confirm`, never signing anything here.

### The Neo4j graph layer

```bash
docker compose -f docker-compose.neo4j.yml up -d
export NEO4J_PASSWORD=arthdrishti_dev_password   # matches the compose file
```
With `NEO4J_PASSWORD` set, `/wallet/connect` (with `"live": true`) and
`/wallet/{address}/risk` automatically write to and read from the graph —
no other config needed. Without it, everything works exactly as before;
the graph is purely additive. Browse the graph directly at
http://localhost:7474 (`MATCH (w:Wallet)-[r:APPROVED]->(s:Spender) RETURN
w, r, s`) or run `pytest tests/test_graph_store.py -v` to verify your
instance end-to-end.

### Exportable safety report

```bash
curl "localhost:8002/wallet/0x.../report" -H "Authorization: Bearer <token>"
curl "localhost:8002/wallet/0x.../report?format=pdf" -H "Authorization: Bearer <token>" -o report.pdf
curl "localhost:8001/doc/<doc_id>/report?format=pdf" -H "Authorization: Bearer <token>" -o report.pdf
```
Both are the user's own copy for their own records — grounded in exactly
the same findings the live view shows, nothing more.

## The non-negotiable rules, and where they're enforced

| Rule (from the brief) | Enforced in |
|---|---|
| Never invent a figure not backed by real evidence | `shared_engine/explainer.py` refuses to explain a Finding with no Evidence; every explanation includes citations |
| Arth Raksha only assesses the owner's own wallet | Single-address API surface throughout `arth_raksha/backend/` — there's no endpoint that accepts or compares a second party's wallet |
| AI never holds keys, never signs/broadcasts | `arth_raksha/backend/transaction.py` — no private-key parameter exists anywhere in the module; `to_wallet_provider_payload()` is the only exit point and contains no signature |
| Recipient addresses only from the user's own saved address book | `transaction.py::draft_transaction` raises `UnknownRecipientError` for any name not already in `AddressBook`; see `tests/test_transaction_safety.py` |

Run `pytest tests/test_transaction_safety.py -v` any time to re-verify these
hold after a change.
