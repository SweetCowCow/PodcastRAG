// External API Status tab — polls /admin/external-api-status every 15s while mounted.
const ExternalApiStatusTab = ({ lang }) => {
  const t = lang === 'zh';
  const [data, setData] = React.useState(null);
  const [error, setError] = React.useState(null);

  React.useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    const fetchOnce = async () => {
      try {
        const res = await fetch(`${API_BASE}/admin/external-api-status`, { signal: controller.signal });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const json = await res.json();
        if (!cancelled) { setData(json); setError(null); }
      } catch (err) {
        if (cancelled || err.name === 'AbortError') return;
        setError(err.message || String(err));
      }
    };
    fetchOnce();
    const id = setInterval(fetchOnce, 15000);
    return () => { cancelled = true; controller.abort(); clearInterval(id); };
  }, []);

  const apiNames = {
    openai_whisper: 'OpenAI Whisper',
    openai_chat: 'OpenAI Chat',
    openai_embedding: 'OpenAI Embedding',
  };

  return (
    <div style={{ maxWidth: 820 }}>
      <p style={{ margin: '0 0 20px', color: TOKEN.textSecondary, fontSize: 14 }}>
        {t ? '外部 API 最近呼叫狀態，每 15 秒自動更新。' : 'Most recent external API call status; auto-refreshes every 15 seconds.'}
      </p>
      {error && !data && (
        <div style={{ marginBottom: 16, padding: 12, background: 'rgba(239,68,68,0.12)', border: '1px solid rgba(239,68,68,0.3)', borderRadius: 8, color: '#f87171', fontSize: 13 }}>
          {(t ? '載入失敗：' : 'Failed to load: ') + error}
        </div>
      )}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {(data?.apis || []).map(api => (
          <ApiStatusCard
            key={api.name}
            entry={api}
            label={apiNames[api.name] || api.name}
            lang={lang}
          />
        ))}
      </div>
    </div>
  );
};

const ApiStatusCard = ({ entry, label, lang }) => {
  const t = lang === 'zh';
  const { latest, degraded } = entry;
  const isHealthy = latest && latest.ok;
  const badge = latest
    ? (isHealthy
        ? { variant: 'success', label: t ? '正常' : 'Healthy' }
        : categoryToBadge(latest.error_category, lang))
    : null;

  return (
    <div style={{ background: TOKEN.surface, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 12, padding: '18px 22px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <span style={{ color: TOKEN.text, fontWeight: 600, fontSize: 15 }}>{label}</span>
        {badge && <Badge variant={badge.variant}>{badge.label}</Badge>}
      </div>
      {!latest && (
        <div style={{ marginTop: 10, color: TOKEN.textMuted, fontSize: 13 }}>
          {t ? '尚無紀錄' : 'No calls recorded yet'}
        </div>
      )}
      {latest && (
        <div style={{ marginTop: 10, display: 'flex', gap: 18, flexWrap: 'wrap', fontSize: 12, color: TOKEN.textMuted, alignItems: 'center' }}>
          <span><Icon name="clock" size={11} style={{ marginRight: 4 }} />{formatRelativeTime(latest.ts_ms, lang)}</span>
          {latest.http_status != null && (
            <span>HTTP {latest.http_status}</span>
          )}
          {typeof latest.duration_ms === 'number' && (
            <span>{latest.duration_ms} ms</span>
          )}
        </div>
      )}
      {degraded && (
        <div style={{ marginTop: 10, color: TOKEN.textMuted, fontSize: 12, fontStyle: 'italic' }}>
          {t ? '監測服務異常，最近狀態可能不準確' : 'Monitoring service degraded; status may be stale'}
        </div>
      )}
    </div>
  );
};

Object.assign(window, { ExternalApiStatusTab });
