import { useState } from 'react';
import { Card, Pill, BarChart, Busy, money, CATEGORY_COLORS } from '../ui';

function NotConnected({ title, text }) {
  return <>
    <div className="section-intro"><Pill tone="green">Arth Raksha</Pill><h2>{title}</h2><p>{text}</p></div>
    <Card><div className="empty">No wallet connected yet. Load sample data from the banner above to preview this page.</div></Card>
  </>;
}
const Sample = ({ c }) => (c?.data_mode === 'demo' ? <Pill tone="orange">Sample data</Pill> : null);
const short = (a) => (a ? `${a.slice(0, 6)}…${a.slice(-4)}` : '');
const change = (v) => (v == null ? '—' : `${v > 0 ? '+' : ''}${v}%`);
const tone = (v) => (v >= 0 ? 'positive' : 'negative');

export function Wallet({ crypto, loading }) {
  const [copied, setCopied] = useState(false);
  if (!crypto) return loading ? <Busy /> : <NotConnected title="Your wallet, in view." text="Connect a wallet address to see balances and activity. Arth Raksha never asks for seed phrases or private keys." />;
  const w = crypto.wallet;
  const copy = () => { navigator.clipboard?.writeText(w.address); setCopied(true); setTimeout(() => setCopied(false), 1500); };
  return <>
    <div className="wallet-hero"><div><Pill tone="green">{crypto.data_mode === 'demo' ? 'Connected · Sample' : 'Connected'}</Pill><h2>{short(w.address)}</h2><p>{w.network} · {w.watch_only ? 'Watch-only wallet' : 'Verified wallet'}</p></div><button className="secondary" onClick={copy}>{copied ? 'Copied ✓' : 'Copy address'}</button></div>
    <div className="metric-grid three">
      <Card><span>Total portfolio</span><strong>{money(crypto.total_value_inr)}</strong><small className={tone(crypto.change_24h_pct)}>{change(crypto.change_24h_pct)} today</small></Card>
      <Card><span>Network</span><strong>Ethereum</strong><small>Gas tracked separately</small></Card>
      <Card><span>Security</span><strong>{crypto.security.risk_label}</strong><small className="positive">{crypto.security.approvals} approvals reviewed</small></Card>
    </div>
    <Card><div className="card-title"><div><span>Safety boundary</span><h3>What Arth Raksha never asks for</h3></div></div><div className="safe-grid"><div>✓ Seed phrases</div><div>✓ Private keys</div><div>✓ Recovery phrases</div><div>✓ Signing secrets</div></div></Card>
    {crypto.disclaimer && <div className="notice">{crypto.disclaimer}</div>}
  </>;
}

export function Assets({ crypto, loading, currency }) {
  if (!crypto) return loading ? <Busy /> : <NotConnected title="Your digital assets at a glance." text="Balances and prices appear once a wallet is connected." />;
  return <>
    <div className="section-intro"><Pill tone="green">{crypto.data_mode === 'demo' ? 'Sample blockchain data' : 'On-chain data'}</Pill><h2>Your digital assets at a glance.</h2><p>{crypto.disclaimer || 'Balances read from the chain; prices from a market-data provider.'}</p></div>
    <Card><div className="table"><div className="thead"><span>Asset</span><span>Balance</span><span>Price</span><span>Value</span><span>24h</span></div>
      {crypto.assets.map((a) => <div className="trow" key={a.symbol}><div><strong>{a.symbol}</strong><small>{a.name}</small></div><span>{a.amount}</span><span>{money(a.price_inr, currency)}</span><b>{money(a.value_inr, currency)}</b><span className={tone(a.change_24h_pct)}>{change(a.change_24h_pct)}</span></div>)}
    </div></Card>
  </>;
}

export function Transactions({ crypto, loading }) {
  const [search, setSearch] = useState('');
  if (!crypto) return loading ? <Busy /> : <NotConnected title="Transactions with context." text="Your on-chain activity appears once a wallet is connected." />;
  const rows = crypto.transactions.filter((t) => Object.values(t).join(' ').toLowerCase().includes(search.toLowerCase()));
  return <>
    <div className="section-intro"><Pill tone="green">Activity</Pill><h2>Transactions with context.</h2><p>Every row includes the network, status, gas and counterparties. <Sample c={crypto} /></p></div>
    <div className="toolbar"><input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search hash, asset, address…" /></div>
    <Card><div className="table"><div className="thead"><span>Transaction</span><span>Asset</span><span>Value</span><span>Status</span><span>Network</span></div>
      {rows.map((t) => <div className="trow" key={t.hash}><div><strong>{t.type} · {t.hash}</strong><small>{t.from} → {t.to} · {t.date}</small></div><span>{t.asset} {t.amount}</span><b>{money(t.value_inr)}</b><Pill tone={t.status === 'Confirmed' ? 'green' : 'orange'}>{t.status}</Pill><span>{t.network} · gas ₹{t.gas_inr}</span></div>)}
    </div>{!rows.length && <div className="empty">No transactions match.</div>}</Card>
  </>;
}

export function Portfolio({ crypto, loading, currency }) {
  if (!crypto) return loading ? <Busy /> : <NotConnected title="Allocation you can actually read." text="Portfolio value and allocation appear once a wallet is connected." />;
  const perf = crypto.performance_30d;
  const bars = perf.filter((_, i) => i % 5 === 4 || i === perf.length - 1).map((p) => ({ label: p.day.slice(8), value: p.value_inr }));
  const first = perf[0]?.value_inr, last = perf[perf.length - 1]?.value_inr;
  const pct30 = first ? Math.round((last - first) / first * 1000) / 10 : null;
  return <>
    <div className="section-intro"><Pill tone="green">Portfolio</Pill><h2>Allocation you can actually read.</h2><p>{crypto.disclaimer || 'Values in INR; USD is available in Settings.'}</p></div>
    <div className="portfolio-grid">
      <Card className="portfolio-total"><span>Total value</span><strong>{money(crypto.total_value_inr, currency)}</strong><small className={tone(crypto.change_24h_pct)}>{change(crypto.change_24h_pct)} today</small>
        <div className="allocation">{crypto.assets.map((a, i) => <div key={a.symbol} style={{ width: `${a.allocation_pct}%`, background: CATEGORY_COLORS[i % CATEGORY_COLORS.length] }} />)}</div>
        {crypto.assets.map((a, i) => <div className="legend" key={a.symbol}><i style={{ background: CATEGORY_COLORS[i % CATEGORY_COLORS.length] }}></i><span>{a.symbol}</span><b>{a.allocation_pct}%</b></div>)}</Card>
      <Card><div className="card-title"><div><span>Performance</span><h3>30 day view {pct30 != null && <small className={tone(pct30)}>{change(pct30)}</small>}</h3></div></div><BarChart data={bars} /></Card>
    </div>
  </>;
}

export function Security({ crypto, loading }) {
  if (!crypto) return loading ? <Busy /> : <NotConnected title="Protect the wallet without touching secrets." text="Risk checks run against your connected wallet's public data." />;
  const s = crypto.security;
  return <>
    <div className="section-intro"><Pill tone="green">Security center</Pill><h2>Protect the wallet without touching secrets.</h2><p>Arth Raksha monitors public wallet signals and explains risks before you act. <Sample c={crypto} /></p></div>
    <div className="metric-grid three">
      <Card><span>Wallet risk</span><strong className="positive">{s.risk_label}</strong><small>Public signals only</small></Card>
      <Card><span>Approvals</span><strong>{s.approvals}</strong><small className="positive">No high-risk approval</small></Card>
      <Card><span>Address checks</span><strong>{s.address_checks}</strong><small className="positive">{crypto.data_mode === 'demo' ? 'Verified in sample set' : 'Verified'}</small></Card>
    </div>
    <Card><div className="security-list">{s.checks.map((x) => <div className="security-row" key={x.title}><span className={x.ok ? 'check' : 'warn'}>{x.ok ? '✓' : '!'}</span><div><strong>{x.title}</strong><small>{x.detail}</small></div></div>)}</div></Card>
  </>;
}
