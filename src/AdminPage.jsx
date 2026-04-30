// Admin Page — API Keys, LLM, RAG Config, Transcription Schedule
const AdminPage = ({ lang, activePage }) => {
  const t = lang === 'zh';
  const pages = {
    'admin-api': <ApiKeysTab lang={lang} />,
    'admin-llm': <LLMTab lang={lang} />,
    'admin-rag': <RAGTab lang={lang} />,
    'admin-schedule': <ScheduleTab lang={lang} />,
    'admin-queue': <QueueTab lang={lang} />,
    'admin-external-api': <ExternalApiStatusTab lang={lang} />,
  };
  return (
    <div style={{ flex: 1, overflowY: 'auto', background: TOKEN.bg }}>
      <div style={{ padding: '32px 40px 16px', borderBottom: `1px solid ${TOKEN.surfaceBorder}`, background: TOKEN.surface }}>
        <p style={{ color: TOKEN.accent, fontSize: 12, fontWeight: 600, letterSpacing: '0.1em', textTransform: 'uppercase', margin: '0 0 4px' }}>{t ? '後台管理' : 'Administration'}</p>
        <h1 style={{ color: TOKEN.text, fontSize: 24, fontWeight: 700, margin: 0 }}>
          {{ 'admin-api': t ? 'API 金鑰管理' : 'API Key Management', 'admin-llm': t ? 'LLM 模型設定' : 'LLM Model Settings', 'admin-rag': t ? 'RAG 參數設定' : 'RAG Configuration', 'admin-schedule': t ? '轉錄排程管理' : 'Transcription Schedule', 'admin-queue': t ? '轉錄序列' : 'Transcription Queue', 'admin-external-api': t ? '外部 API 狀態' : 'External API Status' }[activePage]}
        </h1>
      </div>
      <div style={{ padding: '28px 40px 40px' }}>{pages[activePage]}</div>
    </div>
  );
};

// ── API Keys Tab ──
const ApiKeysTab = ({ lang }) => {
  const t = lang === 'zh';
  const [keys, setKeys] = React.useState([
    { id: 1, provider: 'OpenAI', key: 'sk-proj-••••••••••••••••••••••••••••••XYZ1', active: true, model: 'gpt-4o', added: '2026-03-01' },
    { id: 2, provider: 'Anthropic', key: 'sk-ant-api03-••••••••••••••••••••ABC2', active: true, model: 'claude-opus-4-5', added: '2026-03-15' },
    { id: 3, provider: 'Google', key: 'AIza••••••••••••••••••••••••••••GHI3', active: false, model: 'gemini-2.5-pro', added: '2026-04-01' },
    { id: 4, provider: 'AI Hub', key: 'hub-••••••••••••••••••••••••••••JKL4', active: true, model: 'zeabur-llm-v2', added: '2026-04-10' },
  ]);
  const [showKey, setShowKey] = React.useState({});
  const [adding, setAdding] = React.useState(false);
  const [newKey, setNewKey] = React.useState({ provider: 'OpenAI', key: '' });

  const providerColors = { OpenAI: '#22c55e', Anthropic: '#f59e0b', Google: '#6366f1', 'AI Hub': '#22d3ee' };

  return (
    <div style={{ maxWidth: 760 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <p style={{ margin: 0, color: TOKEN.textSecondary, fontSize: 14 }}>{t ? '管理各 LLM 供應商的 API 金鑰，金鑰以加密方式儲存。' : 'Manage API keys for LLM providers. Keys are stored encrypted.'}</p>
        <Btn icon="plus" onClick={() => setAdding(true)} size="sm">{t ? '新增金鑰' : 'Add Key'}</Btn>
      </div>

      {adding && (
        <div style={{ background: TOKEN.surface, border: `1px solid ${TOKEN.accent + '55'}`, borderRadius: 12, padding: 20, marginBottom: 20 }}>
          <p style={{ color: TOKEN.text, fontWeight: 600, fontSize: 14, margin: '0 0 14px' }}>{t ? '新增 API 金鑰' : 'Add API Key'}</p>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: 12, marginBottom: 14 }}>
            <div>
              <label style={{ display: 'block', color: TOKEN.textMuted, fontSize: 12, marginBottom: 5 }}>{t ? '供應商' : 'Provider'}</label>
              <select value={newKey.provider} onChange={e => setNewKey(k => ({ ...k, provider: e.target.value }))}
                style={{ width: '100%', background: TOKEN.surfaceRaised, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 8, padding: '9px 12px', color: TOKEN.text, fontSize: 14, outline: 'none', fontFamily: 'inherit' }}>
                {['OpenAI', 'Anthropic', 'Google', 'AI Hub'].map(p => <option key={p} value={p}>{p}</option>)}
              </select>
            </div>
            <div>
              <label style={{ display: 'block', color: TOKEN.textMuted, fontSize: 12, marginBottom: 5 }}>{t ? 'API 金鑰' : 'API Key'}</label>
              <Input value={newKey.key} onChange={e => setNewKey(k => ({ ...k, key: e.target.value }))} placeholder="sk-..." />
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <Btn size="sm" onClick={() => { setKeys(ks => [...ks, { id: Date.now(), ...newKey, active: true, model: '-', added: '2026-04-19' }]); setAdding(false); setNewKey({ provider: 'OpenAI', key: '' }); }}>{t ? '儲存' : 'Save'}</Btn>
            <Btn size="sm" variant="ghost" onClick={() => setAdding(false)}>{t ? '取消' : 'Cancel'}</Btn>
          </div>
        </div>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {keys.map(k => (
          <div key={k.id} style={{ background: TOKEN.surface, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 12, padding: '16px 20px', display: 'flex', alignItems: 'center', gap: 16 }}>
            <div style={{ width: 8, height: 8, borderRadius: '50%', background: k.active ? '#22c55e' : TOKEN.textMuted, flexShrink: 0 }} />
            <div style={{ width: 72, fontSize: 13, fontWeight: 600, color: providerColors[k.provider] || TOKEN.accent }}>{k.provider}</div>
            <div style={{ flex: 1, fontFamily: 'monospace', fontSize: 13, color: TOKEN.textSecondary }}>
              {showKey[k.id] ? k.key : k.key.replace(/(?<=.{8}).(?=.{6})/g, '•')}
            </div>
            <div style={{ fontSize: 12, color: TOKEN.textMuted, minWidth: 110 }}>{k.model}</div>
            <div style={{ fontSize: 12, color: TOKEN.textMuted, minWidth: 80 }}>{k.added}</div>
            <div style={{ display: 'flex', gap: 6 }}>
              <Btn size="sm" variant="ghost" icon={showKey[k.id] ? 'eyeOff' : 'eye'} onClick={() => setShowKey(s => ({ ...s, [k.id]: !s[k.id] }))} />
              <Btn size="sm" variant="ghost" icon="trash" onClick={() => setKeys(ks => ks.filter(x => x.id !== k.id))} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

// ── LLM Tab ──
const MASKED_KEY = '***';

const LLMTab = ({ lang }) => {
  const t = lang === 'zh';
  const [form, setForm] = React.useState({
    answer_base_url: '', answer_api_key: '', answer_model: '',
    rewrite_base_url: '', rewrite_api_key: '', rewrite_model: '',
  });
  const [apiKeyTouched, setApiKeyTouched] = React.useState({ answer_api_key: false, rewrite_api_key: false });
  const [loading, setLoading] = React.useState(true);
  const [saving, setSaving] = React.useState(false);
  const [message, setMessage] = React.useState(null);

  const loadConfig = React.useCallback(async () => {
    setLoading(true);
    setMessage(null);
    try {
      const res = await fetch(`${API_BASE}/admin/llm-config`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setForm({
        answer_base_url: data.answer_base_url || '',
        answer_api_key: data.answer_api_key || '',
        answer_model: data.answer_model || '',
        rewrite_base_url: data.rewrite_base_url || '',
        rewrite_api_key: data.rewrite_api_key || '',
        rewrite_model: data.rewrite_model || '',
      });
      setApiKeyTouched({ answer_api_key: false, rewrite_api_key: false });
    } catch (err) {
      setMessage({ kind: 'error', text: (t ? '載入失敗：' : 'Load failed: ') + err.message });
    } finally {
      setLoading(false);
    }
  }, [t]);

  React.useEffect(() => { loadConfig(); }, [loadConfig]);

  const setField = (key) => (e) => {
    const value = e.target.value;
    setForm(f => ({ ...f, [key]: value }));
    if (key === 'answer_api_key' || key === 'rewrite_api_key') {
      setApiKeyTouched(s => ({ ...s, [key]: true }));
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setMessage(null);
    const payload = {
      answer_base_url: form.answer_base_url,
      answer_model: form.answer_model,
      rewrite_base_url: form.rewrite_base_url,
      rewrite_model: form.rewrite_model,
    };
    if (apiKeyTouched.answer_api_key && form.answer_api_key !== MASKED_KEY) {
      payload.answer_api_key = form.answer_api_key;
    }
    if (apiKeyTouched.rewrite_api_key && form.rewrite_api_key !== MASKED_KEY) {
      payload.rewrite_api_key = form.rewrite_api_key;
    }
    try {
      const res = await fetch(`${API_BASE}/admin/llm-config`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const detail = await res.text();
        throw new Error(detail || `HTTP ${res.status}`);
      }
      const data = await res.json();
      setForm({
        answer_base_url: data.answer_base_url || '',
        answer_api_key: data.answer_api_key || '',
        answer_model: data.answer_model || '',
        rewrite_base_url: data.rewrite_base_url || '',
        rewrite_api_key: data.rewrite_api_key || '',
        rewrite_model: data.rewrite_model || '',
      });
      setApiKeyTouched({ answer_api_key: false, rewrite_api_key: false });
      setMessage({ kind: 'success', text: t ? '已儲存' : 'Saved' });
    } catch (err) {
      setMessage({ kind: 'error', text: (t ? '儲存失敗：' : 'Save failed: ') + err.message });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ maxWidth: 760 }}>
      <p style={{ margin: '0 0 18px', color: TOKEN.textSecondary, fontSize: 14 }}>
        {t ? '設定 Answer 與 Rewrite 兩個 LLM，後台儲存於 llm_config 單列資料表。' : 'Configure the Answer and Rewrite LLMs (stored in the singleton llm_config row).'}
      </p>

      {loading ? (
        <div style={{ color: TOKEN.textMuted, padding: '24px 0' }}>{t ? '載入中...' : 'Loading...'}</div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <LLMConfigSection title={t ? 'Answer 模型（回答）' : 'Answer Model'} lang={lang}
            baseUrl={form.answer_base_url} onBaseUrl={setField('answer_base_url')}
            apiKey={form.answer_api_key} onApiKey={setField('answer_api_key')}
            model={form.answer_model} onModel={setField('answer_model')} />
          <LLMConfigSection title={t ? 'Rewrite 模型（查詢改寫）' : 'Rewrite Model'} lang={lang}
            baseUrl={form.rewrite_base_url} onBaseUrl={setField('rewrite_base_url')}
            apiKey={form.rewrite_api_key} onApiKey={setField('rewrite_api_key')}
            model={form.rewrite_model} onModel={setField('rewrite_model')} />

          {message && (
            <div style={{ padding: '9px 13px', borderRadius: 8, fontSize: 13,
              background: message.kind === 'success' ? 'rgba(34,197,94,0.12)' : 'rgba(239,68,68,0.12)',
              border: `1px solid ${message.kind === 'success' ? 'rgba(34,197,94,0.3)' : 'rgba(239,68,68,0.3)'}`,
              color: message.kind === 'success' ? '#4ade80' : '#f87171' }}>
              {message.text}
            </div>
          )}

          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
            <Btn variant="ghost" onClick={loadConfig} disabled={saving}>{t ? '重新載入' : 'Reload'}</Btn>
            <Btn icon="check" onClick={handleSave} disabled={saving}>{saving ? (t ? '儲存中...' : 'Saving...') : (t ? '儲存設定' : 'Save Configuration')}</Btn>
          </div>
        </div>
      )}
    </div>
  );
};

const LLMConfigSection = ({ title, lang, baseUrl, onBaseUrl, apiKey, onApiKey, model, onModel }) => {
  const t = lang === 'zh';
  return (
    <div style={{ background: TOKEN.surface, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 12, padding: '18px 22px' }}>
      <p style={{ color: TOKEN.text, fontWeight: 600, fontSize: 14, margin: '0 0 14px' }}>{title}</p>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 14 }}>
        <div>
          <label style={{ display: 'block', color: TOKEN.textMuted, fontSize: 12, marginBottom: 6 }}>Base URL</label>
          <Input value={baseUrl} onChange={onBaseUrl} placeholder="https://hnd1.aihub.zeabur.ai/v1" />
        </div>
        <div>
          <label style={{ display: 'block', color: TOKEN.textMuted, fontSize: 12, marginBottom: 6 }}>Model</label>
          <Input value={model} onChange={onModel} placeholder="gpt-4o" />
        </div>
      </div>
      <div>
        <label style={{ display: 'block', color: TOKEN.textMuted, fontSize: 12, marginBottom: 6 }}>
          API Key <span style={{ color: TOKEN.textMuted }}>{t ? '（顯示 *** 時未修改則不送出）' : '(leave as *** to keep current)'}</span>
        </label>
        <Input value={apiKey} onChange={onApiKey} type="password" placeholder="sk-..." />
      </div>
    </div>
  );
};

const SliderParam = ({ label, value, min, max, step, onChange, hint }) => (
  <div>
    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
      <label style={{ color: TOKEN.textSecondary, fontSize: 13 }}>{label}</label>
      <span style={{ color: TOKEN.accent, fontSize: 13, fontWeight: 600 }}>{value}</span>
    </div>
    <input type="range" min={min} max={max} step={step} value={value} onChange={e => onChange(Number(e.target.value))}
      style={{ width: '100%', accentColor: TOKEN.accent }} />
    <p style={{ margin: '5px 0 0', color: TOKEN.textMuted, fontSize: 11 }}>{hint}</p>
  </div>
);

// ── RAG Tab ──
const RAGTab = ({ lang }) => {
  const t = lang === 'zh';
  const [cfg, setCfg] = React.useState({ chunkSize: 512, overlap: 64, topK: 5, similarity: 0.72, embedModel: 'text-embedding-3-large', rerank: true, hybridSearch: true });
  const set = (k, v) => setCfg(c => ({ ...c, [k]: v }));

  return (
    <div style={{ maxWidth: 680 }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        <Section title={t ? '文本切割設定' : 'Chunking Settings'}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
            <SliderParam label={t ? 'Chunk 大小 (tokens)' : 'Chunk Size (tokens)'} value={cfg.chunkSize} min={128} max={2048} step={64} onChange={v => set('chunkSize', v)} hint={t ? '建議 256–1024' : 'Recommended 256–1024'} />
            <SliderParam label={t ? '重疊 (Overlap)' : 'Overlap'} value={cfg.overlap} min={0} max={256} step={16} onChange={v => set('overlap', v)} hint={t ? '避免截斷語意' : 'Prevents semantic cutoff'} />
          </div>
        </Section>

        <Section title={t ? '檢索設定' : 'Retrieval Settings'}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20, marginBottom: 16 }}>
            <SliderParam label={t ? '召回數量 (Top-K)' : 'Top-K Retrieval'} value={cfg.topK} min={1} max={20} step={1} onChange={v => set('topK', v)} hint={t ? '返回最相關的 K 個段落' : 'Return K most relevant segments'} />
            <SliderParam label={t ? '相似度門檻' : 'Similarity Threshold'} value={cfg.similarity} min={0.5} max={0.99} step={0.01} onChange={v => set('similarity', v)} hint={`≥ ${cfg.similarity} ${t ? '才納入結果' : 'to include in results'}`} />
          </div>
          <div style={{ display: 'flex', gap: 20 }}>
            <ToggleParam label={t ? '重排序 (Re-ranking)' : 'Re-ranking'} value={cfg.rerank} onChange={v => set('rerank', v)} hint={t ? '使用 Cross-Encoder 精排' : 'Use Cross-Encoder for precision'} />
            <ToggleParam label={t ? '混合搜尋' : 'Hybrid Search'} value={cfg.hybridSearch} onChange={v => set('hybridSearch', v)} hint={t ? 'BM25 + 向量搜尋混合' : 'BM25 + Vector search blend'} />
          </div>
        </Section>

        <Section title={t ? '嵌入模型' : 'Embedding Model'}>
          {['text-embedding-3-large', 'text-embedding-3-small', 'text-embedding-ada-002'].map(m => (
            <label key={m} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 0', cursor: 'pointer', borderBottom: `1px solid ${TOKEN.surfaceBorder}` }}>
              <input type="radio" name="embed" checked={cfg.embedModel === m} onChange={() => set('embedModel', m)} style={{ accentColor: TOKEN.accent }} />
              <span style={{ color: TOKEN.text, fontSize: 14, fontFamily: 'monospace' }}>{m}</span>
              {m === 'text-embedding-3-large' && <Badge variant="default">{t ? '推薦' : 'Recommended'}</Badge>}
            </label>
          ))}
        </Section>

        <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
          <Btn icon="check">{t ? '儲存設定' : 'Save Configuration'}</Btn>
        </div>
      </div>
    </div>
  );
};

const Section = ({ title, children }) => (
  <div style={{ background: TOKEN.surface, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 12, padding: '18px 22px' }}>
    <p style={{ color: TOKEN.text, fontWeight: 600, fontSize: 14, margin: '0 0 16px' }}>{title}</p>
    {children}
  </div>
);

const ToggleParam = ({ label, value, onChange, hint }) => (
  <div style={{ flex: 1 }}>
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
      <label style={{ color: TOKEN.textSecondary, fontSize: 13 }}>{label}</label>
      <div onClick={() => onChange(!value)} style={{ width: 36, height: 20, borderRadius: 99, background: value ? TOKEN.accent : TOKEN.surfaceBorder, cursor: 'pointer', position: 'relative', transition: 'background 0.15s', flexShrink: 0 }}>
        <div style={{ width: 14, height: 14, borderRadius: '50%', background: '#fff', position: 'absolute', top: 3, left: value ? 19 : 3, transition: 'left 0.15s' }} />
      </div>
    </div>
    <p style={{ margin: 0, color: TOKEN.textMuted, fontSize: 11 }}>{hint}</p>
  </div>
);

// ── Schedule Tab ──
// useTranscriptionStatus: poll GET /shows/{id}/transcription-status every 5s while enabled.
// Returns { data, error }. enabled=false returns idle state (no fetch, no interval).
const useTranscriptionStatus = (showId, enabled) => {
  const [data, setData] = React.useState(null);
  const [error, setError] = React.useState(null);
  React.useEffect(() => {
    if (!enabled || !showId) return undefined;
    let cancelled = false;
    const controller = new AbortController();
    const fetchOnce = async () => {
      try {
        const res = await fetch(`${API_BASE}/shows/${showId}/transcription-status`, { signal: controller.signal });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const json = await res.json();
        if (!cancelled) { setData(json); setError(null); }
      } catch (err) {
        if (cancelled || err.name === 'AbortError') return;
        setError(err.message || String(err));
      }
    };
    fetchOnce();
    const id = setInterval(fetchOnce, 5000);
    return () => { cancelled = true; controller.abort(); clearInterval(id); };
  }, [showId, enabled]);
  return { data, error };
};

const TranscriptionProgressPanel = ({ showId, expanded, lang }) => {
  const t = lang === 'zh';
  const { data, error } = useTranscriptionStatus(showId, expanded);
  if (!expanded) return null;
  if (error && !data) {
    return (
      <div style={{ marginTop: 14, padding: 12, background: TOKEN.surfaceRaised, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 8, color: TOKEN.danger, fontSize: 12 }}>
        {(t ? '載入進度失敗：' : 'Failed to load progress: ') + error}
      </div>
    );
  }
  if (!data) {
    return (
      <div style={{ marginTop: 14, color: TOKEN.textMuted, fontSize: 12 }}>{t ? '載入中…' : 'Loading…'}</div>
    );
  }
  return (
    <div style={{ marginTop: 14, padding: '14px 16px', background: TOKEN.surfaceRaised, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 10, display: 'flex', flexDirection: 'column', gap: 14 }}>
      <ProgressCounts counts={data.counts} lang={lang} />

      <div>
        <div style={{ color: TOKEN.textMuted, fontSize: 11, fontWeight: 600, letterSpacing: '0.04em', textTransform: 'uppercase', marginBottom: 6 }}>{t ? '處理中' : 'Currently Processing'}</div>
        {data.currently_processing.length === 0 ? (
          <div style={{ color: TOKEN.textMuted, fontSize: 13 }}>{t ? '目前沒有轉錄中' : 'None currently processing'}</div>
        ) : (
          <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: 4 }}>
            {data.currently_processing.map(ep => (
              <li key={ep.episode_id} style={{ color: TOKEN.text, fontSize: 13 }}>{ep.episode_title}</li>
            ))}
          </ul>
        )}
      </div>

      <div>
        <div style={{ color: TOKEN.textMuted, fontSize: 11, fontWeight: 600, letterSpacing: '0.04em', textTransform: 'uppercase', marginBottom: 6 }}>{t ? '近期失敗' : 'Recent Failures'}</div>
        {data.recent_failures.length === 0 ? (
          <div style={{ color: TOKEN.textMuted, fontSize: 13 }}>{t ? '近期沒有失敗' : 'No recent failures'}</div>
        ) : (
          <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
            {data.recent_failures.map(ep => {
              const badge = categoryToBadge(ep.error_category, lang);
              return (
                <li key={ep.episode_id} style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                    <span style={{ color: TOKEN.text, fontSize: 13 }}>{ep.episode_title}</span>
                    {ep.error_category && <Badge variant={badge.variant}>{badge.label}</Badge>}
                  </div>
                  {ep.error_message && (
                    <div style={{ color: TOKEN.textSecondary, fontSize: 12, fontFamily: 'monospace', wordBreak: 'break-word' }}>{ep.error_message}</div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
};

const ScheduleTab = ({ lang }) => {
  const t = lang === 'zh';
  const { isMobile } = useViewport();
  const [shows, setShows] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [fetchError, setFetchError] = React.useState(null);
  const [showForm, setShowForm] = React.useState(false);
  const [form, setForm] = React.useState({ rss: '', name: '', freq: 'daily', time: '06:00', dayOfWeek: 0, whisperModel: 'large-v3', maxEp: 0 });
  const [rssLoading, setRssLoading] = React.useState(false);
  const [rssError, setRssError] = React.useState(null);
  const [rssPreview, setRssPreview] = React.useState(null);
  const [syncingId, setSyncingId] = React.useState(null);
  const [confirmState, setConfirmState] = React.useState(null);
  const [queueStatus, setQueueStatus] = React.useState(null);
  const [editState, setEditState] = React.useState(null);
  const [runningId, setRunningId] = React.useState(null);
  // Selection set is transient client-side state; not persisted.
  const [selectedIds, setSelectedIds] = React.useState(() => new Set());
  const [expandedIds, setExpandedIds] = React.useState(() => new Set());
  const toggleExpand = (showId) => {
    setExpandedIds(prev => {
      const next = new Set(prev);
      if (next.has(showId)) next.delete(showId); else next.add(showId);
      return next;
    });
  };
  const [batchRefreshing, setBatchRefreshing] = React.useState(false);
  const [batchTranscribing, setBatchTranscribing] = React.useState(false);
  const [batchTranscribeConfirmOpen, setBatchTranscribeConfirmOpen] = React.useState(false);
  const setF = (k, v) => setForm(f => ({ ...f, [k]: v }));

  const toggleSelect = (showId) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(showId)) next.delete(showId); else next.add(showId);
      return next;
    });
  };
  const clearSelection = () => setSelectedIds(new Set());
  const selectAll = (allShowIds) => setSelectedIds(new Set(allShowIds));

  const fetchQueueStatus = React.useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/admin/queue-status`);
      if (!res.ok) return;
      setQueueStatus(await res.json());
    } catch (_) {
      // 靜默失敗，不影響主 UI
    }
  }, []);

  React.useEffect(() => {
    fetchQueueStatus();
    const id = setInterval(fetchQueueStatus, 30000);
    return () => clearInterval(id);
  }, [fetchQueueStatus]);

  const loadSchedules = React.useCallback(async () => {
    setLoading(true);
    setFetchError(null);
    try {
      const res = await fetch(`${API_BASE}/admin/schedules`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setShows(data);
    } catch (err) {
      setFetchError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => { loadSchedules(); }, [loadSchedules]);

  const VALID_FREQUENCIES = ['daily', 'weekly', 'manual'];
  const DAY_LABELS_ZH = ['一', '二', '三', '四', '五', '六', '日'];
  const DAY_LABELS_EN = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

  const formatScheduleHint = (form, lang) => {
    const isZh = lang === 'zh';
    if (form.frequency === 'manual') {
      return isZh ? '不會自動執行' : 'Will not run automatically';
    }
    if (form.frequency === 'daily') {
      return isZh
        ? `每日 ${form.run_time} (UTC) 觸發`
        : `Runs daily at ${form.run_time} (UTC)`;
    }
    if (form.frequency === 'weekly') {
      const idx = Math.max(0, Math.min(6, form.day_of_week ?? 0));
      const dayZh = DAY_LABELS_ZH[idx];
      const dayEn = DAY_LABELS_EN[idx];
      return isZh
        ? `每週${dayZh} ${form.run_time} (UTC) 觸發`
        : `Runs every ${dayEn} at ${form.run_time} (UTC)`;
    }
    return '';
  };

  const handleOpenEdit = (item) => {
    if (!item.schedule) return;
    const persistedFreq = item.schedule.frequency;
    const isLegacy = !VALID_FREQUENCIES.includes(persistedFreq);
    setEditState({
      item,
      hourlyFallback: isLegacy,
      form: {
        enabled: item.schedule.enabled === true,
        frequency: isLegacy ? 'daily' : persistedFreq,
        run_time: item.schedule.run_time,
        day_of_week: item.schedule.day_of_week ?? 0,
        whisper_model: item.schedule.whisper_model,
        max_episodes_per_run: item.schedule.max_episodes_per_run,
      },
    });
  };

  const handleOpenAddSchedule = (item) => {
    setEditState({
      item,
      hourlyFallback: false,
      form: {
        enabled: false,
        frequency: 'manual',
        run_time: '06:00',
        day_of_week: 0,
        whisper_model: 'large-v3',
        max_episodes_per_run: 5,
      },
    });
  };

  const handleSaveEdit = async () => {
    if (!editState) return;
    try {
      const res = await fetch(`${API_BASE}/shows/${editState.item.show_id}/schedule`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(editState.form),
      });
      if (!res.ok) {
        const detail = await res.text();
        throw new Error(detail || `HTTP ${res.status}`);
      }
      setEditState(null);
      await loadSchedules();
    } catch (err) {
      alert((t ? '更新失敗：' : 'Update failed: ') + err.message);
    }
  };

  const handleBatchRefreshEpisodes = async () => {
    const ids = Array.from(selectedIds);
    if (ids.length === 0) return;
    const idToTitle = new Map((shows || []).map(s => [s.show_id, s.show_title]));
    setBatchRefreshing(true);
    try {
      const results = await Promise.allSettled(
        ids.map(async (id) => {
          const res = await fetch(`${API_BASE}/shows/${id}/sync`, { method: 'POST' });
          if (!res.ok) {
            const detail = await res.text();
            throw new Error(detail || `HTTP ${res.status}`);
          }
          return res.json();
        })
      );
      let added = 0, updated = 0;
      const failures = [];
      results.forEach((r, idx) => {
        if (r.status === 'fulfilled') {
          added += r.value.added || 0;
          updated += r.value.updated || 0;
        } else {
          failures.push(`${idToTitle.get(ids[idx]) || ids[idx]}: ${r.reason && r.reason.message ? r.reason.message : 'error'}`);
        }
      });
      const summary = t
        ? `已更新 ${ids.length - failures.length}/${ids.length} 個節目（新增 ${added} 集、更新 ${updated} 集）`
        : `Refreshed ${ids.length - failures.length}/${ids.length} shows (added ${added}, updated ${updated})`;
      const failText = failures.length
        ? '\n' + (t ? '失敗：\n' : 'Failed:\n') + failures.join('\n')
        : '';
      alert(summary + failText);
      await loadSchedules();
      // Selection persists (per spec).
    } finally {
      setBatchRefreshing(false);
    }
  };

  const handleBatchTranscribePending = async () => {
    const ids = Array.from(selectedIds);
    if (ids.length === 0) return;
    const idToTitle = new Map((shows || []).map(s => [s.show_id, s.show_title]));
    setBatchTranscribing(true);
    try {
      const results = await Promise.allSettled(
        ids.map(async (id) => {
          // Omit max_episodes query so backend uses each show's own schedule.max_episodes.
          const res = await fetch(`${API_BASE}/shows/${id}/transcribe-latest`, { method: 'POST' });
          if (!res.ok) {
            const detail = await res.text();
            throw new Error(detail || `HTTP ${res.status}`);
          }
          return res.json();
        })
      );
      let queued = 0;
      const failures = [];
      results.forEach((r, idx) => {
        if (r.status === 'fulfilled') {
          queued += r.value.queued || 0;
        } else {
          failures.push(`${idToTitle.get(ids[idx]) || ids[idx]}: ${r.reason && r.reason.message ? r.reason.message : 'error'}`);
        }
      });
      const summary = t
        ? `已對 ${ids.length - failures.length}/${ids.length} 個節目排入 ${queued} 集轉錄`
        : `Queued ${queued} episodes across ${ids.length - failures.length}/${ids.length} shows`;
      const failText = failures.length
        ? '\n' + (t ? '失敗：\n' : 'Failed:\n') + failures.join('\n')
        : '';
      alert(summary + failText);
      await loadSchedules();
    } finally {
      setBatchTranscribing(false);
    }
  };

  const handleRunNow = async (item) => {
    setRunningId(item.show_id);
    try {
      const res = await fetch(`${API_BASE}/shows/${item.show_id}/transcribe-latest`, { method: 'POST' });
      if (!res.ok) {
        const detail = await res.text();
        throw new Error(detail || `HTTP ${res.status}`);
      }
      const data = await res.json();
      alert(t
        ? `已排入 ${data.queued} 集（新增 ${data.synced.added}/更新 ${data.synced.updated}）`
        : `Queued ${data.queued} episodes (added ${data.synced.added}/updated ${data.synced.updated})`);
    } catch (err) {
      alert((t ? '執行失敗：' : 'Run failed: ') + err.message);
    } finally {
      setRunningId(null);
      await loadSchedules();
    }
  };

  const handleFetchRSS = async () => {
    if (!form.rss) return;
    setRssLoading(true);
    setRssError(null);
    setRssPreview(null);
    try {
      const res = await fetch(`${API_BASE}/rss-preview?url=${encodeURIComponent(form.rss)}`);
      if (!res.ok) {
        const detail = await res.text();
        throw new Error(detail || `HTTP ${res.status}`);
      }
      const data = await res.json();
      setRssPreview(data);
      setF('name', data.title);
    } catch (err) {
      setRssError(err.message);
    } finally {
      setRssLoading(false);
    }
  };

  const handleAddSchedule = async () => {
    if (!form.rss || !form.name) return;
    try {
      const createRes = await fetch(`${API_BASE}/shows`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rss_url: form.rss }),
      });
      if (!createRes.ok && createRes.status !== 409) {
        const detail = await createRes.text();
        throw new Error(detail || `HTTP ${createRes.status}`);
      }
      let show;
      if (createRes.ok) {
        show = await createRes.json();
      } else {
        const listRes = await fetch(`${API_BASE}/shows`);
        const list = await listRes.json();
        show = list.find(s => s.rss_url === form.rss);
        if (!show) throw new Error(t ? '找不到對應節目' : 'Show not found');
      }
      await fetch(`${API_BASE}/shows/${show.id}/schedule`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          enabled: true,
          frequency: form.freq,
          run_time: form.time,
          day_of_week: form.dayOfWeek,
          whisper_model: form.whisperModel,
          max_episodes_per_run: form.maxEp || 5,
        }),
      });
      setShowForm(false);
      setForm({ rss: '', name: '', freq: 'daily', time: '06:00', whisperModel: 'large-v3', maxEp: 5 });
      setRssPreview(null);
      await loadSchedules();
    } catch (err) {
      alert((t ? '建立失敗：' : 'Create failed: ') + err.message);
    }
  };

  const handleSyncShow = async (item) => {
    setSyncingId(item.show_id);
    try {
      const res = await fetch(`${API_BASE}/shows/${item.show_id}/sync`, { method: 'POST' });
      if (!res.ok) {
        const detail = await res.text();
        throw new Error(detail || `HTTP ${res.status}`);
      }
      const data = await res.json();
      alert(t
        ? `已更新節目集數：新增 ${data.added} 集、更新 ${data.updated} 集（總計 ${data.total} 集）`
        : `Episodes refreshed: added ${data.added}, updated ${data.updated} (total ${data.total})`);
      await loadSchedules();
    } catch (err) {
      alert((t ? '更新失敗：' : 'Refresh failed: ') + err.message);
    } finally {
      setSyncingId(null);
    }
  };

  const handleRemoveSchedule = async (item) => {
    try {
      const res = await fetch(`${API_BASE}/shows/${item.show_id}/schedule`, { method: 'DELETE' });
      if (!res.ok && res.status !== 204) {
        const detail = await res.text();
        throw new Error(detail || `HTTP ${res.status}`);
      }
      await loadSchedules();
    } catch (err) {
      alert((t ? '移除排程失敗：' : 'Remove schedule failed: ') + err.message);
    }
  };

  const handleDeleteShow = async (item) => {
    try {
      const res = await fetch(`${API_BASE}/shows/${item.show_id}`, { method: 'DELETE' });
      if (!res.ok && res.status !== 204) {
        const detail = await res.text();
        throw new Error(detail || `HTTP ${res.status}`);
      }
      await loadSchedules();
    } catch (err) {
      alert((t ? '刪除節目失敗：' : 'Delete show failed: ') + err.message);
    }
  };

  const openDeleteShowConfirm = async (item) => {
    let pending_count = 0, running_count = 0;
    try {
      const res = await fetch(`${API_BASE}/admin/queue`);
      if (res.ok) {
        const q = await res.json();
        pending_count = (q.pending || []).filter(r => r.show_id === item.show_id).length;
        running_count = (q.running || []).filter(r => r.show_id === item.show_id).length;
      }
    } catch {}
    setConfirmState({ kind: 'delete-show', item, cascade: { pending_count, running_count } });
  };

  const confirmLabels = {
    'delete-show': {
      title: t ? '刪除節目' : 'Delete Show',
      message: (item, extra) => {
        const base = t
          ? `即將刪除節目「${item.show_title}」及其所有集數、逐字稿、排程設定。此操作不可復原。`
          : `About to delete show "${item.show_title}" and all its episodes, transcripts, and schedule. This cannot be undone.`;
        const cascade = extra && extra.cascade;
        if (cascade && (cascade.pending_count > 0 || cascade.running_count > 0)) {
          const cascadeLine = t
            ? `將同時取消 ${cascade.pending_count} 筆排隊中、${cascade.running_count} 筆執行中的轉錄任務。`
            : `Will cancel ${cascade.pending_count} pending and ${cascade.running_count} running transcription jobs.`;
          return base + '\n\n' + cascadeLine;
        }
        return base;
      },
      confirmLabel: t ? '確認刪除' : 'Confirm Delete',
      handler: handleDeleteShow,
    },
    'remove-schedule': {
      title: t ? '移除排程' : 'Remove Schedule',
      message: (item) => t
        ? `即將移除節目「${item.show_title}」的轉錄排程設定。節目與已轉錄集數不受影響。`
        : `About to remove the transcription schedule for "${item.show_title}". The show and transcribed episodes are not affected.`,
      confirmLabel: t ? '確認移除' : 'Confirm Remove',
      handler: handleRemoveSchedule,
    },
  };
  const renderConfirmMessage = () => {
    if (!confirmState) return '';
    const cfg = confirmLabels[confirmState.kind];
    return cfg.message(confirmState.item, confirmState);
  };

  return (
    <div style={{ maxWidth: 820 }}>
      <div style={{ marginBottom: 20, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <p style={{ margin: 0, color: TOKEN.textSecondary, fontSize: 14 }}>{t ? '設定各節目的自動轉錄排程與進度監控。' : 'Configure auto-transcription schedules and monitor progress.'}</p>
        <div style={{ display: 'flex', gap: 8 }}>
          <Btn icon="plus" size="sm" onClick={() => setShowForm(v => !v)}>{t ? '新增節目' : 'Add Show'}</Btn>
        </div>
      </div>

      {queueStatus && (
        <div style={{ marginBottom: 16, display: 'flex', gap: 16, fontSize: 13, color: TOKEN.textSecondary }}>
          <span>🟢 {t ? '執行中' : 'Active'} {queueStatus.active}/{queueStatus.max_concurrent}</span>
          <span>⏳ {t ? '佇列中' : 'Queued'} {queueStatus.pending_in_db}</span>
        </div>
      )}

      {/* Add Schedule Form */}
      {showForm && (
        <div style={{ background: TOKEN.surface, border: `1px solid ${TOKEN.accent}55`, borderRadius: 14, padding: 24, marginBottom: 22 }}>
          <p style={{ color: TOKEN.text, fontWeight: 700, fontSize: 15, margin: '0 0 18px', display: 'flex', alignItems: 'center', gap: 8 }}>
            <Icon name="rss" size={16} color={TOKEN.accent} />
            {t ? '新增節目轉錄排程' : 'New Show with Transcription Schedule'}
          </p>

          {/* RSS Input */}
          <div style={{ marginBottom: 16 }}>
            <label style={{ display: 'block', color: TOKEN.textMuted, fontSize: 12, marginBottom: 6 }}>{t ? 'Podcast RSS Feed URL' : 'RSS Feed URL'} *</label>
            <div style={{ display: 'flex', gap: 8 }}>
              <div style={{ flex: 1 }}>
                <Input value={form.rss} onChange={e => setF('rss', e.target.value)} placeholder="https://feeds.example.com/my-podcast" icon="rss" />
              </div>
              <Btn size="sm" variant="secondary" onClick={handleFetchRSS} disabled={rssLoading || !form.rss}>
                {rssLoading ? (t ? '讀取中...' : 'Loading...') : (t ? '讀取 RSS' : 'Fetch RSS')}
              </Btn>
            </div>
            {rssPreview && (
              <div style={{ marginTop: 10, background: TOKEN.surfaceRaised, border: `1px solid #22c55e44`, borderRadius: 8, padding: '10px 14px', display: 'flex', gap: 12, alignItems: 'center' }}>
                <Icon name="check" size={16} color="#22c55e" />
                <div>
                  <div style={{ color: TOKEN.text, fontWeight: 600, fontSize: 13 }}>{rssPreview.title}</div>
                  <div style={{ color: TOKEN.textMuted, fontSize: 12 }}>{rssPreview.episode_count} {t ? '集' : 'eps'}{rssPreview.latest_published_at ? ` · ${t ? '最新' : 'Latest'}: ${rssPreview.latest_published_at.slice(0, 10)}` : ''}</div>
                </div>
              </div>
            )}
            {rssError && (
              <div style={{ marginTop: 10, color: '#f87171', fontSize: 12 }}>{rssError}</div>
            )}
          </div>

          {/* Name */}
          <div style={{ marginBottom: 16 }}>
            <label style={{ display: 'block', color: TOKEN.textMuted, fontSize: 12, marginBottom: 6 }}>{t ? '節目名稱' : 'Show Name'} *</label>
            <Input value={form.name} onChange={e => setF('name', e.target.value)} placeholder={t ? '輸入或自動填入' : 'Enter or auto-filled from RSS'} />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr 1fr', gap: 12, marginBottom: 16 }}>
            {/* Frequency */}
            <div>
              <label style={{ display: 'block', color: TOKEN.textMuted, fontSize: 12, marginBottom: 6 }}>{t ? '排程頻率' : 'Frequency'}</label>
              <select value={form.freq} onChange={e => setF('freq', e.target.value)}
                style={{ width: '100%', background: TOKEN.surfaceRaised, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 8, padding: '9px 12px', color: TOKEN.text, fontSize: 14, outline: 'none', fontFamily: 'inherit' }}>
                <option value="daily">{t ? '每天' : 'Daily'}</option>
                <option value="weekly">{t ? '每週' : 'Weekly'}</option>
                <option value="manual">{t ? '手動觸發' : 'Manual'}</option>
              </select>
            </div>
            {/* Time */}
            <div>
              <label style={{ display: 'block', color: TOKEN.textMuted, fontSize: 12, marginBottom: 6 }}>{t ? '執行時間' : 'Run Time'}</label>
              <input type="time" value={form.time} onChange={e => setF('time', e.target.value)}
                style={{ width: '100%', background: TOKEN.surfaceRaised, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 8, padding: '9px 12px', color: TOKEN.text, fontSize: 14, outline: 'none', fontFamily: 'inherit', colorScheme: 'dark' }} />
            </div>
            {/* Max episodes */}
            <div>
              <label style={{ display: 'block', color: TOKEN.textMuted, fontSize: 12, marginBottom: 6 }}>{t ? '每次最多集數 (0=全部)' : 'Max Episodes (0=all)'}</label>
              <input type="number" min={0} max={50} value={form.maxEp} onChange={e => setF('maxEp', Number(e.target.value))}
                style={{ width: '100%', background: TOKEN.surfaceRaised, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 8, padding: '9px 12px', color: TOKEN.text, fontSize: 14, outline: 'none', fontFamily: 'inherit' }} />
            </div>
          </div>

          {/* Whisper Model */}
          <div style={{ marginBottom: 20 }}>
            <label style={{ display: 'block', color: TOKEN.textMuted, fontSize: 12, marginBottom: 8 }}>{t ? 'Whisper 轉錄模型' : 'Whisper Transcription Model'}</label>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {[
                { id: 'large-v3', label: 'large-v3', hint: t ? '最高精度' : 'Best accuracy' },
                { id: 'medium', label: 'medium', hint: t ? '平衡' : 'Balanced' },
                { id: 'small', label: 'small', hint: t ? '快速' : 'Fast' },
                { id: 'base', label: 'base', hint: t ? '最快' : 'Fastest' },
              ].map(m => (
                <div key={m.id} onClick={() => setF('whisperModel', m.id)}
                  style={{ padding: '7px 14px', borderRadius: 8, border: `1px solid ${form.whisperModel === m.id ? TOKEN.accent : TOKEN.surfaceBorder}`, background: form.whisperModel === m.id ? TOKEN.accentDim : TOKEN.surfaceRaised, cursor: 'pointer', transition: 'all 0.12s' }}>
                  <div style={{ color: form.whisperModel === m.id ? TOKEN.accent : TOKEN.text, fontWeight: 600, fontSize: 13, fontFamily: 'monospace' }}>{m.label}</div>
                  <div style={{ color: TOKEN.textMuted, fontSize: 11 }}>{m.hint}</div>
                </div>
              ))}
            </div>
          </div>

          <div style={{ display: 'flex', gap: 8 }}>
            <Btn icon="check" onClick={handleAddSchedule} disabled={!form.rss || !form.name}>{t ? '建立排程' : 'Create Schedule'}</Btn>
            <Btn variant="ghost" onClick={() => { setShowForm(false); setRssPreview(null); }}>{t ? '取消' : 'Cancel'}</Btn>
          </div>
        </div>
      )}

      {loading && (
        <div style={{ color: TOKEN.textMuted, padding: '24px 0', textAlign: 'center' }}>{t ? '載入中...' : 'Loading...'}</div>
      )}
      {fetchError && (
        <div style={{ padding: '14px 18px', borderRadius: 8, background: 'rgba(239,68,68,0.12)', border: '1px solid rgba(239,68,68,0.3)', color: '#f87171', fontSize: 13 }}>
          {(t ? '載入失敗：' : 'Load failed: ') + fetchError}
        </div>
      )}
      {!loading && !fetchError && shows && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {shows.length === 0 && (
            <div style={{ color: TOKEN.textMuted, padding: '24px 0', textAlign: 'center' }}>{t ? '目前沒有節目，請先新增。' : 'No shows yet.'}</div>
          )}

          {shows.length > 0 && (() => {
            const allIds = shows.map(s => s.show_id);
            const allSelected = allIds.length > 0 && allIds.every(id => selectedIds.has(id));
            const someSelected = selectedIds.size > 0;
            return (
              <React.Fragment>
                {/* Master row: select-all checkbox + (when selected) count + clear */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '6px 4px' }}>
                  <label style={{ display: 'inline-flex', alignItems: 'center', gap: 8, color: TOKEN.textSecondary, fontSize: 13, cursor: 'pointer' }}>
                    <input type="checkbox" checked={allSelected} onChange={() => allSelected ? clearSelection() : selectAll(allIds)}
                      style={{ accentColor: TOKEN.accent, width: 16, height: 16, cursor: 'pointer' }} />
                    <span>{t ? '全選' : 'Select All'}</span>
                  </label>
                  {someSelected && (
                    <span style={{ color: TOKEN.textMuted, fontSize: 12 }}>
                      {t ? `已選 ${selectedIds.size} 個` : `${selectedIds.size} selected`}
                    </span>
                  )}
                </div>

                {/* Batch action bar — only when something is selected */}
                {someSelected && (
                  <div style={{ background: TOKEN.accentDim, border: `1px solid ${TOKEN.accent}55`, borderRadius: 10, padding: '10px 14px', display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                    <span style={{ color: TOKEN.accentHover, fontSize: 13, fontWeight: 600, marginRight: 'auto' }}>
                      {t ? `已選 ${selectedIds.size} 個節目` : `${selectedIds.size} shows selected`}
                    </span>
                    <Btn size="sm" variant="secondary" icon="refresh"
                      onClick={handleBatchRefreshEpisodes}
                      disabled={batchRefreshing || batchTranscribing}>
                      {batchRefreshing ? (t ? '更新中...' : 'Refreshing...') : (t ? '更新節目集數' : 'Refresh Episodes')}
                    </Btn>
                    <Btn size="sm" variant="primary" icon="play"
                      onClick={() => setBatchTranscribeConfirmOpen(true)}
                      disabled={batchRefreshing || batchTranscribing}>
                      {batchTranscribing ? (t ? '排入中...' : 'Queueing...') : (t ? '轉錄未完成集數' : 'Transcribe Pending')}
                    </Btn>
                    <Btn size="sm" variant="ghost" onClick={clearSelection}
                      disabled={batchRefreshing || batchTranscribing}>
                      {t ? '取消選取' : 'Clear'}
                    </Btn>
                  </div>
                )}
              </React.Fragment>
            );
          })()}

          {shows.map(item => {
            const sched = item.schedule;
            const checked = selectedIds.has(item.show_id);
            const lastTx = item.last_transcribed_at ? item.last_transcribed_at.slice(0, 16).replace('T', ' ') : '—';
            const refreshDisabled = syncingId === item.show_id;
            const refreshLabel = refreshDisabled
              ? (t ? '更新中...' : 'Refreshing...')
              : (t ? '更新節目集數' : 'Refresh Episodes');
            const menuItems = [
              ...(sched ? [] : [{ label: t ? '新增排程' : 'Add Schedule', icon: 'plus', onClick: () => handleOpenAddSchedule(item) }]),
              { label: refreshLabel, icon: 'refresh', onClick: () => handleSyncShow(item), disabled: refreshDisabled },
              ...(sched ? [{ label: t ? '編輯排程' : 'Edit Schedule', icon: 'settings', onClick: () => handleOpenEdit(item) }] : []),
              ...(sched ? [{ label: t ? '移除排程' : 'Remove Schedule', icon: 'trash', onClick: () => setConfirmState({ kind: 'remove-schedule', item }) }] : []),
              { label: t ? '刪除節目' : 'Delete Show', icon: 'trash', onClick: () => openDeleteShowConfirm(item), danger: true },
            ];
            return (
              <div key={item.show_id} style={{ background: TOKEN.surface, border: `1px solid ${checked ? TOKEN.accent + '88' : TOKEN.surfaceBorder}`, borderRadius: 12, padding: isMobile ? '14px 16px' : '18px 22px' }}>
                <div style={{ display: 'flex', alignItems: 'flex-start', gap: isMobile ? 12 : 16, flexWrap: 'wrap', flexDirection: isMobile ? 'column' : 'row' }}>
                  <input type="checkbox" checked={checked} onChange={() => toggleSelect(item.show_id)}
                    aria-label={t ? `選取 ${item.show_title}` : `Select ${item.show_title}`}
                    style={{ accentColor: TOKEN.accent, width: 16, height: 16, cursor: 'pointer', marginTop: 5, flexShrink: 0 }} />
                  <div style={{ flex: isMobile ? 'none' : '1 1 320px', width: isMobile ? '100%' : 'auto', minWidth: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                      <span style={{ color: TOKEN.text, fontWeight: 600, fontSize: 15 }}>{item.show_title}</span>
                      {item.pending_count > 0 && <Badge variant="warning">{item.pending_count} {t ? '集待轉錄' : 'pending'}</Badge>}
                      {!sched && <Badge variant="muted">{t ? '未設定' : 'No schedule'}</Badge>}
                    </div>
                    <div style={{ display: 'flex', gap: 16, marginTop: 7, fontSize: 12, color: TOKEN.textMuted, flexWrap: 'wrap', alignItems: 'center' }}>
                      <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}><Icon name="rss" size={11} /><span style={{ fontFamily: 'monospace', maxWidth: 240, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{item.rss_url}</span></span>
                      {sched && <span>{t ? '頻率' : 'Freq'}: {sched.frequency}{sched.frequency === 'weekly' ? ` · ${(t ? DAY_LABELS_ZH : DAY_LABELS_EN)[sched.day_of_week ?? 0]}` : ''} · {sched.run_time}</span>}
                      <span><Icon name="clock" size={11} style={{ marginRight: 3 }} />{t ? '最後轉錄' : 'Last'}: {lastTx}</span>
                      {sched && <Badge variant="muted">{sched.whisper_model}</Badge>}
                    </div>
                  </div>
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', justifyContent: isMobile ? 'flex-start' : 'flex-end', alignItems: 'center', width: isMobile ? '100%' : 'auto' }}>
                    <Btn size="sm" variant="ghost"
                      icon={expandedIds.has(item.show_id) ? 'chevronLeft' : 'chevronRight'}
                      onClick={() => toggleExpand(item.show_id)}>
                      {expandedIds.has(item.show_id)
                        ? (t ? '收合進度' : 'Hide Progress')
                        : (t ? '查看進度' : 'View Progress')}
                    </Btn>
                    {sched && (
                      <Btn size="sm" variant="primary" icon="play"
                        onClick={() => handleRunNow(item)}
                        disabled={runningId === item.show_id}>
                        {runningId === item.show_id ? (t ? '執行中...' : 'Running...') : (t ? '立刻執行轉錄' : 'Run Transcribe Now')}
                      </Btn>
                    )}
                    <OverflowMenu items={menuItems} ariaLabel={t ? '更多操作' : 'More actions'} />
                  </div>
                </div>
                {sched && (() => {
                  const status = sched.last_refresh_status || 'pending';
                  const ts = sched.last_refresh_at;
                  const msg = sched.last_refresh_message;
                  const colorMap = { success: '#22c55e', failed: '#f87171', pending: TOKEN.textMuted };
                  const iconMap = { success: '✓', failed: '✗', pending: '·' };
                  const color = colorMap[status] || TOKEN.textMuted;
                  const icon = iconMap[status] || '·';
                  const label = ts
                    ? (t ? `${formatRelativeTime(new Date(ts).getTime(), lang)}刷新` : `Refreshed ${formatRelativeTime(new Date(ts).getTime(), lang)}`)
                    : (t ? '尚未刷新' : 'Not yet refreshed');
                  return (
                    <div title={msg || ''} style={{ marginTop: 12, paddingTop: 10, borderTop: `1px dashed ${TOKEN.surfaceBorder}`, color, fontSize: 12, display: 'flex', alignItems: 'center', gap: 6 }}>
                      <span style={{ fontWeight: 700 }}>{icon}</span>
                      <span>{label}</span>
                      {status === 'failed' && msg && (
                        <span style={{ color: TOKEN.textMuted, marginLeft: 8, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 360 }}>{msg}</span>
                      )}
                    </div>
                  );
                })()}
                <TranscriptionProgressPanel
                  showId={item.show_id}
                  expanded={expandedIds.has(item.show_id)}
                  lang={lang}
                />
              </div>
            );
          })}
        </div>
      )}
      <ConfirmModal
        open={confirmState !== null}
        title={confirmState ? confirmLabels[confirmState.kind].title : ''}
        message={renderConfirmMessage()}
        confirmLabel={confirmState ? confirmLabels[confirmState.kind].confirmLabel : ''}
        cancelLabel={t ? '取消' : 'Cancel'}
        danger={true}
        onConfirm={() => {
          const { kind, item } = confirmState;
          setConfirmState(null);
          confirmLabels[kind].handler(item);
        }}
        onCancel={() => setConfirmState(null)}
      />
      <ConfirmModal
        open={batchTranscribeConfirmOpen}
        title={t ? '批次轉錄' : 'Batch Transcribe'}
        message={t
          ? `即將對 ${selectedIds.size} 個節目排入轉錄，會消耗 OpenAI 額度，是否繼續？`
          : `About to queue transcription for ${selectedIds.size} shows. This will consume OpenAI credit. Continue?`}
        confirmLabel={t ? '確認' : 'Confirm'}
        cancelLabel={t ? '取消' : 'Cancel'}
        danger={false}
        onConfirm={() => {
          setBatchTranscribeConfirmOpen(false);
          handleBatchTranscribePending();
        }}
        onCancel={() => setBatchTranscribeConfirmOpen(false)}
      />
      <FormModal
        open={editState !== null}
        title={t ? '編輯排程' : 'Edit Schedule'}
        confirmLabel={t ? '儲存' : 'Save'}
        cancelLabel={t ? '取消' : 'Cancel'}
        onConfirm={handleSaveEdit}
        onCancel={() => setEditState(null)}
      >
        {editState && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <div>
              <label style={{ display: 'block', color: TOKEN.textMuted, fontSize: 12, marginBottom: 6 }}>{t ? '自動轉錄' : 'Auto Transcribe'}</label>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <div onClick={() => setEditState(s => ({ ...s, form: { ...s.form, enabled: !s.form.enabled } }))}
                  role="switch" aria-checked={editState.form.enabled}
                  style={{ width: 36, height: 20, borderRadius: 99, background: editState.form.enabled ? TOKEN.accent : TOKEN.surfaceBorder, cursor: 'pointer', position: 'relative', transition: 'background 0.15s', flexShrink: 0 }}>
                  <div style={{ width: 14, height: 14, borderRadius: '50%', background: '#fff', position: 'absolute', top: 3, left: editState.form.enabled ? 19 : 3, transition: 'left 0.15s' }} />
                </div>
                <span style={{ color: TOKEN.textSecondary, fontSize: 13 }}>
                  {editState.form.enabled ? (t ? '已啟用' : 'Enabled') : (t ? '已停用' : 'Disabled')}
                </span>
              </div>
              <p style={{ margin: '6px 0 0', color: TOKEN.textMuted, fontSize: 11 }}>
                {t ? '待 cron 功能上線後生效。' : 'Takes effect once cron support ships.'}
              </p>
            </div>
            <div>
              <label style={{ display: 'block', color: TOKEN.textMuted, fontSize: 12, marginBottom: 6 }}>{t ? '排程頻率' : 'Frequency'}</label>
              <select value={editState.form.frequency}
                onChange={e => setEditState(s => ({ ...s, form: { ...s.form, frequency: e.target.value } }))}
                style={{ width: '100%', background: TOKEN.surfaceRaised, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 8, padding: '9px 12px', color: TOKEN.text, fontSize: 14, outline: 'none', fontFamily: 'inherit' }}>
                <option value="daily">{t ? '每天' : 'Daily'}</option>
                <option value="weekly">{t ? '每週' : 'Weekly'}</option>
                <option value="manual">{t ? '手動觸發' : 'Manual'}</option>
              </select>
              {editState.hourlyFallback && (
                <div style={{ color: TOKEN.warning, fontSize: 12, marginTop: 6 }}>
                  {t
                    ? '原設定『每小時』已停用，已改為每天，請確認後儲存。'
                    : "The previous 'hourly' setting is no longer supported; switched to daily. Please confirm and save."}
                </div>
              )}
              {editState.form.frequency === 'manual' && (
                <>
                  <div style={{ color: TOKEN.textSecondary, fontSize: 12, marginTop: 6 }}>
                    {t
                      ? '不會自動執行，需從清單點「立即執行」'
                      : 'Will not run automatically. Trigger manually from the list.'}
                  </div>
                  <div style={{ color: TOKEN.textMuted, fontSize: 12, marginTop: 4 }}>
                    {formatScheduleHint(editState.form, lang)}
                  </div>
                </>
              )}
            </div>
            {editState.form.frequency === 'weekly' && (
              <div>
                <label style={{ display: 'block', color: TOKEN.textMuted, fontSize: 12, marginBottom: 6 }}>{t ? '星期幾' : 'Day of Week'}</label>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                  {(t ? DAY_LABELS_ZH : DAY_LABELS_EN).map((label, i) => {
                    const selected = editState.form.day_of_week === i;
                    return (
                      <button
                        key={i}
                        type="button"
                        onClick={() => setEditState(s => ({ ...s, form: { ...s.form, day_of_week: i } }))}
                        style={{
                          minWidth: 44,
                          minHeight: isMobile ? 44 : undefined,
                          padding: '8px 12px',
                          borderRadius: 8,
                          border: `1px solid ${selected ? TOKEN.accent : TOKEN.surfaceBorder}`,
                          background: selected ? TOKEN.accent : TOKEN.surfaceRaised,
                          color: selected ? '#fff' : TOKEN.textSecondary,
                          fontSize: 13,
                          fontWeight: selected ? 600 : 500,
                          cursor: 'pointer',
                          fontFamily: 'inherit',
                        }}
                      >
                        {label}
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
            {editState.form.frequency !== 'manual' && (
              <div>
                <label style={{ display: 'block', color: TOKEN.textMuted, fontSize: 12, marginBottom: 6 }}>{t ? '執行時間' : 'Run Time'}</label>
                <input type="time" value={editState.form.run_time}
                  onChange={e => setEditState(s => ({ ...s, form: { ...s.form, run_time: e.target.value } }))}
                  style={{ width: '100%', boxSizing: 'border-box', background: TOKEN.surfaceRaised, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 8, padding: '9px 12px', color: TOKEN.text, fontSize: 14, outline: 'none', fontFamily: 'inherit', colorScheme: 'dark' }} />
                <div style={{ color: TOKEN.textMuted, fontSize: 12, marginTop: 6 }}>
                  {formatScheduleHint(editState.form, lang)}
                </div>
              </div>
            )}
            <div>
              <label style={{ display: 'block', color: TOKEN.textMuted, fontSize: 12, marginBottom: 6 }}>{t ? 'Whisper 模型' : 'Whisper Model'}</label>
              <select value={editState.form.whisper_model}
                onChange={e => setEditState(s => ({ ...s, form: { ...s.form, whisper_model: e.target.value } }))}
                style={{ width: '100%', background: TOKEN.surfaceRaised, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 8, padding: '9px 12px', color: TOKEN.text, fontSize: 14, outline: 'none', fontFamily: 'inherit' }}>
                <option value="large-v3">large-v3</option>
                <option value="medium">medium</option>
                <option value="small">small</option>
                <option value="base">base</option>
              </select>
            </div>
            <div>
              <label style={{ display: 'block', color: TOKEN.textMuted, fontSize: 12, marginBottom: 6 }}>{t ? '每次最多轉錄集數' : 'Max Episodes Per Run'}</label>
              <input type="number" min={1} max={50} value={editState.form.max_episodes_per_run}
                onChange={e => setEditState(s => ({ ...s, form: { ...s.form, max_episodes_per_run: Number(e.target.value) } }))}
                style={{ width: '100%', boxSizing: 'border-box', background: TOKEN.surfaceRaised, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 8, padding: '9px 12px', color: TOKEN.text, fontSize: 14, outline: 'none', fontFamily: 'inherit' }} />
            </div>
            {editState.item && editState.item.schedule && (
              <div style={{ marginTop: 4, padding: '10px 12px', background: TOKEN.bg, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 8 }}>
                <div style={{ color: TOKEN.textMuted, fontSize: 11, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 6 }}>
                  {t ? '最後刷新狀態' : 'Last Refresh'}
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 12, color: TOKEN.textSecondary }}>
                  <div>{t ? '時間：' : 'At: '}{editState.item.schedule.last_refresh_at ? new Date(editState.item.schedule.last_refresh_at).toLocaleString() : (t ? '尚未刷新' : 'Not yet refreshed')}</div>
                  <div>{t ? '狀態：' : 'Status: '}{editState.item.schedule.last_refresh_status || '—'}</div>
                  <div style={{ wordBreak: 'break-word' }}>{t ? '訊息：' : 'Message: '}{editState.item.schedule.last_refresh_message || '—'}</div>
                </div>
              </div>
            )}
          </div>
        )}
      </FormModal>
    </div>
  );
};

Object.assign(window, { AdminPage });
