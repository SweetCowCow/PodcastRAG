// AuthContext — exposes `apiFetch`, `useCurrentUser`, `googleLoginUrl` globally.
// All fetch traffic to backend SHOULD go through `apiFetch` so cookies and CSRF
// header are handled uniformly. Public endpoints can still use raw fetch but
// will not get credentials injected.

const _API_BASE = (typeof window !== 'undefined' && window.__API_BASE__) || 'http://localhost:8000';

const UNSAFE_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

function _getCookie(name) {
  const m = document.cookie.match(new RegExp('(?:^|; )' + name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '=([^;]*)'));
  return m ? decodeURIComponent(m[1]) : null;
}

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
    const csrf = _getCookie('csrf_token');
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
        setUser(body);
      } else if (res.status === 401) {
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
