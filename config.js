// Runtime config — loaded before all JSX scripts.
// Local dev: defaults to http://localhost:8000.
// Production (Zeabur): overwrite window.__API_BASE__ with the deployed backend URL
// (no trailing slash), e.g. window.__API_BASE__ = 'https://api-xxx.zeabur.app';
window.__API_BASE__ = 'http://localhost:8000';
