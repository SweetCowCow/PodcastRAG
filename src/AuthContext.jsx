// AuthContext — exposes `apiFetch`, `useCurrentUser`, `googleLoginUrl` globally.
// All fetch traffic to backend SHOULD go through `apiFetch` so cookies and CSRF
// header are handled uniformly. Public endpoints can still use raw fetch but
// will not get credentials injected.

const _API_BASE = (typeof window !== 'undefined' && window.__API_BASE__) || 'http://localhost:8000';

const UNSAFE_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

// CSRF token cached in module memory. Populated from /me response body
// (synchronizer-token pattern). The backend's csrf cookie cannot be read
// across subdomains, so we don't rely on document.cookie at all.
let _csrfToken = null;
function _setCsrfToken(t) { _csrfToken = t || null; }
function _getCsrfToken() { return _csrfToken; }

const _authListeners = new Set();
function _notifyAuthChange() {
  for (const fn of _authListeners) {
    try { fn(); } catch (_) {}
  }
}

async function apiFetch(path, opts = {}) {
  const url = path.startsWith('http') ? path : `${_API_BASE}${path}`;
  const method = (opts.method || 'GET').toUpperCase();
  const headers = new Headers(opts.headers || {});

  if (UNSAFE_METHODS.has(method)) {
    const csrf = _getCsrfToken();
    if (csrf) headers.set('X-CSRF-Token', csrf);
  }
  if (opts.body && !headers.has('Content-Type') && typeof opts.body === 'string') {
    headers.set('Content-Type', 'application/json');
  }

  const res = await fetch(url, {
    ...opts,
    method,
    headers,
    credentials: 'include',
  });

  if (res.status === 401) {
    // session expired or never authenticated — clear local state and notify.
    _notifyAuthChange();
  }
  return res;
}

const googleLoginUrl = () => `${_API_BASE}/auth/google/start`;

async function logout() {
  try {
    await apiFetch('/auth/logout', { method: 'POST' });
  } finally {
    _setCsrfToken(null);
    _notifyAuthChange();
  }
}

// React hook: load and expose current user from /me. Returns
// { user, loading, refresh, logout, error } where user is null when not logged in.
function useCurrentUser() {
  const [user, setUser] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState(null);

  const refresh = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await apiFetch('/me');
      if (res.status === 200) {
        const body = await res.json();
        _setCsrfToken(body.csrf_token);
        setUser(body);
      } else if (res.status === 401) {
        _setCsrfToken(null);
        setUser(null);
      } else {
        setError(`HTTP ${res.status}`);
        setUser(null);
      }
    } catch (e) {
      setError(String(e));
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    refresh();
    const listener = () => refresh();
    _authListeners.add(listener);
    return () => _authListeners.delete(listener);
  }, [refresh]);

  const doLogout = React.useCallback(async () => {
    await logout();
    setUser(null);
  }, []);

  return { user, loading, error, refresh, logout: doLogout };
}

Object.assign(window, { apiFetch, useCurrentUser, googleLoginUrl, logout });
