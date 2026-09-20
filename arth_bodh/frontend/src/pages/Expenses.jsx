import { useState } from 'react';
import { api } from '../api';
import { Card, Pill, Empty, Busy, ErrorNote, money } from '../ui';

export const CATEGORIES = ['Food', 'Travel', 'Shopping', 'Groceries', 'Subscriptions', 'Health', 'Bills', 'Entertainment', 'Education', 'Other'];
const SOURCE_LABEL = { manual: 'Manual', ocr: 'Receipt', bank: 'Bank' };
const today = () => new Date().toISOString().slice(0, 10);

/** Add / edit modal. Editing a bank-imported row is how users correct its category. */
export function ExpenseModal({ expense, onClose, onSaved }) {
  const editing = !!expense;
  const [form, setForm] = useState({
    merchant: expense?.merchant || '', amount: expense?.amount ?? '', category: expense?.category || 'Food',
    date: expense?.date || today(), note: expense?.note || '', tax: expense?.tax ?? '',
  });
  const [applySimilar, setApplySimilar] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const categoryChanged = editing && form.category !== expense.category;

  async function submit(e) {
    e.preventDefault();
    setBusy(true); setError('');
    const body = {
      merchant: form.merchant, amount: Number(form.amount), category: form.category,
      date: form.date, note: form.note, ...(form.tax !== '' ? { tax: Number(form.tax) } : {}),
    };
    try {
      if (editing) await api.patch(`/expenses/${expense.id}`, { ...body, apply_to_similar: applySimilar && categoryChanged });
      else await api.post('/expenses', body);
      onSaved();
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  }

  return <div className="modal-backdrop"><form className="modal" onSubmit={submit}>
    <div className="modal-head"><h2>{editing ? 'Edit expense' : 'Add expense'}</h2><button type="button" onClick={onClose}>×</button></div>
    {editing && expense.source === 'bank' && <div className="notice">Imported from your bank{expense.raw_description ? `: “${expense.raw_description}”` : ''}. Correct anything that looks off.</div>}
    <input value={form.merchant} onChange={set('merchant')} required placeholder="Merchant" maxLength={200} />
    <input value={form.amount} onChange={set('amount')} required type="number" min="0.01" step="0.01" placeholder="Amount (INR)" />
    <select value={form.category} onChange={set('category')}>{CATEGORIES.map((c) => <option key={c}>{c}</option>)}</select>
    <input value={form.date} onChange={set('date')} type="date" required max={today()} />
    <input value={form.tax} onChange={set('tax')} type="number" min="0" step="0.01" placeholder="Tax (optional)" />
    <input value={form.note} onChange={set('note')} placeholder="Note" maxLength={500} />
    {categoryChanged && <label className="check-row"><input type="checkbox" checked={applySimilar} onChange={(e) => setApplySimilar(e.target.checked)} /> Also re-categorise my other “{expense.merchant}” transactions</label>}
    <ErrorNote error={error} />
    <button className="primary" disabled={busy}>{busy ? 'Saving…' : editing ? 'Save changes' : 'Save expense'}</button>
  </form></div>;
}

export default function Expenses({ expenses, loading, error, reload, search, setSearch, onAdd, onEdit, currency }) {
  const [deleteError, setDeleteError] = useState('');
  async function remove(id) {
    if (!window.confirm('Delete this expense?')) return;
    try { await api.del(`/expenses/${id}`); setDeleteError(''); reload(); } catch (e) { setDeleteError(e.message); }
  }
  const rows = expenses.filter((e) => `${e.merchant} ${e.category} ${e.note}`.toLowerCase().includes(search.toLowerCase()));
  return <>
    <div className="section-intro"><Pill tone="purple">Arth Bodh</Pill><h2>Expenses, without the spreadsheet.</h2><p>Manual entries, scanned receipts and bank transactions — all in one place.</p></div>
    <div className="toolbar"><input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search merchant, category or note…" /><button className="primary" onClick={onAdd}>+ Add expense</button></div>
    <ErrorNote error={error || deleteError} onRetry={error ? reload : undefined} />
    <Card><div className="table"><div className="thead"><span>Merchant</span><span>Category</span><span>Date</span><span>Amount</span><span></span></div>
      {rows.map((e) => <div className="trow" key={e.id}>
        <div><strong>{e.merchant}</strong><small>{SOURCE_LABEL[e.source]}{e.account_name ? ` · ${e.account_name}` : ''}{e.note ? ` · ${e.note}` : ''}</small></div>
        <Pill>{e.category}</Pill><span>{e.date}</span><b>-{money(e.amount, currency)}</b>
        <div className="actions"><button className="link" onClick={() => onEdit(e)}>Edit</button><button className="delete" onClick={() => remove(e.id)}>Delete</button></div>
      </div>)}
    </div>
    {loading && !rows.length ? <Busy text="Loading your expenses…" /> : !rows.length && <Empty text={search ? 'No expenses match your search.' : 'No expenses yet — add one, scan a receipt, or connect a bank.'} />}</Card>
  </>;
}
