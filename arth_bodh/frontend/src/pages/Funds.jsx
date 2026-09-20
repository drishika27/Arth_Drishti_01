import { Card, Pill, Busy, ErrorNote, money } from '../ui';

const TYPE_LABEL = { savings: 'Savings', checking: 'Current / Salary', deposit: 'Fixed deposit', credit: 'Credit card' };

export default function Funds({ summary, accounts, loading, error, reload, currency }) {
  if (!summary) return loading ? <Busy text="Loading your funds…" /> : <ErrorNote error={error || 'Could not load your funds.'} onRetry={reload} />;
  const list = accounts?.accounts || [];
  const sample = list.some((a) => a.data_mode === 'demo');
  return <>
    <div className="section-intro"><Pill tone="green">Live overview</Pill><h2>Your money, clearly accounted for.</h2><p>Figures below come from your own saved transactions{sample ? ' (currently sample data).' : '.'}</p></div>
    <div className="metric-grid three">
      <Card><span>Total funds</span><strong>{summary.available_funds != null ? money(summary.available_funds, currency) : '—'}</strong><small>{summary.bank_accounts ? `Across ${summary.bank_accounts} account${summary.bank_accounts === 1 ? '' : 's'}` : 'No bank account linked'}</small></Card>
      <Card><span>Income this month</span><strong>{money(summary.income, currency)}</strong><small>From income entries and bank credits</small></Card>
      <Card><span>Remaining budget</span><strong>{summary.remaining_budget != null ? money(summary.remaining_budget, currency) : '—'}</strong><small>{summary.budget != null ? `${money(summary.budget, currency)} planned spend` : 'Set a monthly budget in Settings'}</small></Card>
    </div>
    <Card><div className="card-title"><div><span>Accounts</span><h3>Balances</h3></div>{sample && <Pill tone="orange">Sample data</Pill>}</div>
      {list.map((a) => <div className="account" key={a.id}><div><strong>{a.name}</strong><span>{a.mask} · {TYPE_LABEL[a.type] || a.type} · {a.institution}</span></div><b>{a.balance != null ? money(a.balance, currency) : '—'}</b></div>)}
      {!list.length && <div className="empty">No bank accounts linked yet.</div>}
    </Card>
  </>;
}
