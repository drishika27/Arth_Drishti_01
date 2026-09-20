import { Card, Pill, BarChart, Donut, Busy, ErrorNote, money } from '../ui';
import { withColors } from './Dashboard';

export default function Analytics({ summary, loading, error, reload, currency }) {
  if (!summary) return loading ? <Busy text="Loading analytics…" /> : <ErrorNote error={error || 'Could not load analytics.'} onRetry={reload} />;
  const cats = withColors(summary.categories);
  const week = summary.last_7_days;
  const weekTotal = week.reduce((a, d) => a + d.amount, 0);
  return <>
    <div className="section-intro"><Pill tone="green">Analytics</Pill><h2>See the patterns, not just the numbers.</h2><p>Built from your saved expenses — manual, scanned and bank-imported.</p></div>
    <div className="two-col">
      <Card><div className="card-title"><div><span>Weekly spend</span><h3>{money(weekTotal, currency)}</h3></div><Pill>7 days</Pill></div><BarChart data={week.map((d) => ({ label: d.label, value: d.amount }))} /></Card>
      <Card><div className="card-title"><div><span>Categories</span><h3>Spending mix</h3></div></div>
        <div className="donut-row"><Donut items={cats} currency={currency} /><div>{cats.map((x) => <div className="legend" key={x.label}><i style={{ background: x.color }}></i><span>{x.label}</span><b>{money(x.value, currency)}</b></div>)}{!cats.length && <small>No spending this month yet.</small>}</div></div></Card>
    </div>
  </>;
}
