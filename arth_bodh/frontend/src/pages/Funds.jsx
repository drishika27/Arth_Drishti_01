import { Card, Pill, Busy, ErrorNote, money } from '../ui';

// Bank accounts arrive with the bank-connection phase; until an account is
// linked this page shows only real figures derived from the user's expenses.
export default function Funds({ summary, loading, error, reload, currency }) {
  if (!summary) return loading ? <Busy text="Loading your funds…" /> : <ErrorNote error={error || 'Could not load your funds.'} onRetry={reload} />;
  return <>
    <div className="section-intro"><Pill tone="green">Live overview</Pill><h2>Your money, clearly accounted for.</h2><p>Figures below come from your own saved transactions.</p></div>
    <div className="metric-grid three">
      <Card><span>Total funds</span><strong>{summary.available_funds != null ? money(summary.available_funds, currency) : '—'}</strong><small>{summary.bank_accounts ? `Across ${summary.bank_accounts} account(s)` : 'No bank account linked'}</small></Card>
      <Card><span>Income this month</span><strong>{money(summary.income, currency)}</strong><small>From income entries and bank credits</small></Card>
      <Card><span>Remaining budget</span><strong>{summary.remaining_budget != null ? money(summary.remaining_budget, currency) : '—'}</strong><small>{summary.budget != null ? `${money(summary.budget, currency)} planned spend` : 'Set a monthly budget in Settings'}</small></Card>
    </div>
    <Card><div className="card-title"><div><span>Accounts</span><h3>Balances</h3></div></div><div className="empty">No bank accounts linked yet.</div></Card>
  </>;
}
