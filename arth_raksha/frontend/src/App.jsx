import { useState, useEffect } from "react";
import { isWalletAvailable, connectWallet, signAndSendPayload } from "./wallet";
import { apiFetch } from "./api";

const SEVERITY_RING = {
  info: "border-mist/30",
  low: "border-amber/40",
  medium: "border-amber",
  high: "border-signal",
  critical: "border-signal",
};

function ConnectScreen({ onConnect }) {
  const [address, setAddress] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [live, setLive] = useState(false);

  async function connectBackend(addr, isLive) {
    setLoading(true);
    setError(null);
    try {
      const res = await apiFetch(`/wallet/connect`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ address: addr || "0xDemoWallet", live: isLive }),
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      onConnect(data.address, isLive);
    } catch (e) {
      setError("Could not reach the Arth Raksha API. Is the backend running on :8002?");
    } finally {
      setLoading(false);
    }
  }

  async function handleMetaMask() {
    setError(null);
    try {
      const { address: realAddress } = await connectWallet();
      setLive(true);
      await connectBackend(realAddress, true);
    } catch (e) {
      setError(e.message);
    }
  }

  return (
    <div className="max-w-md mx-auto mt-16 px-6 text-center">
      <h1 className="font-serif text-3xl text-guardian mb-2">Arth Raksha</h1>
      <p className="text-mist mb-8">अर्थ रक्षा — a calm, honest look at your own wallet's risk. Nothing here is about anyone but you.</p>

      <button
        onClick={handleMetaMask}
        disabled={loading}
        className="w-full bg-guardian text-white py-3 font-medium disabled:opacity-40 mb-3"
      >
        {loading ? "Connecting..." : "Connect MetaMask"}
      </button>
      <p className="text-xs text-mist mb-6">
        Recommended — connecting your own wallet extension proves you actually control this
        address. Arth Raksha only ever reads and reports on the wallet you connect.
      </p>

      <div className="flex items-center gap-3 mb-6">
        <div className="flex-1 h-px bg-mist/20" />
        <span className="text-xs text-mist">or a view-only demo</span>
        <div className="flex-1 h-px bg-mist/20" />
      </div>

      <input
        value={address}
        onChange={(e) => setAddress(e.target.value)}
        placeholder="Any wallet address, or leave blank"
        className="w-full border border-mist/40 px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-guardian mb-3"
      />
      <button
        onClick={() => connectBackend(address, false)}
        disabled={loading}
        className="w-full border border-guardian text-guardian py-3 font-medium disabled:opacity-40"
      >
        {loading ? "Connecting..." : "View mock demo data"}
      </button>
      {error && <p className="text-signal text-sm mt-3">{error}</p>}
      <p className="text-xs text-mist mt-6">
        Demo mode reads a small mock wallet history so this runs without any blockchain API key.
        Connecting MetaMask reads real on-chain data and lets you actually sign revokes/sends.
      </p>
    </div>
  );
}

function ApprovalFinding({ f, onRevoke, revokeState }) {
  const evidence = Object.fromEntries((f.evidence || []).map((e) => [e.label, e.value]));
  const state = revokeState || {};

  return (
    <div className={`border rounded-none border-l-4 p-4 mb-3 bg-white ${SEVERITY_RING[f.severity] || SEVERITY_RING.info}`}>
      <div className="flex justify-between items-baseline">
        <h3 className="font-serif text-lg">Token approval</h3>
        <span className="text-xs text-mist">{f.severity} risk, score {f.score}</span>
      </div>
      <p className="text-sm mt-2 text-deepink">{f.explanation}</p>
      {f.reasons.length > 0 && (
        <ul className="mt-2 text-sm text-mist space-y-0.5">
          {f.reasons.map((r, i) => <li key={i}>· {r}</li>)}
        </ul>
      )}
      {f.suggested_action && (
        <div className="mt-3 border-t border-mist/20 pt-2">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-signal">{f.suggested_action}</span>
            {state.status !== "signed" && state.status !== "demo" && (
              <button
                onClick={() => onRevoke(evidence.token, evidence.spender)}
                disabled={state.status === "drafting" || state.status === "signing"}
                className="text-sm bg-deepink text-white px-3 py-1 disabled:opacity-40"
              >
                {state.status === "drafting" ? "Simulating..." : state.status === "signing" ? "Waiting for wallet..." : "Revoke"}
              </button>
            )}
          </div>
          {state.status === "drafted" && (
            <div className="mt-3 border-4 border-double border-guardian p-3">
              <p className="text-xs text-deepink mb-3">
                {state.simulated_outcome || "Simulation unavailable (connect live to preview outcomes)."}
                {" "}You will sign this yourself, in your own wallet.
              </p>
              <button onClick={state.onConfirm} className="w-full bg-guardian text-white py-2 text-sm font-medium">
                Confirm and continue to my wallet
              </button>
            </div>
          )}
          {state.status === "signed" && (
            <p className="mt-2 text-xs text-guardian break-all">
              Sent for signing — tx hash: {state.txHash}
            </p>
          )}
          {state.status === "demo" && (
            <div className="mt-2 text-xs bg-mist/10 border-l-4 border-mist px-3 py-2">
              <p className="text-deepink mb-2">
                Demo mode — no wallet connected to sign with. This is the exact unsigned
                payload that would be handed to your wallet; nothing was sent.
              </p>
              <pre className="bg-deepink text-white text-xs p-3 overflow-x-auto whitespace-pre-wrap break-all">
                {JSON.stringify(state.payload, null, 2)}
              </pre>
            </div>
          )}
          {state.status === "error" && (
            <p className="mt-2 text-xs text-signal break-words">{state.error}</p>
          )}
        </div>
      )}
    </div>
  );
}

function RiskDashboard({ address, live, onGoToSend }) {
  const [risk, setRisk] = useState(null);
  const [loading, setLoading] = useState(true);
  const [revokeStates, setRevokeStates] = useState({}); // keyed by `${token}:${spender}`

  useEffect(() => {
    apiFetch(`/wallet/${address}/risk`)
      .then((r) => r.json())
      .then((data) => { setRisk(data); setLoading(false); });
  }, []);

  function setState(key, patch) {
    setRevokeStates((prev) => ({ ...prev, [key]: { ...prev[key], ...patch } }));
  }

  async function handleRevoke(token, spender) {
    const key = `${token}:${spender}`;
    setState(key, { status: "drafting" });
    try {
      const res = await apiFetch(`/revoke/draft`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ wallet_address: address, approvals: [{ token_address: token, spender_address: spender }] }),
      });
      const data = await res.json();
      const item = data.drafts[0];
      if (item.error) {
        setState(key, { status: "error", error: item.error });
        return;
      }
      setState(key, {
        status: "drafted",
        draftId: item.draft_id,
        simulated_outcome: item.simulated_outcome,
        onConfirm: () => handleConfirmRevoke(key, item.draft_id),
      });
    } catch (e) {
      setState(key, { status: "error", error: "Could not reach the Arth Raksha API." });
    }
  }

  async function handleConfirmRevoke(key, draftId) {
    setState(key, { status: "signing" });
    try {
      const res = await apiFetch(`/revoke/${draftId}/confirm`, { method: "POST" });
      const payload = await res.json();
      if (!live || !isWalletAvailable()) {
        // View-only / demo mode: never fake a signature — show the exact
        // unsigned payload instead of pretending it was sent.
        setState(key, { status: "demo", payload });
        return;
      }
      const txHash = await signAndSendPayload(payload);
      setState(key, { status: "signed", txHash });
    } catch (e) {
      setState(key, { status: "error", error: e.message || "Signing failed or was rejected." });
    }
  }

  if (loading) return <p className="text-center mt-16 text-mist">Reading your wallet's history...</p>;
  if (!risk) return null;

  return (
    <div className="max-w-2xl mx-auto px-6 py-8">
      <header className="mb-6">
        <h1 className="font-serif text-2xl text-guardian">Your wallet safety report</h1>
        <p className="text-sm text-mist break-all">{address}</p>
      </header>

      <div className="bg-white border border-mist/20 p-5 mb-6">
        <p className="text-sm text-mist">Overall risk signal</p>
        <p className="font-serif text-3xl text-guardian">{risk.overall_score}</p>
        <p className="text-xs text-mist mt-1">Higher means more worth reviewing — not a verdict, just a starting point.</p>
      </div>

      <h2 className="font-serif text-xl mb-3">Approvals on your wallet</h2>
      {risk.findings.length === 0 && <p className="text-mist text-sm">No approvals found for this wallet.</p>}
      {risk.findings.map((f) => {
        const evidence = Object.fromEntries((f.evidence || []).map((e) => [e.label, e.value]));
        const key = `${evidence.token}:${evidence.spender}`;
        return <ApprovalFinding key={f.finding_id} f={f} onRevoke={handleRevoke} revokeState={revokeStates[key]} />;
      })}

      <button
        onClick={onGoToSend}
        className="w-full mt-6 bg-guardian text-white py-3 font-medium"
      >
        Send crypto with a saved contact
      </button>
    </div>
  );
}

function shortAddress(addr) {
  return addr && addr.length > 14 ? `${addr.slice(0, 8)}…${addr.slice(-6)}` : addr;
}

function SendFlow({ address, live, onBack }) {
  const [step, setStep] = useState("contact"); // contact -> request -> confirm -> done
  const [contacts, setContacts] = useState([]);
  const [contactsLoading, setContactsLoading] = useState(true);
  const [showAddForm, setShowAddForm] = useState(false);
  const [contactName, setContactName] = useState("");
  const [contactAddress, setContactAddress] = useState("");
  const [request, setRequest] = useState("");
  const [draft, setDraft] = useState(null);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const [txHash, setTxHash] = useState(null);
  const [signError, setSignError] = useState(null);

  useEffect(() => {
    apiFetch(`/address-book/${address}`)
      .then((r) => r.json())
      .then((data) => {
        setContacts(data.contacts || []);
        setShowAddForm((data.contacts || []).length === 0);
      })
      .finally(() => setContactsLoading(false));
  }, []);

  function selectContact(contact) {
    setRequest(`send 0.05 ETH to ${contact.name}`);
    setStep("request");
  }

  // Any backend error response is treated as plain text first, since a
  // raw unhandled server exception (not an HTTPException) doesn't come
  // back as JSON — assuming it always would meant a real backend bug
  // here surfaced as nothing happening at all on click, instead of a
  // visible error. res.clone() lets us try JSON first without consuming
  // the body if that fails.
  async function _errorMessage(res) {
    try {
      const body = await res.clone().json();
      return body.detail || JSON.stringify(body);
    } catch {
      return (await res.text()) || `Request failed (${res.status})`;
    }
  }

  async function saveContact() {
    setError(null);
    try {
      const res = await apiFetch(`/address-book`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ wallet_address: address, name: contactName, address: contactAddress }),
      });
      if (!res.ok) {
        setError(await _errorMessage(res));
        return;
      }
      const savedContact = { name: contactName, address: contactAddress, chain: "ethereum" };
      setContacts((prev) => [...prev, savedContact]);
      setRequest(`send 0.05 ETH to ${contactName}`);
      setStep("request");
    } catch (e) {
      setError(e.message || "Could not reach the Arth Raksha API.");
    }
  }

  async function makeDraft() {
    setError(null);
    try {
      const res = await apiFetch(`/send/draft`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ wallet_address: address, request }),
      });
      if (!res.ok) {
        setError(await _errorMessage(res));
        return;
      }
      const data = await res.json();
      setDraft(data);
      setStep("confirm");
    } catch (e) {
      setError(e.message || "Could not reach the Arth Raksha API.");
    }
  }

  async function confirm() {
    const res = await apiFetch(`/send/${draft.draft_id}/confirm`, { method: "POST" });
    if (!res.ok) {
      setError(await _errorMessage(res));
      return;
    }
    const payload = await res.json();
    setResult(payload);
    setStep("done");

    if (!live || !isWalletAvailable()) return; // demo mode: show the payload only, never fake a signature

    try {
      const hash = await signAndSendPayload(payload);
      setTxHash(hash);
    } catch (e) {
      setSignError(e.message || "Signing failed or was rejected in your wallet.");
    }
  }

  return (
    <div className="max-w-md mx-auto px-6 py-8">
      <button onClick={onBack} className="text-sm text-mist underline mb-6">← Back to safety report</button>

      {step === "contact" && (
        <div>
          <h2 className="font-serif text-xl mb-3">Who would you like to send to?</h2>
          <p className="text-sm text-mist mb-4">
            Arth Raksha never guesses an address. You save who you trust; the AI only ever sends here.
          </p>

          {contactsLoading && <p className="text-sm text-mist">Loading your saved contacts…</p>}

          {!contactsLoading && !showAddForm && (
            <div className="mb-4">
              {contacts.map((c) => (
                <button
                  key={c.name}
                  onClick={() => selectContact(c)}
                  className="w-full text-left border border-mist/30 bg-white px-4 py-3 mb-2 hover:border-guardian"
                >
                  <span className="block font-medium text-deepink">{c.name}</span>
                  <span className="block text-xs text-mist font-mono">{shortAddress(c.address)}</span>
                </button>
              ))}
              <button onClick={() => setShowAddForm(true)} className="text-sm text-guardian underline mt-1">
                Save someone new
              </button>
            </div>
          )}

          {!contactsLoading && showAddForm && (
            <div>
              <label className="text-sm block mb-1">Name</label>
              <input value={contactName} onChange={(e) => setContactName(e.target.value)}
                className="w-full border border-mist/40 px-3 py-2 mb-3 text-sm bg-white" />
              <label className="text-sm block mb-1">Address</label>
              <input value={contactAddress} onChange={(e) => setContactAddress(e.target.value)}
                className="w-full border border-mist/40 px-3 py-2 mb-4 text-sm bg-white font-mono" />
              {error && <p className="text-signal text-sm mb-3">{error}</p>}
              <button onClick={saveContact} className="w-full bg-guardian text-white py-3 font-medium mb-2">
                Save contact
              </button>
              {contacts.length > 0 && (
                <button onClick={() => setShowAddForm(false)} className="text-sm text-mist underline">
                  Choose from my saved contacts instead
                </button>
              )}
            </div>
          )}
        </div>
      )}

      {step === "request" && (
        <div>
          <h2 className="font-serif text-xl mb-3">What would you like to send?</h2>
          <input value={request} onChange={(e) => setRequest(e.target.value)}
            className="w-full border border-mist/40 px-3 py-2 mb-3 text-sm bg-white"
            placeholder="e.g. send 0.05 ETH to Saniya" />
          {error && <p className="text-signal text-sm mb-3">{error}</p>}
          <button onClick={makeDraft} className="w-full bg-guardian text-white py-3 font-medium">Draft transaction</button>
        </div>
      )}

      {step === "confirm" && draft && (
        <div>
          {/* Zone 1: what's about to happen, stated as a sentence a person
              would actually say, not a form label. */}
          <p className="font-serif text-2xl text-deepink leading-snug mb-5">
            You're about to send <span className="text-guardian">{draft.amount} {draft.token}</span> to{" "}
            {draft.recipient_name}.
          </p>

          {/* Zone 2: the hard, verifiable facts — visually distinct from
              the sentence above so the two can be cross-checked against
              each other, not read as one blended claim. */}
          <dl className="border border-mist/30 bg-harbor text-sm font-mono p-4 space-y-3 mb-4">
            <div className="flex flex-col sm:flex-row sm:justify-between gap-1 sm:gap-3">
              <dt className="text-mist">to</dt><dd className="break-all sm:text-right">{draft.recipient_address}</dd>
            </div>
            <div className="flex justify-between gap-3"><dt className="text-mist">amount</dt><dd>{draft.amount} {draft.token}</dd></div>
            <div className="flex justify-between gap-3"><dt className="text-mist">network</dt><dd>{draft.chain}</dd></div>
          </dl>

          {draft.warnings.map((w, i) => (
            <p key={i} className="text-amber text-sm mb-4 bg-amber/10 border-l-4 border-amber px-3 py-2">{w}</p>
          ))}

          {/* Zone 3: the signing checkpoint, set apart with an actual
              double rule — a deliberate "stamped box" rather than just
              the next button in a stack. */}
          <div className="border-4 border-double border-guardian p-4">
            <p className="text-sm text-deepink mb-4">
              Arth Raksha drafted this from your saved contact. It cannot sign or send on its own —
              you will sign this yourself, in your own wallet, after confirming here.
            </p>
            <button onClick={confirm} className="w-full bg-guardian text-white py-3 font-medium">
              Confirm and continue to my wallet
            </button>
          </div>
          {error && <p className="text-signal text-sm mt-3">{error}</p>}
        </div>
      )}

      {step === "done" && result && (
        <div>
          <h2 className="font-serif text-xl text-guardian mb-3">
            {txHash ? "Signed and submitted" : live && isWalletAvailable() ? "Waiting for your wallet..." : "Ready for your signature"}
          </h2>
          <p className="text-sm text-mist mb-4">
            {live && isWalletAvailable()
              ? "This payload was handed to your connected wallet for you to review and sign. Arth Raksha never held a key and never signed or broadcast anything itself — your wallet did."
              : "Demo mode — no wallet connected. This is the exact unsigned payload that would be handed to your wallet for you to sign; nothing was sent."}
          </p>
          {txHash && (
            <p className="text-sm text-guardian break-all mb-3">Transaction hash: {txHash}</p>
          )}
          {signError && (
            <p className="text-sm text-signal mb-3">{signError}</p>
          )}
          <pre className="bg-deepink text-white text-xs p-4 overflow-auto">{JSON.stringify(result, null, 2)}</pre>
        </div>
      )}
    </div>
  );
}

export default function App() {
  const [address, setAddress] = useState(null);
  const [live, setLive] = useState(false);
  const [view, setView] = useState("dashboard");

  if (!address) {
    return <ConnectScreen onConnect={(addr, isLive) => { setAddress(addr); setLive(isLive); }} />;
  }

  return (
    <div className="min-h-screen bg-harbor font-sans">
      {view === "dashboard" && (
        <RiskDashboard address={address} live={live} onGoToSend={() => setView("send")} />
      )}
      {view === "send" && (
        <SendFlow address={address} live={live} onBack={() => setView("dashboard")} />
      )}
    </div>
  );
}
