// Runtime config — loaded before all JSX scripts.
// Auto-detects environment based on hostname:
//   localhost / 127.0.0.1 → local backend
//   anywhere else (Zeabur, custom domain) → production backend
(function () {
  const host = window.location.hostname;
  const isLocal = host === 'localhost' || host === '127.0.0.1' || host === '';
  window.__API_BASE__ = isLocal
    ? 'http://localhost:8000'
    : 'https://api.podcastrag.app';
})();
