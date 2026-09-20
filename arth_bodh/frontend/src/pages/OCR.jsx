import { useRef, useState } from 'react';
import { api } from '../api';
import { Card, Pill } from '../ui';
import { CATEGORIES } from './Expenses';

const ENGINE_LABEL = { claude: 'AI reader', local: 'Built-in reader', text: 'Pasted text' };
const today = () => new Date().toISOString().slice(0, 10);

/** Receipt OCR: upload or paste -> scanning -> review/edit -> save.
 *  Every failure shows a message and a Retry (re-sends the same file). */
export default function OCR({ onSaved }) {
  const [text, setText] = useState('');
  const [file, setFile] = useState(null);
  const [phase, setPhase] = useState('idle');     // idle | scanning | review | saving | saved
  const [error, setError] = useState(null);       // {message, retryable}
  const [scan, setScan] = useState(null);         // server response
  const [form, setForm] = useState(null);         // editable fields
  const [drag, setDrag] = useState(false);
  const input = useRef(null);

  function pick(f) {
    if (!f) return;
    setFile(f); setError(null); setScan(null); setPhase('idle');
  }

  async function run(engine = 'auto') {
    if (!file && !text.trim()) { setError({ message: 'Choose a receipt image or paste its text first.' }); return; }
    setPhase('scanning'); setError(null);
    const body = new FormData();
    if (file) body.append('file', file); else body.append('text', text);
    body.append('engine', engine);
    try {
      const r = await api.upload('/receipts/scan', body);
      setScan(r);
      setForm({
        merchant: r.extracted.merchant || '', amount: r.extracted.amount ?? '', tax: r.extracted.tax ?? '',
        category: r.extracted.category || 'Other', date: r.extracted.date || today(), note: '',
      });
      setPhase('review');
    } catch (e) {
      setError({ message: e.message, retryable: e.retryable ?? true });
      setPhase('idle');
    }
  }

  async function save() {
    setPhase('saving'); setError(null);
    try {
      await api.post(`/receipts/${scan.receipt_id}/confirm`, {
        merchant: form.merchant, amount: Number(form.amount), category: form.category, date: form.date,
        note: form.note, ...(form.tax !== '' ? { tax: Number(form.tax) } : {}),
      });
      setPhase('saved'); onSaved();
    } catch (e) { setError({ message: e.message }); setPhase('review'); }
  }

  function reset() { setFile(null); setText(''); setScan(null); setForm(null); setError(null); setPhase('idle'); if (input.current) input.current.value = ''; }
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const scanning = phase === 'scanning';

  return <>
    <div className="section-intro"><Pill tone="orange">Receipt OCR</Pill><h2>Turn a receipt into a clean expense.</h2><p>Upload a photo or PDF of a bill, or paste its text. We extract the merchant, date, total and tax — you review before anything is saved.</p></div>
    <Card>
      <div className={`dropzone${drag ? ' drag' : ''}`}
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); pick(e.dataTransfer.files?.[0]); }}>
        <div className="upload-icon">▧</div>
        <h3>{file ? file.name : 'Drop receipt here'}</h3>
        <p>{file ? `${(file.size / 1024).toFixed(0)} KB · ready to scan` : 'JPG, PNG, WEBP or PDF · up to 8 MB — or paste receipt text below'}</p>
        <input ref={input} type="file" accept="image/jpeg,image/png,image/webp,application/pdf" hidden onChange={(e) => pick(e.target.files?.[0])} />
        <div className="hero-actions" style={{ justifyContent: 'center', marginTop: 0 }}>
          <button className="secondary" onClick={() => input.current?.click()} disabled={scanning}>{file ? 'Choose a different file' : 'Choose file'}</button>
          {file && <button className="link" onClick={reset} disabled={scanning}>Remove</button>}
        </div>
        <textarea value={text} onChange={(e) => setText(e.target.value)} disabled={!!file || scanning} placeholder="Example: Cafe Coffee Day ₹540 19 Sep" />
        <button className="primary" onClick={() => run()} disabled={scanning || phase === 'saving'}>{scanning ? 'Reading your receipt…' : 'Extract receipt'}</button>
        {scanning && <p className="scan-progress">Scanning — the first scan can take a few seconds.</p>}
      </div>
      {error && <div className="notice error">{error.message}
        {error.retryable !== false && <> <button className="link" onClick={() => run()}>Retry</button>{file && <button className="link" onClick={() => run('local')}>Try built-in reader</button>}</>}
      </div>}
    </Card>

    {phase === 'saved' && <Card className="review"><div className="card-title"><div><span>Saved</span><h3>Added to your expenses</h3></div><Pill tone="green">Done</Pill></div><button className="primary" onClick={reset}>Scan another receipt</button></Card>}

    {(phase === 'review' || phase === 'saving') && form && <Card className="review">
      <div className="card-title"><div><span>Review before saving</span><h3>Extracted fields</h3></div><Pill tone="orange">{ENGINE_LABEL[scan.engine] || scan.engine} · {scan.confidence} confidence</Pill></div>
      {scan.warnings.map((w) => <div className="notice" key={w}>{w}</div>)}
      <div className="form-grid">
        <label>Merchant<input value={form.merchant} onChange={set('merchant')} /></label>
        <label>Amount<input type="number" min="0" step="0.01" value={form.amount} onChange={set('amount')} /></label>
        <label>Tax<input type="number" min="0" step="0.01" value={form.tax} onChange={set('tax')} placeholder="Not found" /></label>
        <label>Category<select value={form.category} onChange={set('category')}>{CATEGORIES.map((c) => <option key={c}>{c}</option>)}</select></label>
        <label>Date<input type="date" max={today()} value={form.date} onChange={set('date')} /></label>
        <label>Note<input value={form.note} onChange={set('note')} /></label>
      </div>
      <button className="primary" onClick={save} disabled={phase === 'saving' || !form.merchant || !Number(form.amount)}>{phase === 'saving' ? 'Saving…' : 'Save as expense'}</button>{' '}
      <button className="secondary" onClick={reset} disabled={phase === 'saving'}>Discard</button>
    </Card>}
  </>;
}
