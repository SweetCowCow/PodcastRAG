// Admin Page — API Keys, LLM, RAG Config, Transcription Schedule
const AdminPage = ({ lang, activePage, currentUser }) => {
  const t = lang === 'zh';
  const pages = {
    'admin-api': <ApiKeysTab lang={lang} />,
    'admin-llm': <AiStepsTab lang={lang} />,
    'admin-rag': <RAGTab lang={lang} />,
    'admin-schedule': <ScheduleTab lang={lang} />,
    'admin-queue': <QueueTab lang={lang} />,
    'admin-users': <UserManagementTab lang={lang} currentUser={currentUser} />,
    'admin-quota-requests': <QuotaRequestsTab lang={lang} />,
    'admin-guests': <AdminEpisodeGuestsTab lang={lang} />,
    'admin-tokenizer': <AdminTokenizerTab lang={lang} />,
    'admin-asr-correction': <AdminAsrCorrectionTab lang={lang} />,
    'admin-topic-seg-audit': <AdminTopicSegAuditTab lang={lang} />,
    'admin-external-api': <ExternalApiStatusTab lang={lang} />,
    'admin-provider-usage': <ProviderUsageTab lang={lang} />,
    'admin-service-status': <ServiceStatusTab lang={lang} />,
  };
  return (
    <div style={{ flex: 1, overflowY: 'auto', background: TOKEN.bg }}>
      <div style={{ padding: '32px 40px 16px', borderBottom: `1px solid ${TOKEN.surfaceBorder}`, background: TOKEN.surface }}>
        <p style={{ color: TOKEN.accent, fontSize: 12, fontWeight: 600, letterSpacing: '0.1em', textTransform: 'uppercase', margin: '0 0 4px' }}>{t ? '後台管理' : 'Administration'}</p>
        <h1 style={{ color: TOKEN.text, fontSize: 24, fontWeight: 700, margin: 0 }}>
          {{ 'admin-api': t ? 'API 金鑰管理' : 'API Key Management', 'admin-llm': t ? 'LLM 模型設定' : 'LLM Model Settings', 'admin-rag': t ? 'RAG 參數設定' : 'RAG Configuration', 'admin-schedule': t ? '轉錄排程管理' : 'Transcription Schedule', 'admin-queue': t ? '轉錄序列' : 'Transcription Queue', 'admin-users': t ? '使用者管理' : 'User Management', 'admin-quota-requests': t ? 'Quota 申請' : 'Quota Requests', 'admin-guests': t ? '來賓管理' : 'Guests', 'admin-tokenizer': t ? '分詞詞典管理' : 'Tokenizer Dictionary', 'admin-asr-correction': t ? 'ASR 校正字典' : 'ASR Correction Dictionary', 'admin-topic-seg-audit': t ? '段落分類審核' : 'Topic Segment Audit', 'admin-external-api': t ? '外部 API 狀態' : 'External API Status', 'admin-provider-usage': t ? '服務用量' : 'Service Usage', 'admin-service-status': t ? '服務狀態' : 'Service Status' }[activePage]}
        </h1>
      </div>
      <div style={{ padding: '28px 40px 40px' }}>{pages[activePage]}</div>
    </div>
  );
};

// ── API Keys Tab ──
// Provider colour palette. Free-form provider strings fall back to TOKEN.accent.
const PROVIDER_COLORS = {
  openai: '#22c55e',
  anthropic: '#f59e0b',
  google: '#6366f1',
  'zeabur-aihub': '#22d3ee',
};
const PROVIDER_PRESETS = ['openai', 'anthropic', 'google', 'zeabur-aihub'];

const ApiKeysTab = ({ lang }) => {
  const t = lang === 'zh';
  const [keys, setKeys] = React.useState(null);
  const [error, setError] = React.useState(null);
  const [adding, setAdding] = React.useState(false);
  const [editing, setEditing] = React.useState(null); // { id, label, api_key }
  const [toast, setToast] = React.useState(null);
  const [newKey, setNewKey] = React.useState({ provider: '', label: '', api_key: '' });

  const reload = React.useCallback(async () => {
    setError(null);
    try {
      const res = await apiFetch('/admin/api-keys');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setKeys(await res.json());
    } catch (err) { setError(err.message); }
  }, []);
  React.useEffect(() => { reload(); }, [reload]);

  const flashToast = (text, kind = 'success') => {
    setToast({ text, kind });
    setTimeout(() => setToast(null), 3500);
  };

  const handleCreate = async () => {
    if (!newKey.provider.trim() || !newKey.label.trim() || !newKey.api_key.trim()) {
      flashToast(t ? '請填寫完整欄位' : 'All fields required', 'error');
      return;
    }
    try {
      const res = await apiFetch('/admin/api-keys', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newKey),
      });
      if (res.status === 409) {
        flashToast(t ? '同一供應商已有此 label' : 'Duplicate label for provider', 'error');
        return;
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setAdding(false);
      setNewKey({ provider: '', label: '', api_key: '' });
      flashToast(t ? '已新增' : 'Added');
      await reload();
    } catch (err) { flashToast((t ? '失敗：' : 'Failed: ') + err.message, 'error'); }
  };

  const handleUpdate = async () => {
    const payload = {};
    if (editing.label && editing.label.trim()) payload.label = editing.label.trim();
    if (editing.api_key && editing.api_key.trim()) payload.api_key = editing.api_key.trim();
    try {
      const res = await apiFetch(`/admin/api-keys/${editing.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (res.status === 409) {
        flashToast(t ? '同一供應商已有此 label' : 'Duplicate label for provider', 'error');
        return;
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setEditing(null);
      flashToast(t ? '已更新' : 'Updated');
      await reload();
    } catch (err) { flashToast((t ? '失敗：' : 'Failed: ') + err.message, 'error'); }
  };

  const handleDelete = async (k) => {
    if (!window.confirm(t ? `確定要刪除 ${k.provider}/${k.label}？` : `Delete ${k.provider}/${k.label}?`)) return;
    try {
      const res = await apiFetch(`/admin/api-keys/${k.id}`, { method: 'DELETE' });
      if (res.status === 409) {
        const body = await res.json().catch(() => ({}));
        const refs = body?.detail?.referenced_by || [];
        flashToast(
          (t ? '無法刪除：仍被以下 step 使用 — ' : 'Cannot delete: still referenced by — ') + refs.join(', '),
          'error',
        );
        return;
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      flashToast(t ? '已刪除' : 'Deleted');
      await reload();
    } catch (err) { flashToast((t ? '失敗：' : 'Failed: ') + err.message, 'error'); }
  };

  return (
    <div style={{ maxWidth: 760 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <p style={{ margin: 0, color: TOKEN.textSecondary, fontSize: 14 }}>
          {t ? '管理各 LLM 供應商的 API 金鑰。AI 處理步驟設定頁會引用這裡的金鑰。' : 'Manage API keys per provider. Referenced by AI step config.'}
        </p>
        <Btn icon="plus" onClick={() => setAdding(true)} size="sm">{t ? '新增金鑰' : 'Add Key'}</Btn>
      </div>

      {error && (
        <div style={{ padding: '9px 13px', borderRadius: 8, fontSize: 13, marginBottom: 12,
          background: 'rgba(239,68,68,0.12)', border: '1px solid rgba(239,68,68,0.3)', color: '#f87171' }}>
          {(t ? '載入失敗：' : 'Load failed: ') + error}
        </div>
      )}

      {adding && (
        <div style={{ background: TOKEN.surface, border: `1px solid ${TOKEN.accent + '55'}`, borderRadius: 12, padding: 20, marginBottom: 20 }}>
          <p style={{ color: TOKEN.text, fontWeight: 600, fontSize: 14, margin: '0 0 14px' }}>{t ? '新增 API 金鑰' : 'Add API Key'}</p>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 12 }}>
            <div>
              <label style={{ display: 'block', color: TOKEN.textMuted, fontSize: 12, marginBottom: 5 }}>{t ? '供應商' : 'Provider'}</label>
              <Input list="provider-presets" value={newKey.provider}
                onChange={e => setNewKey(k => ({ ...k, provider: e.target.value }))}
                placeholder="openai" />
              <datalist id="provider-presets">
                {PROVIDER_PRESETS.map(p => <option key={p} value={p} />)}
              </datalist>
            </div>
            <div>
              <label style={{ display: 'block', color: TOKEN.textMuted, fontSize: 12, marginBottom: 5 }}>Label</label>
              <Input value={newKey.label} onChange={e => setNewKey(k => ({ ...k, label: e.target.value }))} placeholder="main" />
            </div>
          </div>
          <div style={{ marginBottom: 14 }}>
            <label style={{ display: 'block', color: TOKEN.textMuted, fontSize: 12, marginBottom: 5 }}>{t ? 'API 金鑰' : 'API Key'}</label>
            <Input value={newKey.api_key} onChange={e => setNewKey(k => ({ ...k, api_key: e.target.value }))} placeholder="sk-..." type="password" />
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <Btn size="sm" onClick={handleCreate}>{t ? '儲存' : 'Save'}</Btn>
            <Btn size="sm" variant="ghost" onClick={() => { setAdding(false); setNewKey({ provider: '', label: '', api_key: '' }); }}>{t ? '取消' : 'Cancel'}</Btn>
          </div>
        </div>
      )}

      {editing && (
        <div style={{ background: TOKEN.surface, border: `1px solid ${TOKEN.accent + '55'}`, borderRadius: 12, padding: 20, marginBottom: 20 }}>
          <p style={{ color: TOKEN.text, fontWeight: 600, fontSize: 14, margin: '0 0 14px' }}>
            {t ? '編輯金鑰' : 'Edit API Key'} <span style={{ color: TOKEN.textMuted, fontWeight: 400 }}>· {editing.provider}</span>
          </p>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 14 }}>
            <div>
              <label style={{ display: 'block', color: TOKEN.textMuted, fontSize: 12, marginBottom: 5 }}>Label</label>
              <Input value={editing.label} onChange={e => setEditing(s => ({ ...s, label: e.target.value }))} />
            </div>
            <div>
              <label style={{ display: 'block', color: TOKEN.textMuted, fontSize: 12, marginBottom: 5 }}>
                {t ? '新 API 金鑰（留空保留原值）' : 'New API Key (empty = keep current)'}
              </label>
              <Input value={editing.api_key || ''} onChange={e => setEditing(s => ({ ...s, api_key: e.target.value }))} type="password" placeholder="sk-..." />
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <Btn size="sm" onClick={handleUpdate}>{t ? '儲存' : 'Save'}</Btn>
            <Btn size="sm" variant="ghost" onClick={() => setEditing(null)}>{t ? '取消' : 'Cancel'}</Btn>
          </div>
        </div>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {keys === null ? (
          <div style={{ color: TOKEN.textMuted, padding: '24px 0' }}>{t ? '載入中…' : 'Loading…'}</div>
        ) : keys.length === 0 ? (
          <div style={{ color: TOKEN.textMuted, padding: '24px 0' }}>{t ? '尚無金鑰' : 'No keys yet'}</div>
        ) : keys.map(k => (
          <div key={k.id} style={{ background: TOKEN.surface, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 12, padding: '16px 20px', display: 'flex', alignItems: 'center', gap: 16 }}>
            <div style={{ width: 110, fontSize: 13, fontWeight: 600, color: PROVIDER_COLORS[k.provider] || TOKEN.accent }}>{k.provider}</div>
            <div style={{ flex: 1, fontSize: 14, color: TOKEN.text }}>{k.label}</div>
            <div style={{ fontFamily: 'monospace', fontSize: 13, color: TOKEN.textSecondary, minWidth: 90 }}>{k.api_key_masked}</div>
            <div style={{ display: 'flex', gap: 6 }}>
              <Btn size="sm" variant="ghost" icon="edit" onClick={() => setEditing({ id: k.id, provider: k.provider, label: k.label, api_key: '' })} />
              <Btn size="sm" variant="ghost" icon="trash" onClick={() => handleDelete(k)} />
            </div>
          </div>
        ))}
      </div>

      {toast && (
        <div style={{ position: 'fixed', bottom: 24, right: 24, padding: '11px 16px', borderRadius: 10, fontSize: 13,
          background: toast.kind === 'success' ? 'rgba(34,197,94,0.18)' : 'rgba(239,68,68,0.18)',
          border: `1px solid ${toast.kind === 'success' ? 'rgba(34,197,94,0.4)' : 'rgba(239,68,68,0.4)'}`,
          color: toast.kind === 'success' ? '#4ade80' : '#f87171', zIndex: 50 }}>{toast.text}</div>
      )}
    </div>
  );
};

// ── AI Steps Tab (replaces LLMTab) ──

const STEP_KEYS_ORDER = ['answer', 'rewrite', 'summary', 'embedding', 'transcription'];

const STEP_LABELS = {
  answer:        { zh: 'Answer 模型（RAG 答案）',    en: 'Answer (RAG)' },
  rewrite:       { zh: 'Rewrite 模型（查詢改寫）',   en: 'Rewrite (query rewrite)' },
  summary:       { zh: 'Summary 模型（每集摘要）',   en: 'Summary (per-episode)' },
  embedding:     { zh: 'Embedding 模型（向量化）',   en: 'Embedding (vectorization)' },
  transcription: { zh: 'Transcription（語音轉錄）',  en: 'Transcription (speech)' },
};

// Common base_url / model presets per provider (UI hints; admin can free-type).
const BASE_URL_PRESETS_BY_PROVIDER = {
  openai: ['https://api.openai.com/v1'],
  anthropic: ['https://api.anthropic.com/v1'],
  google: ['https://generativelanguage.googleapis.com/v1'],
  'zeabur-aihub': ['https://hnd1.aihub.zeabur.ai/v1'],
};
const CHAT_MODEL_PRESETS_BY_PROVIDER = {
  openai: ['gpt-4o', 'gpt-4o-mini', 'gpt-5-mini'],
  anthropic: ['claude-opus-4-7', 'claude-sonnet-4-6', 'claude-haiku-4-5'],
  google: ['gemini-2.5-pro'],
  'zeabur-aihub': ['gpt-4o', 'gpt-4o-mini', 'gpt-5-mini'],
};
const EMBEDDING_MODEL_PRESETS = ['text-embedding-3-small', 'text-embedding-3-large'];
const WHISPER_API_MODEL_PRESETS = ['whisper-1'];
const WHISPER_LOCAL_MODEL_PRESETS = ['base', 'small', 'medium', 'large-v3'];

const AiStepsTab = ({ lang }) => {
  const t = lang === 'zh';
  const [steps, setSteps] = React.useState(null);
  const [keys, setKeys] = React.useState(null);
  const [drafts, setDrafts] = React.useState({});
  const [savingKey, setSavingKey] = React.useState(null);
  const [error, setError] = React.useState(null);
  const [toast, setToast] = React.useState(null);

  const flashToast = (text, kind = 'success') => {
    setToast({ text, kind });
    setTimeout(() => setToast(null), 3500);
  };

  const reload = React.useCallback(async () => {
    setError(null);
    try {
      const [stepsRes, keysRes] = await Promise.all([
        apiFetch('/admin/ai-steps'),
        apiFetch('/admin/api-keys'),
      ]);
      if (!stepsRes.ok) throw new Error(`steps HTTP ${stepsRes.status}`);
      if (!keysRes.ok) throw new Error(`keys HTTP ${keysRes.status}`);
      const stepsData = await stepsRes.json();
      const keysData = await keysRes.json();
      setSteps(stepsData);
      setKeys(keysData);
      // seed drafts from server state so admin sees current values in inputs
      const seeded = {};
      for (const s of stepsData) {
        seeded[s.step_key] = {
          base_url: s.base_url || '',
          model: s.model || '',
          api_key_id: s.api_key_id || '',
          extra_config: s.extra_config || {},
        };
      }
      setDrafts(seeded);
    } catch (err) { setError(err.message); }
  }, []);
  React.useEffect(() => { reload(); }, [reload]);

  const setDraft = (step_key, patch) =>
    setDrafts(d => ({ ...d, [step_key]: { ...d[step_key], ...patch } }));
  const setExtra = (step_key, patch) =>
    setDrafts(d => ({ ...d, [step_key]: { ...d[step_key], extra_config: { ...d[step_key].extra_config, ...patch } } }));

  const keysByProvider = React.useMemo(() => {
    if (!keys) return {};
    const acc = {};
    for (const k of keys) (acc[k.provider] = acc[k.provider] || []).push(k);
    return acc;
  }, [keys]);

  const providerOfKey = React.useCallback((api_key_id) => {
    if (!keys || !api_key_id) return null;
    return keys.find(k => k.id === api_key_id)?.provider || null;
  }, [keys]);

  const save = async (step) => {
    setSavingKey(step.step_key);
    const draft = drafts[step.step_key];
    let payload;
    if (step.step_type === 'whisper') {
      const provider = draft.extra_config?.provider;
      if (provider === 'faster-whisper') {
        payload = {
          step_type: 'whisper',
          base_url: null,
          model: draft.model,
          api_key_id: null,
          extra_config: { provider: 'faster-whisper', model_dir: draft.extra_config?.model_dir || '' },
        };
      } else {
        payload = {
          step_type: 'whisper',
          base_url: draft.base_url,
          model: draft.model,
          api_key_id: draft.api_key_id || null,
          extra_config: { provider: 'openai' },
        };
      }
    } else {
      payload = {
        step_type: step.step_type,
        base_url: draft.base_url,
        model: draft.model,
        api_key_id: draft.api_key_id || null,
        extra_config: draft.extra_config || {},
      };
    }
    try {
      const res = await apiFetch(`/admin/ai-steps/${step.step_key}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        const detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
        flashToast((t ? '儲存失敗：' : 'Save failed: ') + detail, 'error');
        return;
      }
      flashToast(t ? `已儲存 ${step.step_key}` : `Saved ${step.step_key}`);
      await reload();
    } catch (err) { flashToast((t ? '失敗：' : 'Failed: ') + err.message, 'error'); }
    finally { setSavingKey(null); }
  };

  if (steps === null) return <div style={{ color: TOKEN.textMuted, padding: '24px 0' }}>{t ? '載入中…' : 'Loading…'}</div>;
  if (error) return <div style={{ color: '#f87171' }}>{(t ? '載入失敗：' : 'Load failed: ') + error}</div>;

  const stepsByKey = Object.fromEntries(steps.map(s => [s.step_key, s]));

  return (
    <div style={{ maxWidth: 820 }}>
      <p style={{ margin: '0 0 18px', color: TOKEN.textSecondary, fontSize: 14 }}>
        {t ? '為每個 AI 處理步驟挑選 base_url、model 與 API 金鑰。金鑰請先到「API 金鑰管理」新增。' : 'Configure base_url, model, and api_key for each AI processing step. Add keys via "API Keys" tab first.'}
      </p>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        {STEP_KEYS_ORDER.map(sk => {
          const step = stepsByKey[sk];
          if (!step) return null;
          return (
            <AiStepSection
              key={sk}
              step={step}
              draft={drafts[sk] || { base_url: '', model: '', api_key_id: '', extra_config: {} }}
              keys={keys || []}
              keysByProvider={keysByProvider}
              providerOfKey={providerOfKey}
              setDraft={(patch) => setDraft(sk, patch)}
              setExtra={(patch) => setExtra(sk, patch)}
              onSave={() => save(step)}
              saving={savingKey === sk}
              lang={lang}
            />
          );
        })}
      </div>
      {toast && (
        <div style={{ position: 'fixed', bottom: 24, right: 24, padding: '11px 16px', borderRadius: 10, fontSize: 13,
          background: toast.kind === 'success' ? 'rgba(34,197,94,0.18)' : 'rgba(239,68,68,0.18)',
          border: `1px solid ${toast.kind === 'success' ? 'rgba(34,197,94,0.4)' : 'rgba(239,68,68,0.4)'}`,
          color: toast.kind === 'success' ? '#4ade80' : '#f87171', zIndex: 50 }}>{toast.text}</div>
      )}
    </div>
  );
};

const AiStepSection = ({ step, draft, keys, keysByProvider, providerOfKey, setDraft, setExtra, onSave, saving, lang }) => {
  const t = lang === 'zh';
  const isWhisper = step.step_type === 'whisper';
  const whisperProvider = isWhisper ? (draft.extra_config?.provider || 'openai') : null;
  const isLocalWhisper = isWhisper && whisperProvider === 'faster-whisper';

  // Embedding step: filter api_keys to provider==openai only.
  const visibleKeys = step.step_key === 'embedding'
    ? (keysByProvider.openai || [])
    : keys;

  // Provider that drives presets is whichever provider the chosen api_key has.
  const inferredProvider = providerOfKey(draft.api_key_id) || (step.step_key === 'embedding' ? 'openai' : null);

  const baseUrlPresets = inferredProvider ? (BASE_URL_PRESETS_BY_PROVIDER[inferredProvider] || []) : [];
  let modelPresets = [];
  if (step.step_type === 'chat') {
    modelPresets = inferredProvider ? (CHAT_MODEL_PRESETS_BY_PROVIDER[inferredProvider] || []) : [];
  } else if (step.step_type === 'embedding') {
    modelPresets = EMBEDDING_MODEL_PRESETS;
  } else if (isWhisper && !isLocalWhisper) {
    modelPresets = WHISPER_API_MODEL_PRESETS;
  } else if (isLocalWhisper) {
    modelPresets = WHISPER_LOCAL_MODEL_PRESETS;
  }
  const presetIdBase = `presets-${step.step_key}`;

  // Embedding model change warning: compare draft.model vs server-side step.model
  const embeddingModelChanged =
    step.step_key === 'embedding' && draft.model && step.model && draft.model !== step.model;

  return (
    <div style={{ background: TOKEN.surface, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 12, padding: '18px 22px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 14 }}>
        <p style={{ color: TOKEN.text, fontWeight: 600, fontSize: 14, margin: 0 }}>{STEP_LABELS[step.step_key][t ? 'zh' : 'en']}</p>
        <span style={{ color: TOKEN.textMuted, fontSize: 11, fontFamily: 'monospace' }}>
          {step.step_key} · {step.step_type}
        </span>
      </div>

      {isWhisper && (
        <div style={{ marginBottom: 14 }}>
          <label style={{ display: 'block', color: TOKEN.textMuted, fontSize: 12, marginBottom: 6 }}>{t ? '轉錄供應商' : 'Transcription Provider'}</label>
          <select value={whisperProvider}
            onChange={e => setExtra({ provider: e.target.value, ...(e.target.value === 'faster-whisper' ? { model_dir: draft.extra_config?.model_dir || '/models/faster-whisper' } : {}) })}
            style={{ width: '100%', background: TOKEN.surfaceRaised, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 8, padding: '9px 12px', color: TOKEN.text, fontSize: 14, outline: 'none', fontFamily: 'inherit' }}>
            <option value="openai">openai (Whisper API)</option>
            <option value="faster-whisper" disabled>{t ? 'faster-whisper（暫停使用 — 容器重啟會中斷）' : 'faster-whisper (disabled — restarts truncate progress)'}</option>
          </select>
        </div>
      )}

      {!isLocalWhisper && (
        <>
          <div style={{ marginBottom: 14 }}>
            <label style={{ display: 'block', color: TOKEN.textMuted, fontSize: 12, marginBottom: 6 }}>
              {t ? '供應商' : 'Provider'} {step.step_key === 'embedding' && (
                <span style={{ color: TOKEN.textMuted }}>{t ? '（必須是 openai provider 的金鑰）' : '(must be an openai-provider key)'}</span>
              )}
            </label>
            <select value={draft.api_key_id || ''}
              onChange={e => setDraft({ api_key_id: e.target.value || '' })}
              style={{ width: '100%', background: TOKEN.surfaceRaised, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 8, padding: '9px 12px', color: TOKEN.text, fontSize: 14, outline: 'none', fontFamily: 'inherit' }}>
              <option value="">{t ? '— 未選擇 —' : '— none —'}</option>
              {visibleKeys.map(k => (
                <option key={k.id} value={k.id}>{k.provider} · {k.label} ({k.api_key_masked})</option>
              ))}
            </select>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 14 }}>
            <div>
              <label style={{ display: 'block', color: TOKEN.textMuted, fontSize: 12, marginBottom: 6 }}>Base URL</label>
              <Input list={`${presetIdBase}-baseurl`} value={draft.base_url}
                onChange={e => setDraft({ base_url: e.target.value })}
                placeholder="https://api.openai.com/v1" />
              <datalist id={`${presetIdBase}-baseurl`}>
                {baseUrlPresets.map(u => <option key={u} value={u} />)}
              </datalist>
            </div>
            <div>
              <label style={{ display: 'block', color: TOKEN.textMuted, fontSize: 12, marginBottom: 6 }}>Model</label>
              <Input list={`${presetIdBase}-model`} value={draft.model}
                onChange={e => setDraft({ model: e.target.value })}
                placeholder="gpt-4o" />
              <datalist id={`${presetIdBase}-model`}>
                {modelPresets.map(m => <option key={m} value={m} />)}
              </datalist>
            </div>
          </div>
        </>
      )}

      {isLocalWhisper && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 14 }}>
          <div>
            <label style={{ display: 'block', color: TOKEN.textMuted, fontSize: 12, marginBottom: 6 }}>{t ? '模型 Size' : 'Model Size'}</label>
            <Input list={`${presetIdBase}-model`} value={draft.model}
              onChange={e => setDraft({ model: e.target.value })}
              placeholder="base" />
            <datalist id={`${presetIdBase}-model`}>
              {WHISPER_LOCAL_MODEL_PRESETS.map(m => <option key={m} value={m} />)}
            </datalist>
          </div>
          <div>
            <label style={{ display: 'block', color: TOKEN.textMuted, fontSize: 12, marginBottom: 6 }}>Model Dir</label>
            <Input value={draft.extra_config?.model_dir || ''}
              onChange={e => setExtra({ model_dir: e.target.value })}
              placeholder="/models/faster-whisper" />
          </div>
        </div>
      )}

      {embeddingModelChanged && (
        <div style={{ padding: '9px 13px', borderRadius: 8, fontSize: 12, marginBottom: 12,
          background: 'rgba(245,158,11,0.12)', border: '1px solid rgba(245,158,11,0.4)', color: '#fbbf24' }}>
          {t ? '⚠️ 改 model 會讓既有 vector 失效，需要 reindex。' : '⚠️ Changing the model invalidates existing vectors; reindex required.'}
        </div>
      )}

      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <Btn icon="check" onClick={onSave} disabled={saving} size="sm">
          {saving ? (t ? '儲存中…' : 'Saving…') : (t ? '儲存' : 'Save')}
        </Btn>
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
        const res = await apiFetch(`/shows/${showId}/transcription-status`, { signal: controller.signal });
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
      const res = await apiFetch(`/admin/queue-status`);
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
      const res = await apiFetch(`/admin/schedules`);
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
      const res = await apiFetch(`/shows/${editState.item.show_id}/schedule`, {
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
          const res = await apiFetch(`/shows/${id}/sync`, { method: 'POST' });
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
          const res = await apiFetch(`/shows/${id}/transcribe-latest`, { method: 'POST' });
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
      const res = await apiFetch(`/shows/${item.show_id}/transcribe-latest`, { method: 'POST' });
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
      const res = await apiFetch(`/rss-preview?url=${encodeURIComponent(form.rss)}`);
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
      const createRes = await apiFetch(`/shows`, {
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
        const listRes = await apiFetch(`/shows`);
        const list = await listRes.json();
        show = list.find(s => s.rss_url === form.rss);
        if (!show) throw new Error(t ? '找不到對應節目' : 'Show not found');
      }
      await apiFetch(`/shows/${show.id}/schedule`, {
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
      const res = await apiFetch(`/shows/${item.show_id}/sync`, { method: 'POST' });
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
      const res = await apiFetch(`/shows/${item.show_id}/schedule`, { method: 'DELETE' });
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
      const res = await apiFetch(`/shows/${item.show_id}`, { method: 'DELETE' });
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
      const res = await apiFetch(`/admin/queue`);
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
