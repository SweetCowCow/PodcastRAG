// Error message i18n map. Keys MUST stay in sync with backend ErrorCode constants
// in backend/app/schemas/errors.py.
const ERROR_MESSAGES = {
  llm_quota_exceeded: {
    zh: (p) => `${p || 'LLM'} 配額不足，請至${p === 'Zeabur AI Hub' ? ' Zeabur ' : ' OpenAI '}後台檢查餘額`,
    en: (p) => `${p || 'LLM'} quota exceeded — check your account balance`,
  },
  llm_rate_limited: {
    zh: (p) => `${p || 'LLM'} 速率限制，請稍候再試`,
    en: (p) => `${p || 'LLM'} rate limit reached — please retry shortly`,
  },
  llm_auth_failed: {
    zh: (p) => `${p || 'LLM'} API 金鑰失效，請至後台更新`,
    en: (p) => `${p || 'LLM'} API key invalid — update it in admin`,
  },
  llm_unavailable: {
    zh: (p) => `無法連線至 ${p || 'LLM'}，請稍後重試`,
    en: (p) => `Cannot reach ${p || 'LLM'} — please retry later`,
  },
  llm_not_configured: {
    zh: () => 'LLM 尚未在後台設定',
    en: () => 'LLM is not configured in admin',
  },
  rss_timeout: {
    zh: () => 'RSS Feed 逾時',
    en: () => 'RSS feed timed out',
  },
  rss_invalid: {
    zh: () => 'RSS Feed 格式錯誤',
    en: () => 'RSS feed is invalid',
  },
  show_duplicate_rss: {
    zh: () => '此 RSS URL 已註冊',
    en: () => 'RSS URL already registered',
  },
  internal_error: {
    zh: () => '伺服器內部錯誤，請稍後重試',
    en: () => 'Internal server error — please retry later',
  },
  not_authenticated: {
    zh: () => '請先登入',
    en: () => 'Please sign in',
  },
  forbidden: {
    zh: () => '權限不足',
    en: () => 'Permission denied',
  },
  csrf_token_missing: {
    zh: () => '安全驗證失敗（CSRF token 缺失），請重新整理頁面',
    en: () => 'Security check failed (CSRF token missing) — refresh the page',
  },
  csrf_token_invalid: {
    zh: () => '安全驗證失敗（CSRF token 不符），請重新整理頁面',
    en: () => 'Security check failed (CSRF token invalid) — refresh the page',
  },
  origin_missing: {
    zh: () => '請求來源驗證失敗',
    en: () => 'Origin validation failed',
  },
  origin_forbidden: {
    zh: () => '請求來源不被允許',
    en: () => 'Origin not allowed',
  },
  account_disabled: {
    zh: () => '帳號已停用，請聯絡管理員',
    en: () => 'Account is disabled — contact administrator',
  },
  invalid_oauth_state: {
    zh: () => '登入流程驗證失敗，請重新登入',
    en: () => 'OAuth state invalid — please sign in again',
  },
  quota_exhausted: {
    zh: () => '查詢額度已用完，請聯絡管理員加值',
    en: () => 'Query quota exhausted — contact admin to top up',
  },
};

function formatError(errorBody, lang) {
  const d = errorBody && errorBody.detail;
  if (d && typeof d === 'object' && d.error_code) {
    const map = ERROR_MESSAGES[d.error_code];
    if (map && map[lang]) return map[lang](d.provider || '');
    return d.detail || (lang === 'zh' ? '未知錯誤' : 'Unknown error');
  }
  if (typeof d === 'string') return d;
  return lang === 'zh' ? '請求失敗' : 'Request failed';
}

function networkErrorMessage(lang) {
  return lang === 'zh' ? '網路連線失敗，請檢查網路' : 'Network error — check your connection';
}

Object.assign(window, { ERROR_MESSAGES, formatError, networkErrorMessage });
