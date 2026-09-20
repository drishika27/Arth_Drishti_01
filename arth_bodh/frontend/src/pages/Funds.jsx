import { useState } from 'react';
import { api } from '../api';
import { Card, Pill, Busy, ErrorNote, money } from '../ui';
import { ConnectBankModal, StatementModal } from './BankModals';

const TYPE_LABEL = { savings: 'Savings', checking: 'Current / Salary', deposit: 'Fixed deposit', credit: 'Credit card' };
const MODE = { demo: ['Sample data', 'orange'], sandbox: ['Test bank', 'orange'], statement: ['From statement', 'purple'], live: ['Live', 'green'] };
const ago = (iso) => {
  if (!iso) return 'never';
  const m = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  return m < 1 ? 'just now' : m < 60 ? `${m} min ago` : m < 1440 ? `${Math.round(m / 60)} h ago` : `${Math.round(m / 1440)} d ago`;
};

export default function Funds({ summary, accounts, connections, loading, error, reload, currency }) {
  const [modal, setModal] = useState(null);      // 'connect' | 'statement'
  const [busyId, setBusyId] = useState(null);
  const [note, setNote] = useState('');
  const [actionError, setActionError] = useState('');

  if (!summary) return loading ? <Busy text="Loading your funds…" /> : <ErrorNote error={error || 'Could not load your funds.'} onRetry={reload} />;
  const list = accounts?.accounts || [];
  const conns = connections?.connections || [];
  const sample = list.some((a) => a.data_mode === 'demo');

  async function sync(c) {
    setBusyId(c.id); setActionError(''); setNote('');
    try { const r = await api.post(`/bank/connections/${c.id}/sync`); setNote(r.new ? `Synced — ${r.new} new transactions.` : 'Already up to date.'); reload(); }
    catch (e) { setActionError(e.message); reload(); } finally { setBusyId(null); }
  }
  async function disconnect(c) {
    const keep = window.confirm(`Disconnect ${c.institution}?\n\nOK = disconnect and KEEP the imported transactions.\nCancel = go back.`);
    if (!keep) return;
    setBusyId(c.id); setActionError('');
    try { await api.del(`/bank/connections/${c.id}`); reload(); } catch (e) { setActionError(e.message); } finally { setBusyId(null); }
  }

  return <>
    <div className="section-intro"><Pill tone="green">Live overview</Pill><h2>Your money, clearly accounted for.</h2><p>Figures below come from your own saved transactions{sample ? ' (currently including sample data).' : '.'}</p></div>
    <div className="metric-grid three">
      <Card><span>Total funds</span><strong>{summary.available_funds != null ? money(summary.available_funds, currency) : '—'}</strong><small>{summary.bank_accounts ? `Across ${summary.bank_accounts} account${summary.bank_accounts === 1 ? '' : 's'}` : 'No bank account linked'}</small></Card>
      <Card><span>Income this month</span><strong>{money(summary.income, currency)}</strong><small>From income entries and bank credits</small></Card>
      <Card><span>Remaining budget</span><strong>{summary.remaining_budget != null ? money(summary.remaining_budget, currency) : '—'}</strong><small>{summary.budget != null ? `${money(summary.budget, currency)} planned spend` : 'Set a monthly budget in Settings'}</small></Card>
    </div>

    <Card><div className="card-title"><div><span>Bring in your bank data</span><h3>Connect or import</h3></div></div>
      <div className="hero-actions" style={{ marginTop: 0 }}>
        <button className="primary" onClick={() => setModal('connect')}>+ Connect a bank</button>
        <button className="secondary" onClick={() => setModal('statement')}>Import a statement (CSV / Excel / PDF)</button>
      </div>
      <p className="sub-note">We never ask for your bank password, OTP or UPI PIN. Connecting uses a consent screen; importing reads a statement you download yourself.</p>
      {note && <div className="notice">{note}</div>}
      <ErrorNote error={actionError} />
      {conns.filter((c) => c.provider !== 'demo').map((c) => <div className="account" key={c.id}>
        <div><strong>{c.institution} <Pill tone={MODE[c.data_mode]?.[1]}>{MODE[c.data_mode]?.[0]}</Pill>{c.status === 'error' && <Pill tone="orange">needs attention</Pill>}</strong>
          <span>{c.accounts} account{c.accounts === 1 ? '' : 's'} · {c.auto_sync ? `auto-sync on · last synced ${ago(c.last_synced_at)}` : `last import ${ago(c.last_synced_at)}`}{c.last_error ? ` · ${c.last_error}` : ''}</span></div>
        <div className="actions">{c.auto_sync && <button className="link" disabled={busyId === c.id} onClick={() => sync(c)}>{busyId === c.id ? 'Syncing…' : 'Sync now'}</button>}
          <button className="delete" disabled={busyId === c.id} onClick={() => disconnect(c)}>{c.provider === 'statement' ? 'Remove' : 'Disconnect'}</button></div>
      </div>)}
    </Card>

    <Card className="review"><div className="card-title"><div><span>Accounts</span><h3>Balances</h3></div>{sample && <Pill tone="orange">Includes sample data</Pill>}</div>
      {list.map((a) => <div className="account" key={a.id}><div><strong>{a.name} <Pill tone={MODE[a.data_mode]?.[1]}>{MODE[a.data_mode]?.[0]}</Pill></strong><span>{a.mask} · {TYPE_LABEL[a.type] || a.type} · {a.institution}</span></div><b>{a.balance != null ? money(a.balance, currency) : '—'}</b></div>)}
      {!list.length && <div className="empty">No bank accounts yet — connect a bank or import a statement above.</div>}
    </Card>

    {modal === 'connect' && <ConnectBankModal onClose={() => setModal(null)} onDone={reload} />}
    {modal === 'statement' && <StatementModal currency={currency} onClose={() => setModal(null)} onDone={reload} />}
  </>;
}
