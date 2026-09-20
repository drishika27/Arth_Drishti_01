import { useState } from 'react';
import { api, login, register, walletLogin } from './api';
import { requestAccount, signText, hasWallet } from './wallet';

export default function Auth({ onAuthed }) {
  const [mode, setMode] = useState('login');
  const [form, setForm] = useState({ name: '', email: '', password: '' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  async function submit(e) {
    e.preventDefault();
    setBusy(true); setError('');
    try {
      const user = mode === 'login'
        ? await login(form.email, form.password)
        : await register(form.email, form.password, form.name);
      // Local development only: new accounts start with labelled sample data so nothing looks empty.
      if (mode === 'register' && import.meta.env.DEV) await api.post('/demo/seed').catch(() => {});
      onAuthed(user);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function signInWithWallet() {
    setBusy(true); setError('');
    try {
      const address = await requestAccount();
      const user = await walletLogin(address, (message) => signText(address, message));
      onAuthed(user);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return <div className="auth-shell">
    <form className="card auth-card" onSubmit={submit}>
      <div className="brand" style={{ paddingBottom: 18 }}><div className="brand-mark">A</div><div><strong>ArthDrishti</strong><span>wealth, understood.</span></div></div>
      <h2>{mode === 'login' ? 'Welcome back' : 'Create your account'}</h2>
      <p className="auth-sub">{mode === 'login' ? 'Sign in to see your money, clearly.' : 'Your data stays private to your account.'}</p>
      <button type="button" className="secondary wallet-signin" disabled={busy} onClick={signInWithWallet}>◇ Sign in with your crypto wallet</button>
      <small className="auth-sub" style={{ marginTop: -4 }}>{hasWallet() ? 'You only sign a message — no seed phrase, no private key, no gas.' : 'Needs a browser wallet such as MetaMask.'}</small>
      <div className="auth-divider"><span>or use email</span></div>
      {mode === 'register' && <input placeholder="Your name" value={form.name} onChange={set('name')} autoComplete="name" />}
      <input type="email" required placeholder="Email" value={form.email} onChange={set('email')} autoComplete="email" />
      <input type="password" required minLength={mode === 'register' ? 8 : undefined} placeholder={mode === 'register' ? 'Password (8+ characters)' : 'Password'} value={form.password} onChange={set('password')} autoComplete={mode === 'login' ? 'current-password' : 'new-password'} />
      {error && <div className="notice error">{error}</div>}
      <button className="primary" disabled={busy}>{busy ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Create account'}</button>
      <button type="button" className="link" onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); setError(''); }}>
        {mode === 'login' ? 'New here? Create an account' : 'Have an account? Sign in'}
      </button>
    </form>
  </div>;
}
