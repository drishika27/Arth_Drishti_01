// API client for the ArthDrishti backend.
// Handles user sessions (access + refresh tokens), attaches the bearer token,
// refreshes it once on a 401, and turns every failure into a readable ApiError.
// No API keys live in the frontend bundle — users sign in with an account.
export const API = import.meta.env.VITE_ARTH_BODH_API || "http://localhost:8001";

const STORAGE_KEY = "arth-session";

let session = (() => {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEY)); } catch { return null; }
})();

function saveSession(s) {
  session = s;
  if (s) localStorage.setItem(STORAGE_KEY, JSON.stringify(s));
  else localStorage.removeItem(STORAGE_KEY);
}

export const hasSession = () => !!session?.access_token;
export const getStoredUser = () => session?.user || null;

export class ApiError extends Error {
  constructor(message, status = 0, retryable = false) {
    super(message);
    this.status = status;
    this.retryable = retryable;
  }
}

async function toError(res) {
  let message = `Request failed (${res.status})`;
  let retryable = res.status >= 500;
  try {
    const body = await res.json();
    const d = body.detail;
    if (typeof d === "string") message = d;
    else if (Array.isArray(d)) message = d.map((x) => x.msg?.replace(/^Value error, /, "")).filter(Boolean).join("; ") || message;
    else if (d && typeof d === "object") { message = d.message || message; retryable = d.retryable ?? retryable; }
  } catch { /* non-JSON error body */ }
  return new ApiError(message, res.status, retryable);
}

async function rawFetch(path, options) {
  try {
    return await fetch(`${API}${path}`, options);
  } catch {
    throw new ApiError("Can't reach the server. Check your connection and try again.", 0, true);
  }
}

async function refreshTokens() {
  if (!session?.refresh_token) return false;
  const res = await rawFetch("/auth/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: session.refresh_token }),
  }).catch(() => null);
  if (!res || !res.ok) return false;
  const t = await res.json();
  saveSession({ ...session, access_token: t.access_token, refresh_token: t.refresh_token });
  return true;
}

function expireSession() {
  saveSession(null);
  window.dispatchEvent(new Event("arth-logout"));
}

/** Low-level: returns the Response (used by the AI chat and file uploads). */
export async function apiFetch(path, options = {}) {
  const send = () => rawFetch(path, {
    ...options,
    headers: { ...(options.headers || {}), ...(session ? { Authorization: `Bearer ${session.access_token}` } : {}) },
  });
  let res = await send();
  if (res.status === 401 && session && (await refreshTokens())) res = await send();
  if (res.status === 401 && session) expireSession();
  return res;
}

async function request(path, options) {
  const res = await apiFetch(path, options);
  if (!res.ok) throw await toError(res);
  return res.status === 204 ? null : res.json();
}

const jsonInit = (method, body) => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: body === undefined ? undefined : JSON.stringify(body),
});

export const api = {
  get: (path) => request(path),
  post: (path, body) => request(path, jsonInit("POST", body)),
  patch: (path, body) => request(path, jsonInit("PATCH", body)),
  del: (path) => request(path, { method: "DELETE" }),
  upload: (path, formData) => request(path, { method: "POST", body: formData }),
};

// ---- account -------------------------------------------------------------
async function authenticate(path, body) {
  const res = await rawFetch(path, jsonInit("POST", body));
  if (!res.ok) throw await toError(res);
  const data = await res.json();
  saveSession({ access_token: data.access_token, refresh_token: data.refresh_token, user: data.user });
  return data.user;
}

export const login = (email, password) => authenticate("/auth/login", { email, password });
export const register = (email, password, name) => authenticate("/auth/register", { email, password, name });
export const logout = () => saveSession(null);
export function updateStoredUser(user) { if (session) saveSession({ ...session, user }); }
