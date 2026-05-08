// Admin Topic Segmentation Audit — sample 50 labelled segments with context.
const AdminTopicSegAuditTab = ({ lang }) => {
  const t = lang === 'zh';
  const [items, setItems] = React.useState(null);
  const [error, setError] = React.useState(null);
  const [reloading, setReloading] = React.useState(false);

  const reload = React.useCallback(async () => {
    setError(null);
    setReloading(true);
    try {
      const res = await apiFetch('/admin/topic-seg/audit-sample?n=50');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setItems(await res.json());
    } catch (err) {
      setError(err.message || String(err));
    } finally {
      setReloading(false);
    }
  }, []);
  React.useEffect(() => { reload(); }, [reload]);

  return (
    <div style={{ maxWidth: 980 }}>
      <p style={{ color: TOKEN.textSecondary, fontSize: 13, marginTop: 0 }}>
        {t ? 'LLM 標註後抽 50 段隨機樣本，協助你檢查標籤合理性。粗體是被標的段落，上下兩行是前後文。' : 'Random sample of 50 labelled segments. The bold middle line is the labelled segment.'}
      </p>

      <div style={{ marginBottom: 16 }}>
        <Btn variant="secondary" onClick={reload} disabled={reloading}>
          {reloading ? (t ? '抽樣中…' : 'Sampling…') : (t ? '重抽樣' : 'Re-sample')}
        </Btn>
      </div>

      {error && (
        <div style={{ color: '#f87171', fontSize: 13, marginBottom: 12 }}>
          {error}
        </div>
      )}

      {items === null ? (
        <div style={{ color: TOKEN.textMuted, fontSize: 13 }}>{t ? '載入中…' : 'Loading…'}</div>
      ) : items.length === 0 ? (
        <div style={{ color: TOKEN.textMuted, fontSize: 13 }}>{t ? '尚無已標註的段落' : 'No labelled segments yet'}</div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {items.map((it, i) => (
            <div key={it.segment_id} style={{ background: TOKEN.surface, padding: 16, borderRadius: 8, border: `1px solid ${TOKEN.surfaceBorder}` }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
                <span style={{ color: TOKEN.textMuted, fontSize: 12 }}>#{i + 1}</span>
                <Badge variant={it.is_show_specific_label ? 'success' : 'default'}>
                  {it.topic_label}
                </Badge>
                <span style={{ color: TOKEN.textMuted, fontSize: 12 }}>
                  {it.episode_title} @ {it.start_time.toFixed(1)}s
                </span>
              </div>
              <div style={{ color: TOKEN.textMuted, fontSize: 13, marginBottom: 4 }}>
                {it.prev_text || (t ? '（節目開頭）' : '(episode start)')}
              </div>
              <div style={{ color: TOKEN.text, fontSize: 14, fontWeight: 600, padding: '6px 10px', background: TOKEN.surfaceRaised, borderRadius: 4, marginBottom: 4 }}>
                {it.text}
              </div>
              <div style={{ color: TOKEN.textMuted, fontSize: 13 }}>
                {it.next_text || (t ? '（節目結尾）' : '(episode end)')}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
