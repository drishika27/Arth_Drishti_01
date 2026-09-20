import { useEffect, useState } from 'react';

// Currency display. INR is the base currency; USD uses a live rate fetched
// from the backend (/meta/fx). If no rate is available we keep showing INR
// rather than converting with an invented number.
let fxUsdPerInr = null;
export function setFxRate(rate) { fxUsdPerInr = rate; }

export const money = (n, currency = 'INR') => {
  const v = Number(n) || 0;
  if (currency === 'USD' && fxUsdPerInr) return `$${(v * fxUsdPerInr).toLocaleString('en-US', { maximumFractionDigits: 0 })}`;
  return `₹${v.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;
};

export const CATEGORY_COLORS = ['#6C63FF', '#00A884', '#F4A261', '#E76F51', '#F2C94C', '#4CC9F0', '#B5838D', '#90BE6D', '#577590', '#9D4EDD'];

export function Card({ children, className = '' }) { return <div className={`card ${className}`}>{children}</div>; }
export function Pill({ children, tone = 'neutral' }) { return <span className={`pill ${tone}`}>{children}</span>; }
export function Empty({ text }) { return <div className="empty">{text}</div>; }
export function Busy({ text = 'Loading…' }) { return <div className="empty">{text}</div>; }
export function ErrorNote({ error, onRetry }) {
  if (!error) return null;
  return <div className="notice error">{error}{onRetry && <button className="link" onClick={onRetry}>Retry</button>}</div>;
}

export function BarChart({ data }) {
  const max = Math.max(...data.map((x) => x.value), 1);
  return <div className="bars">{data.map((x) => <div className="bar-wrap" key={x.label}><div className="bar" style={{ height: `${Math.max(8, x.value / max * 150)}px` }} /><span>{x.label}</span></div>)}</div>;
}

export function Donut({ items, currency }) {
  const total = items.reduce((a, b) => a + b.value, 0) || 1;
  let cursor = 0;
  const stops = items.map((i) => { const start = cursor / total * 360; cursor += i.value; return `${i.color} ${start}deg ${cursor / total * 360}deg`; }).join(',');
  return <div className="donut" style={{ background: items.length ? `conic-gradient(${stops})` : 'var(--bg)' }}><div className="donut-hole"><strong>{money(items.reduce((a, b) => a + b.value, 0), currency)}</strong><small>this month</small></div></div>;
}

/** Runs an async loader on mount / when deps change, exposing loading + error + reload. */
export function useLoad(loader, deps = []) {
  const [state, setState] = useState({ data: null, loading: true, error: null });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    setState((s) => ({ ...s, loading: true, error: null }));
    loader().then(
      (data) => alive && setState({ data, loading: false, error: null }),
      (e) => alive && setState({ data: null, loading: false, error: e.message || 'Something went wrong.' }),
    );
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  return { ...state, reload: () => setTick((t) => t + 1) };
}
