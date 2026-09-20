import { useEffect, useState } from 'react';
import { api } from '../api';
import { ErrorNote, Busy, Pill, money } from '../ui';
import { CATEGORIES } from './Expenses';

/** Connect a bank: choose institution -> read exactly what will be shared -> approve.
 *  ArthDrishti never asks for a bank password, OTP or UPI PIN — the provider hands back an access token only. */
export function ConnectBankModal({ onClose, onDone }) {
  const [providers, setProviders] = useState(null);
  const [consent, setConsent] = useState(null);       // { consent_id, consent }
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState(null);

  useEffect(() => { api.get('/bank/providers').then((r) => setProviders(r.providers)).catch((e) => setError(e.message)); }, []);

  async function pick(provider, inst) {
    setBusy(true); setError('');
    try { setConsent(await api.post('/bank/connect/start', { provider: provider.id, institution_id: inst.id })); }
    catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  async function decide(approve) {
    setBusy(true); setError('');
    try {
      const r = await api.post('/bank/connect/complete', { consent_id: consent.consent_id, approve });
      if (!approve) { onClose(); return; }
      setResult(r); onDone();
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }

  return <div className="modal-backdrop"><div className="modal">
    <div className="modal-head"><h2>Connect a bank</h2><button type="button" onClick={onClose}>×</button></div>
    {result ? <>
      <div className="notice">Connected to {result.connection.institution}. Imported {result.imported} transactions from {result.connection.accounts} accounts — new ones will sync automatically.</div>
      <button className="primary" onClick={onClose}>Done</button>
    </> : consent ? <>
      <div><strong>{consent.consent.institution}</strong> <Pill tone="orange">Test bank</Pill></div>
      <p className="sub-note" style={{ margin: 0 }}>{consent.consent.purpose}</p>
      <div className="consent-box"><b>ArthDrishti will read</b><ul>{consent.consent.data_requested.map((x) => <li key={x}>{x}</li>)}</ul></div>
      <div className="consent-box safe"><b>ArthDrishti will never ask for or get</b><ul>{consent.consent.data_not_requested.map((x) => <li key={x}>{x}</li>)}</ul></div>
      <p className="sub-note" style={{ margin: 0 }}>Access lasts {consent.consent.duration_days} days and you can disconnect any time. {consent.consent.note}</p>
      <ErrorNote error={error} />
      <button className="primary" disabled={busy} onClick={() => decide(true)}>{busy ? 'Connecting…' : 'Approve and connect'}</button>
      <button className="secondary" disabled={busy} onClick={() => decide(false)}>Decline</button>
    </> : <>
      {!providers && !error && <Busy text="Loading banks…" />}
      {providers?.map((p) => <div key={p.id}>
        <p className="sub-note" style={{ margin: '0 0 8px' }}>{p.mode === 'sandbox' ? 'Test mode — these are practice banks with synthetic data. Real banks connect the same way once a licensed provider is enabled.' : 'Choose your bank.'}</p>
        {p.institutions.map((i) => <button key={i.id} className="secondary bank-pick" disabled={busy} onClick={() => pick(p, i)}>{i.name}</button>)}
      </div>)}
      <ErrorNote error={error} />
    </>}
  </div></div>;
}

/** Statement import: upload -> preview (edit categories) -> import. Real bank data with no bank integration. */
export function StatementModal({ onClose, onDone, currency }) {
  const [file, setFile] = useState(null);
  const [password, setPassword] = useState('');
  const [needPassword, setNeedPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [preview, setPreview] = useState(null);
  const [rows, setRows] = useState([]);
  const [label, setLabel] = useState('');
  const [done, setDone] = useState(null);

  async function parse(e) {
    e?.preventDefault();
    if (!file) { setError('Choose a statement file first.'); return; }
    setBusy(true); setError('');
    const body = new FormData();
    body.append('file', file);
    if (password) body.append('password', password);
    try {
      const p = await api.upload('/bank/statements/parse', body);
      setPreview(p); setNeedPassword(false);
      setRows(p.transactions.map((t) => ({ ...t, original: t.category })));
      setLabel(p.bank_hint ? `${p.bank_hint} account` : 'My bank account');
    } catch (err) {
      setNeedPassword(err.code === 'password_required' || err.code === 'password_wrong');
      setError(err.message);
    } finally { setBusy(false); }
  }

  async function doImport() {
    setBusy(true); setError('');
    const items = rows.filter((r) => !r.duplicate).map((r) => ({
      external_id: r.external_id, date: r.date, description: r.description, merchant: r.merchant, amount: r.amount,
      kind: r.kind, category: r.category, edited: r.category !== r.original,
    }));
    try {
      setDone(await api.post('/bank/statements/import', { account_label: label.trim() || 'My bank account', bank_name: preview.bank_hint || '', closing_balance: preview.closing_balance, items }));
      onDone();
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  }

  const setCat = (id, category) => setRows((rs) => rs.map((r) => (r.external_id === id ? { ...r, category } : r)));
  const fresh = rows.filter((r) => !r.duplicate);

  return <div className="modal-backdrop"><div className={`modal ${preview && !done ? 'wide' : ''}`}>
    <div className="modal-head"><h2>Import a bank statement</h2><button type="button" onClick={onClose}>×</button></div>
    {done ? <>
      <div className="notice">Imported {done.imported} transactions into “{done.account.name}”{done.duplicates_skipped ? ` (${done.duplicates_skipped} already imported were skipped)` : ''}.</div>
      <button className="primary" onClick={onClose}>Done</button>
    </> : !preview ? <form onSubmit={parse} style={{ display: 'grid', gap: 12 }}>
      <p className="sub-note" style={{ margin: 0 }}>Download a statement from your bank’s app or website (CSV, Excel or PDF) and upload it here. It’s read on our server and only the transactions you approve are saved. If the PDF has a password, it’s used once and never stored.</p>
      <input type="file" accept=".csv,.xlsx,.pdf,text/csv,application/pdf" onChange={(e) => { setFile(e.target.files?.[0] || null); setError(''); setNeedPassword(false); }} />
      {needPassword && <input type="password" placeholder="PDF password" value={password} onChange={(e) => setPassword(e.target.value)} autoFocus />}
      <ErrorNote error={error} />
      <button className="primary" disabled={busy || !file}>{busy ? 'Reading statement…' : needPassword ? 'Unlock and read' : 'Read statement'}</button>
    </form> : <>
      <div className="notice">Found <b>{preview.count}</b> transactions{preview.period ? ` from ${preview.period.from} to ${preview.period.to}` : ''}. <b>{preview.new_count}</b> new{preview.duplicate_count ? `, ${preview.duplicate_count} already imported` : ''}{preview.skipped_rows ? `, ${preview.skipped_rows} unreadable rows skipped` : ''}. Fix any category below before importing.</div>
      {preview.warnings.map((w) => <div className="notice error" key={w}>{w}</div>)}
      <label className="sub-note" style={{ margin: 0 }}>Account name <input value={label} onChange={(e) => setLabel(e.target.value)} maxLength={80} style={{ marginLeft: 8, width: 240 }} /></label>
      <div className="preview-scroll"><table className="mini-table"><thead><tr><th>Date</th><th>Description</th><th>Amount</th><th>Category</th></tr></thead><tbody>
        {rows.map((r) => <tr key={r.external_id} className={r.duplicate ? 'dim' : ''}>
          <td>{r.date}</td><td title={r.description}>{r.merchant}{r.duplicate && <Pill>already imported</Pill>}{r.direction_guessed && <Pill tone="orange">check direction</Pill>}<small>{r.description.slice(0, 60)}</small></td>
          <td className={r.kind === 'income' ? 'positive' : ''}>{r.kind === 'income' ? '+' : '-'}{money(r.amount, currency)}</td>
          <td>{r.kind === 'income' ? <Pill tone="green">Income</Pill> : r.duplicate ? r.category : <select value={r.category} onChange={(e) => setCat(r.external_id, e.target.value)}>{CATEGORIES.map((c) => <option key={c}>{c}</option>)}</select>}</td>
        </tr>)}
      </tbody></table></div>
      <ErrorNote error={error} />
      <button className="primary" disabled={busy || !fresh.length} onClick={doImport}>{busy ? 'Importing…' : fresh.length ? `Import ${fresh.length} transactions` : 'Nothing new to import'}</button>
    </>}
  </div></div>;
}
