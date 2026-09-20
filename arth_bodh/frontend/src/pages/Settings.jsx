import { useState } from 'react';
import { api, updateStoredUser } from '../api';
import { Card, Pill, ErrorNote } from '../ui';

export default function Settings({ user, setUser, dark, setDark, onLogout, demo, demoBusy, toggleDemo }) {
  const [budget, setBudget] = useState(user.monthly_budget ?? '');
  const [name, setName] = useState(user.name || '');
  const [msg, setMsg] = useState('');
  const [error, setError] = useState('');

  async function save(patch) {
    setError(''); setMsg('');
    try {
      const u = await api.patch('/me', patch);
      setUser(u); updateStoredUser(u); setMsg('Saved.');
    } catch (e) { setError(e.message); }
  }

  return <>
    <div className="section-intro"><Pill>Preferences</Pill><h2>Make ArthDrishti yours.</h2><p>Your preferences are saved to your account and follow you across devices.</p></div>
    <Card>
      <div className="settings-row"><div><strong>Theme</strong><small>Light or dark interface</small></div><div className="seg"><button className={!dark ? 'selected' : ''} onClick={() => setDark(false)}>Light</button><button className={dark ? 'selected' : ''} onClick={() => setDark(true)}>Dark</button></div></div>
      <div className="settings-row"><div><strong>Language</strong><small>English / हिंदी</small></div><div className="seg"><button className={user.language === 'English' ? 'selected' : ''} onClick={() => save({ language: 'English' })}>English</button><button className={user.language === 'हिंदी' ? 'selected' : ''} onClick={() => save({ language: 'हिंदी' })}>हिंदी</button></div></div>
      <div className="settings-row"><div><strong>Currency</strong><small>Display preference</small></div><div className="seg"><button className={user.currency === 'INR' ? 'selected' : ''} onClick={() => save({ currency: 'INR' })}>INR ₹</button><button className={user.currency === 'USD' ? 'selected' : ''} onClick={() => save({ currency: 'USD' })}>USD $</button></div></div>
      <div className="settings-row"><div><strong>Monthly budget</strong><small>Used for “remaining budget” on your overview. Leave empty or 0 to clear.</small></div>
        <div className="inline-form"><input type="number" min="0" value={budget} onChange={(e) => setBudget(e.target.value)} placeholder="e.g. 38000" /><button className="secondary" onClick={() => save({ monthly_budget: Number(budget) || 0 })}>Save</button></div></div>
      <div className="settings-row"><div><strong>Name</strong><small>{user.email}</small></div>
        <div className="inline-form"><input value={name} onChange={(e) => setName(e.target.value)} maxLength={120} /><button className="secondary" onClick={() => save({ name })}>Save</button></div></div>
      <div className="settings-row"><div><strong>Sample data</strong><small>Synthetic expenses, bank accounts and crypto wallet for exploring the app. Clearing it never touches your own entries.</small></div><button className="secondary" disabled={demoBusy} onClick={() => toggleDemo(!demo)}>{demo ? 'Clear sample data' : 'Load sample data'}</button></div>
      <div className="settings-row"><div><strong>Sign out</strong><small>End this session on this device</small></div><button className="secondary" onClick={onLogout}>Sign out</button></div>
    </Card>
    {msg && <div className="notice">{msg}</div>}
    <ErrorNote error={error} />
  </>;
}
