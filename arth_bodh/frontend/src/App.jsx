import { useCallback, useEffect, useState } from 'react';
import { api, hasSession, getStoredUser, logout } from './api';
import { setFxRate } from './ui';
import Auth from './Auth';
import Dashboard from './pages/Dashboard';
import Funds from './pages/Funds';
import Expenses, { ExpenseModal } from './pages/Expenses';
import OCR from './pages/OCR';
import AI from './pages/AI';
import Analytics from './pages/Analytics';
import Settings from './pages/Settings';
import { Wallet, Assets, Transactions, Portfolio, Security } from './pages/Crypto';

const nav = [
  ['dashboard', 'Overview', '⌂'],
  ['funds', 'Funds', '₹'],
  ['expenses', 'Expenses', '↘'],
  ['ocr', 'Receipt OCR', '▧'],
  ['ai', 'AI Assistant', '✦'],
  ['analytics', 'Analytics', '◔'],
  ['wallet', 'Wallet', '◇'],
  ['assets', 'Assets', '◈'],
  ['transactions', 'Transactions', '↕'],
  ['portfolio', 'Portfolio', '◒'],
  ['security', 'Security', '✓'],
  ['settings', 'Settings', '⚙'],
];
const RAKSHA_PAGES = ['wallet', 'assets', 'transactions', 'portfolio', 'security'];

export default function App() {
  const [user, setUser] = useState(hasSession() ? getStoredUser() : null);
  useEffect(() => {
    const onLogout = () => setUser(null);
    window.addEventListener('arth-logout', onLogout);
    return () => window.removeEventListener('arth-logout', onLogout);
  }, []);
  if (!user) return <Auth onAuthed={setUser} />;
  return <Shell user={user} setUser={setUser} onLogout={() => { logout(); setUser(null); }} />;
}

function Shell({ user, setUser, onLogout }) {
  const [page, setPage] = useState('dashboard');
  const [dark, setDark] = useState(localStorage.getItem('arth-theme') === 'dark');
  const [modal, setModal] = useState(null);          // null | {expense?: row}
  const [search, setSearch] = useState('');
  const [data, setData] = useState({ expenses: [], summary: null, accounts: null, demo: false, loading: true, error: null });
  const [wallets, setWallets] = useState([]);
  const [walletId, setWalletId] = useState(null);
  const [crypto, setCrypto] = useState({ data: null, loading: true, error: null });
  const [demoBusy, setDemoBusy] = useState(false);
  const currency = user.currency || 'INR';
  const language = user.language || 'English';

  useEffect(() => { document.documentElement.classList.toggle('dark', dark); localStorage.setItem('arth-theme', dark ? 'dark' : 'light'); }, [dark]);

  const reload = useCallback(async () => {
    try {
      const [list, summary, accounts, demo] = await Promise.all([
        api.get('/expenses?limit=500'), api.get('/expenses/summary'), api.get('/bank/accounts'), api.get('/demo/status'),
      ]);
      setData({ expenses: list.items, summary, accounts, demo: demo.active, loading: false, error: null });
    } catch (e) {
      setData((d) => ({ ...d, loading: false, error: e.message }));
    }
  }, []);
  useEffect(() => { reload(); }, [reload]);

  // Crypto loads on its own (reading a blockchain can be slow) so it never blocks the rest of the app.
  const loadWallets = useCallback(async () => {
    try { setWallets((await api.get('/crypto/wallets')).wallets); } catch { /* shown via overview error */ }
  }, []);
  const loadCrypto = useCallback(async (refresh = false) => {
    setCrypto((c) => ({ ...c, loading: true, error: null }));
    try {
      const q = new URLSearchParams();
      if (walletId) q.set('wallet_id', walletId);
      if (refresh) q.set('refresh', 'true');
      const d = await api.get(`/crypto/overview?${q}`);
      setCrypto({ data: d.connected === false ? null : d, loading: false, error: null });
    } catch (e) {
      setCrypto({ data: null, loading: false, error: e.message });
      if (/not found/i.test(e.message)) setWalletId(null);
    }
  }, [walletId]);
  useEffect(() => { loadWallets(); }, [loadWallets, data.demo]);
  useEffect(() => { loadCrypto(); }, [loadCrypto, wallets.length, data.demo]);

  async function toggleDemo(load) {
    setDemoBusy(true);
    try { await (load ? api.post('/demo/seed') : api.del('/demo')); await reload(); }
    catch (e) { setData((d) => ({ ...d, error: e.message })); }
    finally { setDemoBusy(false); }
  }

  // Live INR->USD rate, only needed when the user prefers USD.
  useEffect(() => {
    if (currency !== 'USD') { setFxRate(null); return; }
    api.get('/meta/fx').then((r) => { setFxRate(r.usd_per_inr); setData((d) => ({ ...d })); }).catch(() => setFxRate(null));
  }, [currency]);

  const title = nav.find((x) => x[0] === page)?.[1] || 'Overview';
  const shared = { summary: data.summary, accounts: data.accounts, loading: data.loading, error: data.error, reload, currency };
  const cryptoProps = { crypto: crypto.data, state: crypto, reload: () => loadCrypto(true), wallets, walletId, setWalletId, refreshWallets: loadWallets, currency };
  const emptyAccount = !data.loading && !data.demo && !data.expenses.length && !data.accounts?.accounts?.length;
  const initials = (user.name || user.email || '?').split(/[\s@]+/).map((p) => p[0]).slice(0, 2).join('').toUpperCase();

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark">A</div><div><strong>ArthDrishti</strong><span>wealth, understood.</span></div></div>
      <div className="nav-group"><small>ARTH BODH</small>{nav.slice(0, 6).map(([id, label, icon]) => <button className={page === id ? 'nav-item active' : 'nav-item'} onClick={() => setPage(id)} key={id}><b>{icon}</b>{label}</button>)}</div>
      <div className="nav-group"><small>ARTH RAKSHA</small>{nav.slice(6, 11).map(([id, label, icon]) => <button className={page === id ? 'nav-item active' : 'nav-item'} onClick={() => setPage(id)} key={id}><b>{icon}</b>{label}</button>)}</div>
      <div className="nav-bottom"><button className={page === 'settings' ? 'nav-item active' : 'nav-item'} onClick={() => setPage('settings')}><b>⚙</b>Settings</button><div className="safe-note">● Signed in<br /><span>Your data is private to your account.</span></div></div>
    </aside>
    <main className="main">
      <header className="topbar"><div><p className="eyebrow">{RAKSHA_PAGES.includes(page) ? 'ARTH RAKSHA' : 'ARTH BODH'}</p><h1>{language === 'हिंदी' && page === 'dashboard' ? 'आपका वित्तीय डैशबोर्ड' : title}</h1></div><div className="top-actions"><button className="icon-btn" onClick={() => setDark(!dark)}>{dark ? '☀' : '◐'}</button><button className="profile" onClick={() => setPage('settings')} title={user.email}>{initials}</button></div></header>
      <div className="content">
        {data.demo && <div className="notice">You're viewing <b>sample data</b> (synthetic expenses, bank accounts and crypto wallet) so you can explore the app. <button className="link" disabled={demoBusy} onClick={() => toggleDemo(false)}>{demoBusy ? 'Working…' : 'Clear sample data'}</button></div>}
        {emptyAccount && <div className="notice">Your account is empty. <button className="link" disabled={demoBusy} onClick={() => toggleDemo(true)}>{demoBusy ? 'Loading…' : 'Load sample data'}</button> to explore every page, or start adding your own.</div>}
        {page === 'dashboard' && <Dashboard setPage={setPage} {...shared} crypto={crypto.data} security={crypto.data?.security && { risk_label: crypto.data.security.risk_label, approvals: crypto.data.security.approvals ?? 0 }} />}
        {page === 'funds' && <Funds {...shared} />}
        {page === 'expenses' && <Expenses expenses={data.expenses} loading={data.loading} error={data.error} reload={reload} search={search} setSearch={setSearch} onAdd={() => setModal({})} onEdit={(e) => setModal({ expense: e })} currency={currency} />}
        {page === 'ocr' && <OCR onSaved={reload} />}
        {page === 'ai' && <AI language={language} />}
        {page === 'analytics' && <Analytics {...shared} />}
        {page === 'wallet' && <Wallet {...cryptoProps} />}
        {page === 'assets' && <Assets {...cryptoProps} />}
        {page === 'transactions' && <Transactions {...cryptoProps} />}
        {page === 'portfolio' && <Portfolio {...cryptoProps} />}
        {page === 'security' && <Security {...cryptoProps} />}
        {page === 'settings' && <Settings user={user} setUser={setUser} dark={dark} setDark={setDark} onLogout={onLogout} demo={data.demo} demoBusy={demoBusy} toggleDemo={toggleDemo} />}
      </div>
    </main>
    {modal && <ExpenseModal expense={modal.expense} onClose={() => setModal(null)} onSaved={() => { setModal(null); reload(); }} />}
  </div>;
}
