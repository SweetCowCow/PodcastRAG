// Admin Page — API Keys, LLM, RAG Config, Transcription Schedule
const AdminPage = ({ lang, activePage }) => {
  const t = lang === 'zh';
  const pages = {
    'admin-api': <ApiKeysTab lang={lang} />,
    'admin-llm': <LLMTab lang={lang} />,
    'admin-rag': <RAGTab lang={lang} />,
    'admin-schedule': <ScheduleTab lang={lang} />,
  };
  return (
    <div style={{ flex: 1, overflowY: 'auto', background: TOKEN.bg }}>
      <div style={{ padding: '32px 40px 16px', borderBottom: `1px solid ${TOKEN.surfaceBorder}`, background: TOKEN.surface }}>
        <p style={{ color: TOKEN.accent, fontSize: 12, fontWeight: 600, letterSpacing: '0.1em', textTransform: 'uppercase', margin: '0 0 4px' }}>{t ? '後台管理' : 'Administration'}</p>
        <h1 style={{ color: TOKEN.text, fontSize: 24, fontWeight: 700, margin: 0 }}>
          {{ 'admin-api': t ? 'API 金鑰管理' : 'API Key Management', 'admin-llm': t ? 'LLM 模型設定' : 'LLM Model Settings', 'admin-rag': t ? 'RAG 參數設定' : 'RAG Configuration', 'admin-schedule': t ? '轉錄排程管理' : 'Transcription Schedule' }[activePage]}
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
const LLMTab = ({ lang }) => {
  const t = lang === 'zh';
  const [active, setActive] = React.useState('openai-gpt4o');
  const [temp, setTemp] = React.useState(0.3);
  const [maxTokens, setMaxTokens] = React.useState(2048);

  const models = [
    { id: 'openai-gpt4o', provider: 'OpenAI', name: 'GPT-4o', desc: t ? '適合複雜推理與長文摘要' : 'Best for complex reasoning and long summaries', ctx: '128K', status: 'available' },
    { id: 'openai-gpt4o-mini', provider: 'OpenAI', name: 'GPT-4o mini', desc: t ? '速度快、成本低，適合即時查詢' : 'Fast and cost-efficient for real-time queries', ctx: '128K', status: 'available' },
    { id: 'anthropic-claude', provider: 'Anthropic', name: 'Claude Opus 4.5', desc: t ? '長文本理解能力最強' : 'Best long-context comprehension', ctx: '200K', status: 'available' },
    { id: 'anthropic-haiku', provider: 'Anthropic', name: 'Claude Haiku 4.5', desc: t ? '超低延遲，適合摘要生成' : 'Ultra-low latency for summary generation', ctx: '200K', status: 'available' },
    { id: 'google-gemini', provider: 'Google', name: 'Gemini 2.5 Pro', desc: t ? '多模態支援，適合含影片的 Podcast' : 'Multimodal support for video podcasts', ctx: '1M', status: 'available' },
    { id: 'aihub', provider: 'AI Hub', name: 'Zeabur LLM v2', desc: t ? '私有部署，資料不外流' : 'Private deployment, data stays local', ctx: '32K', status: 'available' },
  ];

  const providerColors = { OpenAI: '#22c55e', Anthropic: '#f59e0b', Google: '#6366f1', 'AI Hub': '#22d3ee' };

  return (
    <div style={{ maxWidth: 760 }}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 28 }}>
        {models.map(m => (
          <div key={m.id} onClick={() => setActive(m.id)}
            style={{ background: TOKEN.surface, border: `1px solid ${active === m.id ? TOKEN.accent + '88' : TOKEN.surfaceBorder}`, borderRadius: 12, padding: '16px 18px', cursor: 'pointer', transition: 'all 0.12s', boxShadow: active === m.id ? `0 0 0 1px ${TOKEN.accent}44` : 'none' }}>
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 5 }}>
                  <span style={{ fontSize: 12, fontWeight: 600, color: providerColors[m.provider] }}>{m.provider}</span>
                  {active === m.id && <Badge variant="default">{t ? '使用中' : 'Active'}</Badge>}
                </div>
                <div style={{ color: TOKEN.text, fontWeight: 600, fontSize: 15, marginBottom: 5 }}>{m.name}</div>
                <p style={{ margin: 0, color: TOKEN.textSecondary, fontSize: 12, lineHeight: 1.5 }}>{m.desc}</p>
              </div>
              <div style={{ width: 20, height: 20, borderRadius: '50%', border: `2px solid ${active === m.id ? TOKEN.accent : TOKEN.surfaceBorder}`, background: active === m.id ? TOKEN.accent : 'transparent', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, marginTop: 2 }}>
                {active === m.id && <Icon name="check" size={12} color="#fff" />}
              </div>
            </div>
            <div style={{ marginTop: 12, fontSize: 11, color: TOKEN.textMuted }}>Context: {m.ctx}</div>
          </div>
        ))}
      </div>

      {/* Params */}
      <div style={{ background: TOKEN.surface, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 12, padding: '20px 24px' }}>
        <p style={{ color: TOKEN.text, fontWeight: 600, fontSize: 14, margin: '0 0 18px' }}>{t ? '推論參數' : 'Inference Parameters'}</p>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
          <SliderParam label={t ? '溫度 (Temperature)' : 'Temperature'} value={temp} min={0} max={1} step={0.05} onChange={setTemp} hint={t ? '越高越有創意，越低越精確' : 'Higher = more creative, lower = precise'} />
          <SliderParam label={t ? '最大 Token 數' : 'Max Tokens'} value={maxTokens} min={256} max={8192} step={256} onChange={setMaxTokens} hint={`${maxTokens} tokens`} />
        </div>
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
const ScheduleTab = ({ lang }) => {
  const t = lang === 'zh';
  const [shows, setShows] = React.useState([
    { id: 'tsmc-era', name: '台積電時代', nameEn: 'TSMC Era', rss: 'https://feeds.example.com/tsmc-era', enabled: true, freq: 'daily', time: '06:00', whisperModel: 'large-v3', maxEp: 0, lastRun: '2026-04-18 06:00', nextRun: '2026-04-19 06:00', status: 'success', progress: 100, pending: 4 },
    { id: 'ai-frontiers', name: 'AI 前沿報告', nameEn: 'AI Frontiers', rss: 'https://feeds.example.com/ai-frontiers', enabled: true, freq: 'weekly', time: '08:00', whisperModel: 'large-v3', maxEp: 0, lastRun: '2026-04-17 08:00', nextRun: '2026-04-24 08:00', status: 'success', progress: 100, pending: 0 },
    { id: 'startup-island', name: '創業島嶼', nameEn: 'Startup Island', rss: 'https://feeds.example.com/startup-island', enabled: true, freq: 'daily', time: '02:30', whisperModel: 'medium', maxEp: 5, lastRun: '2026-04-19 02:30', nextRun: '2026-04-20 02:30', status: 'running', progress: 67, pending: 15 },
    { id: 'deep-science', name: '深科學', nameEn: 'Deep Science', rss: 'https://feeds.example.com/deep-science', enabled: false, freq: 'manual', time: '00:00', whisperModel: 'base', maxEp: 10, lastRun: '2026-04-10 14:00', nextRun: '—', status: 'paused', progress: 60, pending: 27 },
  ]);
  const [showForm, setShowForm] = React.useState(false);
  const [form, setForm] = React.useState({ rss: '', name: '', freq: 'daily', time: '06:00', whisperModel: 'large-v3', maxEp: 0, lang: 'zh' });
  const [rssLoading, setRssLoading] = React.useState(false);
  const [rssPreview, setRssPreview] = React.useState(null);
  const setF = (k, v) => setForm(f => ({ ...f, [k]: v }));

  const statusColor = { success: '#22c55e', running: TOKEN.accent, paused: TOKEN.textMuted, error: TOKEN.danger };
  const statusLabel = { success: t ? '完成' : 'Done', running: t ? '轉錄中' : 'Running', paused: t ? '已暫停' : 'Paused', error: t ? '錯誤' : 'Error' };

  const handleFetchRSS = () => {
    if (!form.rss) return;
    setRssLoading(true);
    setRssPreview(null);
    setTimeout(() => {
      setRssPreview({ name: '科技島讀', episodes: 87, latestEp: '2026-04-18', desc: 'AI 時代的台灣科技觀察' });
      setF('name', '科技島讀');
      setRssLoading(false);
    }, 1000);
  };

  const handleAddSchedule = () => {
    if (!form.rss || !form.name) return;
    const id = 'new-' + Date.now();
    setShows(ss => [...ss, {
      id, name: form.name, nameEn: form.name, rss: form.rss,
      enabled: true, freq: form.freq, time: form.time,
      whisperModel: form.whisperModel, maxEp: form.maxEp,
      lastRun: '—', nextRun: '2026-04-20 ' + form.time,
      status: 'paused', progress: 0, pending: rssPreview?.episodes || 0,
    }]);
    setShowForm(false);
    setForm({ rss: '', name: '', freq: 'daily', time: '06:00', whisperModel: 'large-v3', maxEp: 0 });
    setRssPreview(null);
  };

  return (
    <div style={{ maxWidth: 820 }}>
      <div style={{ marginBottom: 20, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <p style={{ margin: 0, color: TOKEN.textSecondary, fontSize: 14 }}>{t ? '設定各節目的自動轉錄排程與進度監控。' : 'Configure auto-transcription schedules and monitor progress.'}</p>
        <div style={{ display: 'flex', gap: 8 }}>
          <Btn icon="refresh" variant="secondary" size="sm">{t ? '同步所有' : 'Sync All'}</Btn>
          <Btn icon="plus" size="sm" onClick={() => setShowForm(v => !v)}>{t ? '新增排程' : 'Add Schedule'}</Btn>
        </div>
      </div>

      {/* Add Schedule Form */}
      {showForm && (
        <div style={{ background: TOKEN.surface, border: `1px solid ${TOKEN.accent}55`, borderRadius: 14, padding: 24, marginBottom: 22 }}>
          <p style={{ color: TOKEN.text, fontWeight: 700, fontSize: 15, margin: '0 0 18px', display: 'flex', alignItems: 'center', gap: 8 }}>
            <Icon name="rss" size={16} color={TOKEN.accent} />
            {t ? '新增轉錄排程' : 'New Transcription Schedule'}
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
                  <div style={{ color: TOKEN.text, fontWeight: 600, fontSize: 13 }}>{rssPreview.name}</div>
                  <div style={{ color: TOKEN.textMuted, fontSize: 12 }}>{rssPreview.episodes} {t ? '集・最新' : 'eps · Latest'}: {rssPreview.latestEp} · {rssPreview.desc}</div>
                </div>
              </div>
            )}
          </div>

          {/* Name */}
          <div style={{ marginBottom: 16 }}>
            <label style={{ display: 'block', color: TOKEN.textMuted, fontSize: 12, marginBottom: 6 }}>{t ? '節目名稱' : 'Show Name'} *</label>
            <Input value={form.name} onChange={e => setF('name', e.target.value)} placeholder={t ? '輸入或自動填入' : 'Enter or auto-filled from RSS'} />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 14, marginBottom: 16 }}>
            {/* Frequency */}
            <div>
              <label style={{ display: 'block', color: TOKEN.textMuted, fontSize: 12, marginBottom: 6 }}>{t ? '排程頻率' : 'Frequency'}</label>
              <select value={form.freq} onChange={e => setF('freq', e.target.value)}
                style={{ width: '100%', background: TOKEN.surfaceRaised, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 8, padding: '9px 12px', color: TOKEN.text, fontSize: 14, outline: 'none', fontFamily: 'inherit' }}>
                <option value="hourly">{t ? '每小時' : 'Hourly'}</option>
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

      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        {shows.map(show => (
          <div key={show.id} style={{ background: TOKEN.surface, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 12, padding: '18px 22px' }}>
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: 16, marginBottom: 14 }}>
              <div onClick={() => setShows(ss => ss.map(s => s.id === show.id ? { ...s, enabled: !s.enabled, status: !s.enabled ? 'success' : 'paused' } : s))}
                style={{ width: 36, height: 20, borderRadius: 99, background: show.enabled ? TOKEN.accent : TOKEN.surfaceBorder, cursor: 'pointer', position: 'relative', transition: 'background 0.15s', flexShrink: 0, marginTop: 3 }}>
                <div style={{ width: 14, height: 14, borderRadius: '50%', background: '#fff', position: 'absolute', top: 3, left: show.enabled ? 19 : 3, transition: 'left 0.15s' }} />
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                  <span style={{ color: TOKEN.text, fontWeight: 600, fontSize: 15 }}>{t ? show.name : show.nameEn}</span>
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12, color: statusColor[show.status] }}>
                    <span style={{ width: 6, height: 6, borderRadius: '50%', background: statusColor[show.status], display: 'inline-block', animation: show.status === 'running' ? 'pulse 1.5s infinite' : 'none' }} />
                    {statusLabel[show.status]}
                  </span>
                  {show.pending > 0 && <Badge variant="warning">{show.pending} {t ? '集待轉錄' : 'pending'}</Badge>}
                </div>
                <div style={{ display: 'flex', gap: 16, marginTop: 7, fontSize: 12, color: TOKEN.textMuted, flexWrap: 'wrap', alignItems: 'center' }}>
                  <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}><Icon name="rss" size={11} /><span style={{ fontFamily: 'monospace', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{show.rss}</span></span>
                  <span><select value={show.freq} onChange={e => setShows(ss => ss.map(s => s.id === show.id ? { ...s, freq: e.target.value } : s))}
                    style={{ background: 'transparent', border: 'none', color: TOKEN.textSecondary, fontSize: 12, cursor: 'pointer', fontFamily: 'inherit', outline: 'none' }}>
                    <option value="hourly">{t ? '每小時' : 'Hourly'}</option>
                    <option value="daily">{t ? '每天' : 'Daily'}</option>
                    <option value="weekly">{t ? '每週' : 'Weekly'}</option>
                    <option value="manual">{t ? '手動' : 'Manual'}</option>
                  </select></span>
                  <span><Icon name="clock" size={11} style={{ marginRight: 3 }} />{t ? '上次' : 'Last'}: {show.lastRun}</span>
                  <span>{t ? '下次' : 'Next'}: {show.nextRun}</span>
                  <Badge variant="muted">{show.whisperModel || 'large-v3'}</Badge>
                </div>
              </div>
              <Btn size="sm" variant="secondary" icon="play" onClick={() => setShows(ss => ss.map(s => s.id === show.id ? { ...s, status: 'running', progress: 10 } : s))}>{t ? '執行' : 'Run'}</Btn>
            </div>
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: TOKEN.textMuted, marginBottom: 6 }}>
                <span>{t ? '轉錄進度' : 'Progress'}</span>
                <span style={{ color: show.progress === 100 ? '#22c55e' : TOKEN.textSecondary, fontWeight: 600 }}>{show.progress}%</span>
              </div>
              <div style={{ height: 6, background: TOKEN.surfaceBorder, borderRadius: 99, overflow: 'hidden' }}>
                <div style={{ height: '100%', width: `${show.progress}%`, background: show.progress === 100 ? '#22c55e' : show.status === 'running' ? TOKEN.accent : TOKEN.textMuted, borderRadius: 99, transition: 'width 0.4s', animation: show.status === 'running' ? 'shimmer 1.5s infinite' : 'none' }} />
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

Object.assign(window, { AdminPage });
