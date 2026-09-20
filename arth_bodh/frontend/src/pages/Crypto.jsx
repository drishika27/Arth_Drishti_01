import { useEffect, useState } from 'react';
import { api } from '../api';
import { requestAccount, signText } from '../wallet';
import { Card, Pill, BarChart, Busy, ErrorNote, money, CATEGORY_COLORS } from '../ui';

const short = (a) => (a ? `${a.slice(0, 6)}…${a.slice(-4)}` : '');
const change = (v) => (v == null ? '—' : `${v > 0 ? '+' : ''}${v}%`);
const tone = (v) => (v == null ? '' : v >= 0 ? 'positive' : 'negative');
const num = (v) => Number(v).toLocaleString('en-IN', { maximumFractionDigits: v < 1 ? 6 : 4 });
const isLive = (c) => c?.data_mode === 'live';

/** Wallet switcher + "connect my wallet" (signature, keyless) + "watch an address" (read-only). */
function WalletBar({ crypto, wallets, walletId, setWalletId, refreshWallets, reload }) {
  const [address, setAddress] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function run(fn) {
    setBusy(true); setError('');
    try { await fn(); } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  const connect = () => run(async () => {
    const addr = await requestAccount();
    const ch = await api.post('/auth/wallet/nonce', { address: addr, domain: window.location.host });
    const signature = await signText(addr, ch.message);
    const w = await api.post('/crypto/wallets/link', { address: addr, signature, token: ch.token });
    await refreshWallets(); setWalletId(w.id);
  });
  const watch = (e) => { e.preventDefault(); return run(async () => {
    const w = await api.post('/crypto/wallets/watch', { address: address.trim() });
    setAddress(''); await refreshWallets(); setWalletId(w.id);
  }); };
  const remove = () => run(async () => {
    if (!window.confirm('Stop tracking this wallet? (Nothing on the blockchain changes.)')) return;
    await api.del(`/crypto/wallets/${walletId || crypto.wallet_id}`); setWalletId(null); await refreshWallets();
  });

  const current = walletId || crypto?.wallet_id || '';
  return <>
    <div className="wallet-bar">
      {wallets.length > 0 && <select value={current} onChange={(e) => setWalletId(e.target.value)}>
        {wallets.map((w) => <option key={w.id} value={w.id}>{w.demo ? 'Sample wallet' : `${w.label || 'Wallet'} · ${short(w.address)}`}{w.verified ? ' ✓' : ''}</option>)}
      </select>}
      <button className="secondary" disabled={busy} onClick={connect}>◇ Connect my wallet</button>
      <form onSubmit={watch} style={{ display: 'contents' }}>
        <input value={address} onChange={(e) => setAddress(e.target.value)} placeholder="…or paste any Ethereum address to watch (read-only)" spellCheck={false} />
        <button className="secondary" disabled={busy || !address.trim()}>Watch</button>
      </form>
      {crypto && <button className="link" disabled={busy} onClick={reload}>↻ Refresh</button>}
      {crypto && wallets.some((w) => w.id === current && !w.demo) && <button className="link" disabled={busy} onClick={remove}>Remove</button>}
    </div>
    <ErrorNote error={error} />
  </>;
}

function Frame({ p, title, text, children }) {
  const { crypto, state } = p;
  return <>
    <div className="section-intro"><Pill tone="green">Arth Raksha</Pill><h2>{title}</h2><p>{text}</p></div>
    <WalletBar {...p} />
    <ErrorNote error={state.error} onRetry={p.reload} />
    {state.loading && !crypto ? <Busy text="Reading the blockchain… large wallets can take up to a minute the first time." />
      : crypto ? children(crypto)
        : !state.error && <Card><div className="empty">No wallet yet. Tap “Connect my wallet”, or paste any Ethereum address above to see its real balances and transactions.</div></Card>}
    {crypto && <p className="sub-note">{crypto.data_mode === 'demo' ? crypto.disclaimer : `Data: ${crypto.sources.balances_and_history} · prices: ${crypto.sources.prices} · updated ${new Date(crypto.fetched_at).toLocaleTimeString()}`}</p>}
  </>;
}

const Notes = ({ c }) => (c.notes || []).map((n) => <div className="notice" key={n}>{n}</div>);

export function Wallet(p) {
  const [copied, setCopied] = useState(false);
  return <Frame p={p} title="Your wallet, in view." text="Connect your own wallet, or watch any public address. Arth Raksha never asks for seed phrases or private keys.">{(c) => {
    const w = c.wallet;
    const copy = () => { navigator.clipboard?.writeText(w.address); setCopied(true); setTimeout(() => setCopied(false), 1500); };
    const badge = c.data_mode === 'demo' ? 'Sample wallet' : w.verified ? 'Connected · verified owner' : 'Watching · read-only';
    return <>
      <div className="wallet-hero"><div><Pill tone="green">{badge}</Pill><h2 title={w.address}>{w.ens || short(w.address)}</h2><p className="mono">{w.address}</p><p>{w.network}</p></div><button className="secondary" onClick={copy}>{copied ? 'Copied ✓' : 'Copy address'}</button></div>
      <Notes c={c} />
      <div className="metric-grid three">
        <Card><span>Total portfolio</span><strong>{c.total_value_inr != null ? money(c.total_value_inr, p.currency) : '—'}</strong><small className={tone(c.change_24h_pct)}>{c.change_24h_pct != null ? `${change(c.change_24h_pct)} today` : 'Price data unavailable'}</small></Card>
        <Card><span>Assets</span><strong>{c.assets.length}</strong><small>{c.transactions.length} recent transactions</small></Card>
        <Card><span>Security</span><strong className={c.security.risk_label === 'Flagged' ? 'negative' : ''}>{c.security.risk_label}</strong><small>{c.security.checks.filter((x) => !x.ok).length} item(s) to review</small></Card>
      </div>
      <Card><div className="card-title"><div><span>Safety boundary</span><h3>What Arth Raksha never asks for</h3></div></div><div className="safe-grid"><div>✓ Seed phrases</div><div>✓ Private keys</div><div>✓ Recovery phrases</div><div>✓ Signing secrets</div></div></Card>
    </>;
  }}</Frame>;
}

function AssetTable({ rows, currency, counted }) {
  return <div className="table"><div className="thead"><span>Asset</span><span>Balance</span><span>Price</span><span>Value</span><span>24h</span></div>
    {rows.map((a) => <div className="trow" key={a.contract || a.symbol}><div><strong>{a.symbol}</strong><small>{a.name}</small></div><span>{num(a.amount)}</span><span>{a.price_inr != null ? money(a.price_inr, currency) : '—'}</span><b>{a.value_inr != null ? money(a.value_inr, currency) : '—'}</b><span className={tone(a.change_24h_pct)}>{change(a.change_24h_pct)}</span></div>)}
    {!rows.length && counted && <div className="empty">No assets found for this address.</div>}
  </div>;
}

export function Assets(p) {
  return <Frame p={p} title="Your digital assets at a glance." text="Balances read from the chain; prices from a market-data provider.">{(c) => <>
    <Notes c={c} />
    <Card><AssetTable rows={c.assets} currency={p.currency} counted /></Card>
    {c.other_assets?.length > 0 && <Card className="review"><div className="card-title"><div><span>Not counted in your total</span><h3>Other tokens</h3></div></div><p className="sub-note" style={{ margin: '0 0 10px' }}>{c.other_assets_note}</p><AssetTable rows={c.other_assets} currency={p.currency} /></Card>}
    {c.hidden_unverified_tokens > 0 && <p className="sub-note">{c.hidden_unverified_tokens} unrecognised tokens were hidden — these are usually airdrop spam. Don’t interact with them.</p>}
  </>}</Frame>;
}

export function Transactions(p) {
  const [search, setSearch] = useState('');
  return <Frame p={p} title="Transactions with context." text="Your real on-chain activity — status, counterparties and fees.">{(c) => {
    const rows = c.transactions.filter((t) => Object.values(t).join(' ').toLowerCase().includes(search.toLowerCase()));
    return <>
      <div className="toolbar"><input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search hash, asset, address…" /></div>
      <Card><div className="table"><div className="thead"><span>Transaction</span><span>Asset</span><span>Value today</span><span>Status</span><span>Network</span></div>
        {rows.map((t) => <div className="trow" key={t.id || t.hash}>
          <div><strong>{t.type} · {t.explorer_url ? <a className="tx-link" href={t.explorer_url} target="_blank" rel="noreferrer">{t.hash_short || t.hash}</a> : (t.hash_short || t.hash)}</strong><small>{t.from} → {t.to} · {(t.date || '').slice(0, 10)}</small></div>
          <span>{t.asset} {num(t.amount)}</span><b>{(t.value_now_inr ?? t.value_inr) != null ? money(t.value_now_inr ?? t.value_inr) : '—'}</b>
          <Pill tone={t.status === 'Confirmed' ? 'green' : 'orange'}>{t.status}</Pill><span>{t.network}{t.gas_inr != null ? ` · fee ${money(t.gas_inr)}` : ''}</span></div>)}
      </div>{!rows.length && <div className="empty">{c.transactions.length ? 'No transactions match.' : 'No transactions found for this address yet.'}</div>}</Card>
      {(c.hidden_unverified_transfers > 0) && <p className="sub-note">{c.hidden_unverified_transfers} transfers of unrecognised tokens were hidden (likely spam). “Value today” uses current prices, not the price at the time.</p>}
    </>;
  }}</Frame>;
}

function usePerformance(crypto, walletId) {
  const [perf, setPerf] = useState({ loading: false, data: null });
  useEffect(() => {
    if (!crypto) return;
    if (!isLive(crypto)) { setPerf({ loading: false, data: crypto.performance_30d ? { available: true, points: crypto.performance_30d } : null }); return; }
    let alive = true;
    setPerf({ loading: true, data: null });
    api.get(`/crypto/performance?wallet_id=${walletId || crypto.wallet_id}`)
      .then((d) => alive && setPerf({ loading: false, data: d }))
      .catch(() => alive && setPerf({ loading: false, data: { available: false, reason: 'Price history could not be loaded.' } }));
    return () => { alive = false; };
  }, [crypto?.wallet_id, crypto?.fetched_at, walletId]);   // eslint-disable-line react-hooks/exhaustive-deps
  return perf;
}

export function Portfolio(p) {
  const perf = usePerformance(p.crypto, p.walletId);
  return <Frame p={p} title="Allocation you can actually read." text="How your holdings split, and how they've moved.">{(c) => {
    const pts = perf.data?.available ? perf.data.points : null;
    const bars = pts ? pts.filter((_, i) => i % 5 === 4 || i === pts.length - 1).map((x) => ({ label: x.day.slice(8), value: x.value_inr })) : [];
    const first = pts?.[0]?.value_inr, last = pts?.[pts.length - 1]?.value_inr;
    const pct30 = first ? Math.round((last - first) / first * 1000) / 10 : null;
    return <div className="portfolio-grid">
      <Card className="portfolio-total"><span>Total value</span><strong>{c.total_value_inr != null ? money(c.total_value_inr, p.currency) : '—'}</strong><small className={tone(c.change_24h_pct)}>{change(c.change_24h_pct)} today</small>
        <div className="allocation">{c.assets.filter((a) => a.allocation_pct).map((a, i) => <div key={a.symbol} style={{ width: `${a.allocation_pct}%`, background: CATEGORY_COLORS[i % CATEGORY_COLORS.length] }} />)}</div>
        {c.assets.filter((a) => a.allocation_pct != null).map((a, i) => <div className="legend" key={a.symbol}><i style={{ background: CATEGORY_COLORS[i % CATEGORY_COLORS.length] }}></i><span>{a.symbol}</span><b>{a.allocation_pct}%</b></div>)}</Card>
      <Card><div className="card-title"><div><span>Performance</span><h3>30 day view {pct30 != null && <small className={tone(pct30)}>{change(pct30)}</small>}</h3></div></div>
        {perf.loading ? <Busy text="Loading price history…" /> : pts ? <><BarChart data={bars} /><p className="sub-note">{perf.data.note || 'Your current holdings valued at each day’s price.'}</p></> : <div className="empty">{perf.data?.reason || 'Performance history is unavailable.'}</div>}</Card>
    </div>;
  }}</Frame>;
}

export function Security(p) {
  return <Frame p={p} title="Protect the wallet without touching secrets." text="Arth Raksha checks public signals and explains risks before you act.">{(c) => {
    const s = c.security, warn = s.checks.filter((x) => !x.ok).length;
    return <>
      <div className="metric-grid three">
        <Card><span>Wallet risk</span><strong className={s.risk_label === 'Flagged' ? 'negative' : 'positive'}>{s.risk_label}</strong><small>Public signals only</small></Card>
        <Card><span>Token approvals</span><strong>{s.approvals ?? '—'}</strong><small>{s.approvals == null ? 'Approval scan not run yet' : 'Reviewed'}</small></Card>
        <Card><span>Checks</span><strong>{s.checks.length - warn} / {s.checks.length}</strong><small className={warn ? 'negative' : 'positive'}>{warn ? `${warn} to review` : 'All clear'}</small></Card>
      </div>
      <Card><div className="security-list">{s.checks.map((x) => <div className="security-row" key={x.title}><span className={x.ok ? 'check' : 'warn'}>{x.ok ? '✓' : '!'}</span><div><strong>{x.title}</strong><small>{x.detail}</small></div></div>)}</div></Card>
    </>;
  }}</Frame>;
}
