// Thin fetch wrapper that transparently handles the backend's auth
// (shared_engine/auth.py): fetches a bearer token once (cached until
// shortly before it expires) and attaches it to every request.
export const API = import.meta.env.VITE_ARTH_BODH_API || "http://localhost:8001";
const API_KEY = import.meta.env.VITE_API_KEY || "dev-local-key-not-for-production";

let cachedToken = null;
let tokenExpiresAt = 0;

async function getToken() {
  if (cachedToken && Date.now() < tokenExpiresAt) return cachedToken;
  const res = await fetch(`${API}/auth/token`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ api_key: API_KEY }),
  });
  if (!res.ok) {
    throw new Error(
      "Could not authenticate with the Arth Bodh API. Check VITE_API_KEY matches a key " +
      "the backend accepts (ARTHDRISHTI_API_KEYS), or that the backend is running."
    );
  }
  const data = await res.json();
  cachedToken = data.access_token;
  tokenExpiresAt = Date.now() + (data.expires_in - 60) * 1000; // refresh a minute early
  return cachedToken;
}

export async function apiFetch(path, options = {}) {
  const token = await getToken();
  const headers = { ...(options.headers || {}), Authorization: `Bearer ${token}` };
  return fetch(`${API}${path}`, { ...options, headers });
}
