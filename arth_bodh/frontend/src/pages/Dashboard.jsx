import { Card, Pill, Donut, Busy, ErrorNote, money, CATEGORY_COLORS } from '../ui';

export const withColors = (categories) => categories.map((c, i) => ({ label: c.category, value: c.amount, color: CATEGORY_COLORS[i % CATEGORY_COLORS.length] }));

const pct = (v) => (v == null ? null : `${v > 0 ? '+' : ''}${v}% vs last month`);

export default function Dashboard({ setPage, summary, loading, error, reload, currency, crypto, security }) {
  if (!summary) return loading ? <Busy text="Loading your overview…" /> : <ErrorNote error={error || 'Could not load your overview.'} onRetry={reload} />;
  const cats = withColors(summary.categories);
  const funds = summary.available_funds;
  return <>
    <div className="hero"><div><Pill tone="purple">Financial command center</Pill><h2>Understand today.<br /><span>Protect tomorrow.</span></h2><p>Arth Bodh makes everyday money visible; Arth Raksha keeps digital assets in view.</p><div className="hero-actions"><button className="primary" onClick={() => setPage('expenses')}>Add expense</button><button className="secondary" onClick={() => setPage('ai')}>Ask Arth AI ✦</button></div></div>
      <div className="hero-orb"><div className="orb-inner">{funds != null ? money(funds, currency) : money(summary.spend, currency)}<br /><small>{funds != null ? 'available funds' : 'spent this month'}</small></div></div></div>
    <ErrorNote error={error} onRetry={reload} />
    <div className="metric-grid">
      <Card><span>Available funds</span><strong>{funds != null ? money(funds, currency) : '—'}</strong>{funds != null ? <small>Across {summary.bank_accounts} linked account{summary.bank_accounts === 1 ? '' : 's'}</small> : <button className="link" onClick={() => setPage('funds')}>Connect a bank →</button>}</Card>
      <Card><span>Monthly spending</span><strong>{money(summary.spend, currency)}</strong><small>{summary.budget != null ? `of ${money(summary.budget, currency)} budget` : 'No budget set'}{summary.spend_change_pct != null ? ` · ${pct(summary.spend_change_pct)}` : ''}</small></Card>
      <Card><span>Crypto portfolio</span><strong>{crypto?.total_value_inr != null ? money(crypto.total_value_inr, currency) : '—'}</strong>{crypto ? <small className={crypto.change_24h_pct >= 0 ? 'positive' : 'negative'}>{crypto.change_24h_pct != null ? `${crypto.change_24h_pct > 0 ? '+' : ''}${crypto.change_24h_pct}% today` : 'Prices unavailable'}</small> : <button className="link" onClick={() => setPage('wallet')}>Connect a wallet →</button>}</Card>
      <Card><span>Security status</span><strong>{security?.risk_label || 'Not checked'}</strong><small>{security ? `${security.approvals} token approvals reviewed` : 'Connect a wallet to check'}</small></Card>
    </div>
    <div className="two-col">
      <Card><div className="card-title"><div><span>Recent expenses</span><h3>Money in motion</h3></div><button className="link" onClick={() => setPage('expenses')}>View all →</button></div>
        {summary.recent.slice(0, 4).map((e) => <div className="row" key={e.id}><div className="avatar">{e.merchant[0]}</div><div className="row-main"><strong>{e.merchant}</strong><span>{e.category} · {e.date}</span></div><b>-{money(e.amount, currency)}</b></div>)}
        {!summary.recent.length && <div className="empty">Nothing tracked yet — add an expense or scan a receipt.</div>}</Card>
      <Card><div className="card-title"><div><span>Spending mix</span><h3>Where it goes</h3></div><button className="link" onClick={() => setPage('analytics')}>Analytics →</button></div>
        <div className="donut-row"><Donut items={cats} currency={currency} /><div>{cats.slice(0, 4).map((x) => <div className="legend" key={x.label}><i style={{ background: x.color }}></i><span>{x.label}</span><b>{money(x.value, currency)}</b></div>)}</div></div></Card>
    </div>
  </>;
}
