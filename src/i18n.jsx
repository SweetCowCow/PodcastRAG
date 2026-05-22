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

const UI_STRINGS = {
  empty_shows_admin_cta: {
    zh: '前往後台管理節目',
    en: 'Go to admin show management',
  },
  empty_shows_member_hint: {
    zh: '目前尚無節目，請聯絡管理員加入節目',
    en: 'No shows yet — please contact an administrator to add one',
  },
  // ─── landing-and-mode-orchestration-redesign: Lock card v2 (anonymous / quota_exhausted) ───
  // 文案定版來自 design.md 決策 3。zh / en 語意對齊；無「免費」「N 次」「重置」「自動恢復」字眼。
  lockcard_anon_emoji: { zh: '🔒', en: '🔒' },
  lockcard_anon_title: {
    zh: '不想花時間重聽找答案？',
    en: 'Tired of re-listening to find the answer?',
  },
  lockcard_anon_body: {
    zh: '登入後直接針對節目內容發問，自動為你交叉比對，整理重點回覆',
    en: 'Sign in to ask the show directly — answers are cross-referenced and summarized for you.',
  },
  lockcard_anon_cta: {
    zh: '以 Google 登入',
    en: 'Sign in with Google',
  },
  lockcard_anon_secondary_prefix: { zh: '或先用', en: 'Or try ' },
  lockcard_anon_secondary_link: { zh: '語意搜尋', en: 'semantic search' },
  lockcard_anon_secondary_suffix: { zh: '找找看相關片段', en: ' first to find related segments.' },
  lockcard_quota_emoji: { zh: '⏳', en: '⏳' },
  lockcard_quota_title: {
    zh: '已達使用上限',
    en: 'You’ve reached the usage limit',
  },
  lockcard_quota_body: {
    zh: '如果還需要繼續用，可以說明用途申請額度',
    en: 'If you still need it, tell us your use case to request more.',
  },
  lockcard_quota_cta: {
    zh: '申請更多次數',
    en: 'Request more usage',
  },
  // Re-use anon_secondary_* for the「先用語意搜尋找找看相關片段」link in both states.
  // Mode tabs
  mode_tab_index: { zh: '索引', en: 'Index' },
  mode_tab_semantic: { zh: '語意', en: 'Semantic' },
  mode_tab_chat: { zh: '對話', en: 'Chat' },
  mode_index_placeholder_title: { zh: '索引模式即將推出', en: 'Index mode coming soon' },
  mode_index_placeholder_body: {
    zh: '索引模式可在節目中快速找到關鍵字命中段落。目前還在後端準備中，先試試其他兩個模式吧。',
    en: 'Index mode will surface keyword hits across the show. It is still wiring up — give the other two modes a try meanwhile.',
  },
  mode_index_try_semantic: { zh: '試試語意搜尋 →', en: 'Try semantic search →' },
  mode_index_try_chat: { zh: '試試對話查詢 →', en: 'Try chat →' },
  // Mode trio cards (HomePage 教育區)
  mode_card_index_title: { zh: '索引', en: 'Index' },
  mode_card_index_desc: {
    zh: '想知道某個關鍵字在哪幾集出現？適合查具體名詞、來賓、地點',
    en: 'Find where a keyword appears across episodes — best for names, guests, places',
  },
  mode_card_index_example: {
    zh: '例如：「黃仁勳」出現在哪幾集？',
    en: 'e.g. Which episodes mention "Jensen Huang"?',
  },
  mode_card_index_quota: { zh: '免額度', en: 'No quota' },
  mode_card_semantic_title: { zh: '語意', en: 'Semantic' },
  mode_card_semantic_desc: {
    zh: '描述問題，找出意思最相近的段落。不需要記得確切用詞',
    en: 'Describe the question; surface the closest matching segments. No exact phrasing needed.',
  },
  mode_card_semantic_example: {
    zh: '例如：他們怎麼評論 AI 泡沫？',
    en: 'e.g. What do they say about the AI bubble?',
  },
  mode_card_semantic_quota: { zh: '免額度', en: 'No quota' },
  mode_card_chat_title: { zh: '對話', en: 'Chat' },
  mode_card_chat_desc: {
    zh: '請 AI 跨集統整答案，並附上引用來源；適合需要整理重點的問題',
    en: 'Ask the AI to summarize across episodes with citations — great for synthesis questions.',
  },
  mode_card_chat_example: {
    zh: '例如：整理 2026 Q1 的半導體趨勢',
    en: 'e.g. Summarize 2026 Q1 semiconductor trends',
  },
  mode_card_chat_quota: { zh: '使用額度', en: 'Uses quota' },
  // Source panel header
  source_panel_header_zh_singular: { zh: '答案參考來源（共 ', en: 'Answer sources (' },
  // built dynamically; see ConversationSourcePanel.
};

function uiString(key, lang) {
  const m = UI_STRINGS[key];
  return m ? m[lang] || m.en : key;
}

Object.assign(window, { ERROR_MESSAGES, UI_STRINGS, formatError, networkErrorMessage, uiString });
