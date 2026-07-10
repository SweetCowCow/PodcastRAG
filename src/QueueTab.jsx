// ── Processing Overview block ──
// Renders at the top of the Queue Tab. Shows three progress bars
// (transcription / summary / topic segmentation) sourced from
// GET /admin/processing-stats, polling every 30 seconds. On poll error
// shows a small warning text without breaking the queue table below.
// Spec: openspec/changes/backfill-progress-admin-tab/specs/...
const PO_POLL_INTERVAL_MS = 30000;

const _formatInt = (n) => {
  if (typeof n !== 'number' || !Number.isFinite(n)) return '—';
  return n.toLocaleString('en-US');
};

const _formatPct = (ratio) => {
  if (typeof ratio !== 'number' || !Number.isFinite(ratio)) return '0.0%';
  return (ratio * 100).toFixed(1) + '%';
};

const _formatTaipeiTime = (iso) => {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    // Convert to Asia/Taipei (UTC+8). toLocaleTimeString lets us pick the zone.
    return d.toLocaleTimeString('en-GB', {
      hour: '2-digit',
      minute: '2-digit',
      timeZone: 'Asia/Taipei',
    });
  } catch {
    return '—';
  }
};

const ProgressRow = ({ label, sublabel, ratio, primary, secondary }) => {
  const pct = Math.max(0, Math.min(1, ratio || 0)) * 100;
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{
        display: 'flex', alignItems: 'baseline', justifyContent: 'space-between',
        gap: 12, marginBottom: 6, flexWrap: 'wrap',
      }}>
        <div style={{ color: TOKEN.text, fontSize: 13, fontWeight: 600 }}>
          {label}
          {sublabel && (
            <span style={{ color: TOKEN.textMuted, fontWeight: 400, marginLeft: 8, fontSize: 12 }}>
              {sublabel}
            </span>
          )}
        </div>
        <div style={{ color: TOKEN.textSecondary, fontSize: 12, fontVariantNumeric: 'tabular-nums' }}>
          {primary}
        </div>
      </div>
      <div style={{
        height: 8, background: TOKEN.surfaceRaised, borderRadius: 4,
        overflow: 'hidden', border: `1px solid ${TOKEN.surfaceBorder}`,
      }}>
        <div style={{
          width: pct + '%',
          height: '100%',
          background: TOKEN.accent,
          transition: 'width 0.3s ease',
        }} />
      </div>
      {secondary && (
        <div style={{ color: TOKEN.textMuted, fontSize: 11, marginTop: 4 }}>
          {secondary}
        </div>
      )}
    </div>
  );
};

const ProcessingOverview = ({ lang }) => {
  const t = lang === 'zh';
  const [stats, setStats] = React.useState(null);
  const [pollError, setPollError] = React.useState(false);
  const [showFailures, setShowFailures] = React.useState(false);
  const [lastUpdated, setLastUpdated] = React.useState(null);

  React.useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const res = await apiFetch('/admin/processing-stats');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const body = await res.json();
        if (cancelled) return;
        setStats(body);
        setLastUpdated(body.as_of || new Date().toISOString());
        setPollError(false);
      } catch (e) {
        if (!cancelled) setPollError(true);
      }
    };
    poll();
    const id = setInterval(poll, PO_POLL_INTERVAL_MS);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  const containerStyle = {
    background: TOKEN.surface,
    border: `1px solid ${TOKEN.surfaceBorder}`,
    borderRadius: 10,
    padding: '16px 18px',
    marginBottom: 20,
  };

  if (!stats && !pollError) {
    return (
      <div style={containerStyle}>
        <div style={{ color: TOKEN.textMuted, fontSize: 13 }}>
          {t ? '載入進度中…' : 'Loading progress…'}
        </div>
      </div>
    );
  }

  const tx = stats?.transcription || { completed_episodes: 0, total_episodes: 0, ratio: 0 };
  const sm = stats?.summary || { completed_episodes: 0, total_episodes: 0, ratio: 0 };
  const tp = stats?.topic_seg || {
    completed_segments: 0, total_segments: 0, ratio: 0,
    completed_episodes: 0, total_episodes_with_transcript: 0, episode_ratio: 0,
  };
  const l24 = stats?.last_24h || { transcribed_episodes: 0, labeled_segments: 0, failures: [] };
  const failures = l24.failures || [];
  const failTotal = failures.reduce((acc, f) => acc + (f.count || 0), 0);

  return (
    <div style={containerStyle}>
      <div style={{
        display: 'flex', alignItems: 'baseline', justifyContent: 'space-between',
        gap: 12, marginBottom: 14, flexWrap: 'wrap',
      }}>
        <div style={{ color: TOKEN.text, fontSize: 15, fontWeight: 700 }}>
          {t ? '進度概覽' : 'Processing Overview'}
        </div>
        {pollError && (
          <div style={{ color: '#f59e0b', fontSize: 11 }}>
            {t ? '更新失敗，重試中…' : 'Update failed, retrying…'}
          </div>
        )}
      </div>

      {stats && (
        <>
          <ProgressRow
            label={t ? '轉錄' : 'Transcription'}
            ratio={tx.ratio}
            primary={`${_formatInt(tx.completed_episodes)} / ${_formatInt(tx.total_episodes)} ${t ? '集' : 'eps'} (${_formatPct(tx.ratio)})`}
          />
          <ProgressRow
            label={t ? '摘要' : 'Summary'}
            ratio={sm.ratio}
            primary={`${_formatInt(sm.completed_episodes)} / ${_formatInt(sm.total_episodes)} ${t ? '集' : 'eps'} (${_formatPct(sm.ratio)})`}
          />
          <ProgressRow
            label={t ? '分類' : 'Topic'}
            ratio={tp.ratio}
            primary={`${_formatInt(tp.completed_segments)} / ${_formatInt(tp.total_segments)} ${t ? '段' : 'segs'} (${_formatPct(tp.ratio)})`}
            secondary={
              t
                ? `(${_formatInt(tp.completed_episodes)} / ${_formatInt(tp.total_episodes_with_transcript)} 集已完整標完)`
                : `(${_formatInt(tp.completed_episodes)} / ${_formatInt(tp.total_episodes_with_transcript)} eps fully labelled)`
            }
          />

          <div style={{
            borderTop: `1px solid ${TOKEN.surfaceBorder}`,
            marginTop: 14, paddingTop: 12,
            color: TOKEN.textSecondary, fontSize: 12,
          }}>
            <div style={{ marginBottom: 6, color: TOKEN.text, fontWeight: 600 }}>
              {t ? '最近 24 小時' : 'Last 24 Hours'}
            </div>
            <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'center' }}>
              <span>
                {t ? `轉錄 +${_formatInt(l24.transcribed_episodes)} 集` : `Transcribed +${_formatInt(l24.transcribed_episodes)} eps`}
              </span>
              <span>
                {t ? `分類 +${_formatInt(l24.labeled_segments)} 段` : `Labelled +${_formatInt(l24.labeled_segments)} segs`}
              </span>
              <span>
                {t ? `失敗 ${_formatInt(failTotal)} 件` : `Failures ${_formatInt(failTotal)}`}
              </span>
              {failures.length > 0 && (
                <button
                  type="button"
                  onClick={() => setShowFailures(s => !s)}
                  style={{
                    background: 'transparent',
                    border: `1px solid ${TOKEN.surfaceBorder}`,
                    borderRadius: 6,
                    padding: '4px 10px',
                    color: TOKEN.textSecondary,
                    fontSize: 11,
                    cursor: 'pointer',
                    fontFamily: 'inherit',
                  }}
                >
                  {showFailures
                    ? (t ? '收起失敗清單' : 'Hide Failures')
                    : (t ? '查看失敗清單' : 'Show Failures')}
                </button>
              )}
            </div>
            {showFailures && failures.length > 0 && (
              <div style={{
                marginTop: 10, background: TOKEN.surfaceRaised,
                border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 6,
                padding: '8px 12px',
              }}>
                <table style={{ width: '100%', fontSize: 11, color: TOKEN.textSecondary, borderCollapse: 'collapse' }}>
                  <thead>
                    <tr style={{ textAlign: 'left', color: TOKEN.textMuted }}>
                      <th style={{ padding: '4px 8px', fontWeight: 600 }}>{t ? '任務' : 'Task'}</th>
                      <th style={{ padding: '4px 8px', fontWeight: 600, width: 60 }}>{t ? '次數' : 'Count'}</th>
                      <th style={{ padding: '4px 8px', fontWeight: 600 }}>{t ? '範例錯誤' : 'Sample Error'}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {failures.map((f, i) => (
                      <tr key={i} style={{ borderTop: `1px solid ${TOKEN.surfaceBorder}` }}>
                        <td style={{ padding: '4px 8px', wordBreak: 'break-all' }}>
                          <code style={{ fontSize: 10 }}>{f.task_name}</code>
                        </td>
                        <td style={{ padding: '4px 8px', fontVariantNumeric: 'tabular-nums' }}>{f.count}</td>
                        <td style={{ padding: '4px 8px', wordBreak: 'break-word' }}>
                          {(f.sample_error || '').slice(0, 100)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {lastUpdated && (
            <div style={{
              color: TOKEN.textMuted, fontSize: 11, marginTop: 10,
              textAlign: 'right',
            }}>
              {t ? '上次更新：' : 'Last Updated: '}{_formatTaipeiTime(lastUpdated)} {t ? '台北' : 'Taipei'}
            </div>
          )}
        </>
      )}
    </div>
  );
};

// Summary status badge — admin only. Hidden when transcript not yet completed.
const SummaryBadge = ({ status, error, lang }) => {
  if (!status) return null;
  const t = lang === 'zh';
  if (status === 'pending' || status === 'running') {
    return <Badge variant="default">{t ? '摘要中' : 'Summarising'}</Badge>;
  }
  if (status === 'done') {
    return <Badge variant="success">{t ? '已摘要' : 'Summarised'}</Badge>;
  }
  if (status === 'failed') {
    const fallback = t
      ? '摘要失敗（未記錄錯誤訊息）'
      : 'Summary task failed (no error message recorded)';
    let tip = error && error.length > 0 ? error : fallback;
    if (tip.length > 200) tip = tip.slice(0, 200) + '…';
    return (
      <span title={tip}>
        <Badge variant="danger">{t ? '摘要失敗' : 'Summary failed'}</Badge>
      </span>
    );
  }
  return null;
};

// Transcription Queue Tab — admin queue rows + max_concurrent input + drag reorder
const QueueTab = ({ lang }) => {
  const t = lang === 'zh';
  const { isMobile } = useViewport();
  const [queue, setQueue] = React.useState({ pending: [], running: [], completed: [], failed: [], cancelled: [] });
  const [settings, setSettings] = React.useState({ max_concurrent_transcriptions: 1 });
  const [maxLocal, setMaxLocal] = React.useState('');
  const [maxError, setMaxError] = React.useState('');
  const [error, setError] = React.useState(null);
  const [confirmOpen, setConfirmOpen] = React.useState(false);
  const [confirmTarget, setConfirmTarget] = React.useState(null);
  const [confirmLoading, setConfirmLoading] = React.useState(false);
  const [actionError, setActionError] = React.useState({}); // {row_id: msg}
  const [draggingId, setDraggingId] = React.useState(null);
  const [dragInFlight, setDragInFlight] = React.useState(false);
  const [pendingOverride, setPendingOverride] = React.useState(null); // optimistic order array of row ids
  const [activeTab, setActiveTab] = React.useState('active'); // 'active' | 'completed' | 'closed'
  const debounceRef = React.useRef(null);

  // Polling
  React.useEffect(() => {
    let cancelled = false;
    const fetchAll = async () => {
      try {
        const [qRes, sRes] = await Promise.all([
          apiFetch(`/admin/queue`),
          apiFetch(`/admin/settings`),
        ]);
        if (!qRes.ok || !sRes.ok) throw new Error(`HTTP ${qRes.status}/${sRes.status}`);
        const q = await qRes.json();
        const s = await sRes.json();
        if (cancelled) return;
        setQueue(q);
        setSettings(s);
        setMaxLocal(prev => prev === '' ? String(s.max_concurrent_transcriptions) : prev);
        setError(null);
      } catch (err) {
        if (!cancelled) setError(err.message || String(err));
      }
    };
    fetchAll();
    const id = setInterval(fetchAll, 5000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  const refetch = async () => {
    try {
      const qRes = await apiFetch(`/admin/queue`);
      if (qRes.ok) setQueue(await qRes.json());
    } catch {}
  };

  const [toast, setToast] = React.useState(null);
  const showToast = (msg) => { setToast(msg); setTimeout(() => setToast(null), 4000); };

  const regenerateSummary = async (row) => {
    clearActionErr(row.id);
    try {
      const res = await apiFetch(
        `/admin/episodes/${row.episode_id}/regenerate-summary`,
        { method: 'POST' }
      );
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setActionErr(row.id, body.detail || `HTTP ${res.status}`);
        return;
      }
      // Optimistic UI: flip to summarising; refetch picks up real state on next poll.
      row.ai_summary_status = 'pending';
      await refetch();
    } catch (e) {
      setActionErr(row.id, e.message || String(e));
    }
  };

  const [backfillBusy, setBackfillBusy] = React.useState(false);
  const runBackfill = async () => {
    if (backfillBusy) return;
    setBackfillBusy(true);
    try {
      const res = await apiFetch(`/admin/episodes/backfill-summary`, { method: 'POST' });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        showToast((t ? '批次補摘要失敗：' : 'Backfill failed: ') + (body.detail || `HTTP ${res.status}`));
        return;
      }
      const data = await res.json();
      showToast(t ? `已排入 ${data.enqueued_count} 集` : `Queued ${data.enqueued_count} episodes`);
      await refetch();
    } catch (e) {
      showToast((t ? '批次補摘要失敗：' : 'Backfill failed: ') + (e.message || String(e)));
    } finally {
      setBackfillBusy(false);
    }
  };

  const setActionErr = (id, msg) => setActionError(e => ({ ...e, [id]: msg }));
  const clearActionErr = (id) => setActionError(e => { const c = { ...e }; delete c[id]; return c; });

  // ── Cancel pending ──
  const cancelPending = async (row) => {
    clearActionErr(row.id);
    try {
      const res = await apiFetch(`/admin/queue/${row.id}/cancel`, { method: 'POST' });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setActionErr(row.id, body.detail || `HTTP ${res.status}`);
        return;
      }
      await refetch();
    } catch (e) {
      setActionErr(row.id, e.message || String(e));
    }
  };

  // ── Force-cancel running ──
  const openForceCancel = (row) => { setConfirmTarget(row); setConfirmOpen(true); };
  const closeConfirm = () => { if (!confirmLoading) { setConfirmOpen(false); setConfirmTarget(null); } };
  const confirmForceCancel = async () => {
    if (!confirmTarget) return;
    setConfirmLoading(true);
    clearActionErr(confirmTarget.id);
    try {
      const res = await apiFetch(`/admin/queue/${confirmTarget.id}/cancel?force=true`, { method: 'POST' });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setActionErr(confirmTarget.id, body.detail || `HTTP ${res.status}`);
      } else {
        await refetch();
      }
    } catch (e) {
      setActionErr(confirmTarget.id, e.message || String(e));
    } finally {
      setConfirmLoading(false);
      setConfirmOpen(false);
      setConfirmTarget(null);
    }
  };

  // ── Retry / Ignore / Unignore ──
  const retryRow = async (row) => {
    clearActionErr(row.id);
    try {
      const res = await apiFetch(`/episodes/${row.episode_id}/transcribe`, { method: 'POST' });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setActionErr(row.id, body.detail || `HTTP ${res.status}`);
      }
    } catch (e) { setActionErr(row.id, e.message || String(e)); }
  };
  const ignoreRow = async (row) => {
    clearActionErr(row.id);
    try {
      const res = await apiFetch(`/admin/queue/${row.id}/ignore`, { method: 'POST' });
      if (!res.ok) setActionErr(row.id, `HTTP ${res.status}`);
    } catch (e) { setActionErr(row.id, e.message || String(e)); }
  };
  const unignoreRow = async (row) => {
    clearActionErr(row.id);
    try {
      const res = await apiFetch(`/admin/queue/${row.id}/unignore`, { method: 'POST' });
      if (!res.ok) setActionErr(row.id, `HTTP ${res.status}`);
    } catch (e) { setActionErr(row.id, e.message || String(e)); }
  };

  // ── max_concurrent input + debounce 500ms ──
  const onMaxChange = (e) => {
    const val = e.target.value;
    setMaxLocal(val);
    setMaxError('');
    const num = parseInt(val, 10);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      if (Number.isNaN(num)) return;
      try {
        const res = await apiFetch(`/admin/settings`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ max_concurrent_transcriptions: num }),
        });
        if (res.status === 422) {
          const body = await res.json().catch(() => ({}));
          setMaxError(typeof body.detail === 'string' ? body.detail : (t ? '數值無效（範圍 1–3）' : 'Invalid value (range 1–3)'));
          setMaxLocal(String(settings.max_concurrent_transcriptions));
          return;
        }
        if (!res.ok) {
          setMaxError(`HTTP ${res.status}`);
          return;
        }
        const data = await res.json();
        setSettings(data);
        setMaxLocal(String(data.max_concurrent_transcriptions));
      } catch (err) {
        setMaxError(err.message || String(err));
      }
    }, 500);
  };

  const maxNum = parseInt(maxLocal, 10);
  const showMaxWarning = !Number.isNaN(maxNum) && (maxNum > 3 || maxNum < 1);

  // ── Drag reorder ──
  // Compute display order for pending: prefer pendingOverride array of ids if set
  const pendingDisplay = React.useMemo(() => {
    if (!pendingOverride) return queue.pending;
    const byId = Object.fromEntries(queue.pending.map(r => [r.id, r]));
    const ordered = pendingOverride.map(id => byId[id]).filter(Boolean);
    // include any new pending rows not in override (newly enqueued)
    const seen = new Set(pendingOverride);
    queue.pending.forEach(r => { if (!seen.has(r.id)) ordered.push(r); });
    return ordered;
  }, [queue.pending, pendingOverride]);

  // ── Mobile arrow-button reorder ──
  const moveRow = async (row, direction) => {
    if (dragInFlight) return;
    const order = pendingDisplay;
    const i = order.findIndex(r => r.id === row.id);
    if (i < 0) return;
    const targetIdx = direction === 'up' ? i - 1 : i + 1;
    if (targetIdx < 0 || targetIdx >= order.length) return;
    const target = order[targetIdx];
    clearActionErr(row.id);
    // optimistic reorder
    const previousOverride = pendingOverride;
    const newOrder = order.map(r => r.id);
    newOrder.splice(i, 1);
    newOrder.splice(targetIdx, 0, row.id);
    setPendingOverride(newOrder);
    setDragInFlight(true);
    try {
      const res = await apiFetch(`/admin/queue/${row.id}/position`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ position: target.position }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setActionErr(row.id, body.detail || `HTTP ${res.status}`);
        setPendingOverride(previousOverride);
        return;
      }
      await refetch();
      setPendingOverride(null);
    } catch (err) {
      setActionErr(row.id, err.message || String(err));
      setPendingOverride(previousOverride);
    } finally {
      setDragInFlight(false);
    }
  };

  const onDragStart = (e, row) => {
    if (dragInFlight) { e.preventDefault(); return; }
    e.dataTransfer.setData('text/plain', row.id);
    e.dataTransfer.effectAllowed = 'move';
    setDraggingId(row.id);
  };
  const onDragEnd = () => { setDraggingId(null); };
  const onDragOverPending = (e) => { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; };
  const onDropPending = async (e, targetRow) => {
    e.preventDefault();
    if (dragInFlight) return;
    const sourceId = e.dataTransfer.getData('text/plain');
    if (!sourceId || sourceId === targetRow.id) { setDraggingId(null); return; }
    const sourceRow = queue.pending.find(r => r.id === sourceId);
    if (!sourceRow) { setDraggingId(null); return; }

    // optimistic reorder: move sourceId to targetRow's index
    const currentOrder = pendingDisplay.map(r => r.id);
    const fromIdx = currentOrder.indexOf(sourceId);
    const toIdx = currentOrder.indexOf(targetRow.id);
    if (fromIdx === -1 || toIdx === -1) { setDraggingId(null); return; }
    const newOrder = [...currentOrder];
    newOrder.splice(fromIdx, 1);
    newOrder.splice(toIdx, 0, sourceId);
    const previousOverride = pendingOverride;
    setPendingOverride(newOrder);
    setDraggingId(null);
    setDragInFlight(true);
    try {
      const res = await apiFetch(`/admin/queue/${sourceId}/position`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ position: targetRow.position }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setActionErr(sourceId, body.detail || `HTTP ${res.status}`);
        setPendingOverride(previousOverride);
        return;
      }
      await refetch();
      setPendingOverride(null);
    } catch (err) {
      setActionErr(sourceId, err.message || String(err));
      setPendingOverride(previousOverride);
    } finally {
      setDragInFlight(false);
    }
  };

  // ── Row rendering ──
  const formatTs = (iso) => {
    if (!iso) return '—';
    const ms = new Date(iso).getTime();
    if (Number.isNaN(ms)) return '—';
    return formatRelativeTime(ms, lang);
  };

  const Row = ({ row, status, canMoveUp, canMoveDown, position }) => {
    const isPending = status === 'pending';
    const isRunning = status === 'running';
    const isFailed = status === 'failed';
    const ignored = row.ignored;
    const dragging = draggingId === row.id;
    const errMsg = actionError[row.id];
    const dragEnabled = isPending && !dragInFlight && !isMobile;
    return (
      <div
        draggable={dragEnabled}
        onDragStart={dragEnabled ? (e) => onDragStart(e, row) : undefined}
        onDragEnd={dragEnabled ? onDragEnd : undefined}
        onDragOver={dragEnabled ? onDragOverPending : undefined}
        onDrop={dragEnabled ? (e) => onDropPending(e, row) : undefined}
        style={{
          background: ignored ? TOKEN.bg : TOKEN.surface,
          border: `1px solid ${TOKEN.surfaceBorder}`,
          borderRadius: 8,
          padding: '12px 14px',
          display: 'flex',
          gap: isMobile ? 8 : 12,
          flexDirection: isMobile ? 'column' : 'row',
          alignItems: isMobile ? 'stretch' : 'flex-start',
          opacity: ignored ? 0.55 : (dragging ? 0.4 : 1),
          cursor: dragEnabled ? 'grab' : (isPending && dragInFlight && !isMobile ? 'wait' : 'default'),
          transition: 'opacity 0.15s',
        }}
      >
        {isPending && typeof position === 'number' && (
          <span title={t ? `排隊順位 ${position}` : `Queue position ${position}`}
            style={{
              flexShrink: 0,
              display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
              width: 26, height: 26, borderRadius: '50%',
              background: TOKEN.accentDim, color: TOKEN.accent,
              fontSize: 12, fontWeight: 700, fontVariantNumeric: 'tabular-nums',
              marginTop: 1,
            }}>
            {position}
          </span>
        )}
        {isPending && !isMobile && (
          <span style={{ color: TOKEN.textMuted, fontSize: 14, marginTop: 2 }}>⋮⋮</span>
        )}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 4 }}>
            <span style={{ color: TOKEN.text, fontWeight: 600, fontSize: 14 }}>
              {row.episode_title || row.episode_id.slice(0, 8)}
            </span>
            <span style={{ color: TOKEN.textMuted, fontSize: 12 }}>{row.show_title || ''}</span>
            <Badge variant={
              status === 'completed' ? 'success' :
              status === 'failed' ? 'danger' :
              status === 'running' ? 'warning' :
              status === 'cancelled' ? 'muted' : 'default'
            }>
              {status}
            </Badge>
            {ignored && <Badge variant="muted">{t ? '已忽略' : 'Ignored'}</Badge>}
            {row.whisper_model && row.whisper_model.startsWith('external:') && (
              <Badge variant="muted">{row.whisper_model}</Badge>
            )}
            {status === 'completed' && <SummaryBadge status={row.ai_summary_status} error={row.ai_summary_error} lang={lang} />}
            {status === 'completed' && row.ai_summary_status === 'failed' && (
              <Btn size="sm" variant="ghost" icon="refresh" onClick={() => regenerateSummary(row)}>
                {t ? '重跑摘要' : 'Regenerate'}
              </Btn>
            )}
          </div>
          <div style={{ color: TOKEN.textSecondary, fontSize: 12, display: 'flex', gap: 14, flexWrap: 'wrap' }}>
            <span>{t ? '排隊：' : 'Enqueued: '}{formatTs(row.enqueued_at)}</span>
            {row.started_at && <span>{t ? '開始：' : 'Started: '}{formatTs(row.started_at)}</span>}
            {row.finished_at && <span>{t ? '完成：' : 'Finished: '}{formatTs(row.finished_at)}</span>}
          </div>
          {row.error_message && (
            <div style={{ color: TOKEN.danger || '#f87171', fontSize: 12, marginTop: 6, wordBreak: 'break-word' }}>
              {row.error_message}
            </div>
          )}
          {row.celery_task_id && (
            <details style={{ marginTop: 6 }}>
              <summary style={{ color: TOKEN.textMuted, fontSize: 11, cursor: 'pointer' }}>
                {t ? 'Celery task id' : 'Celery task id'}
              </summary>
              <code style={{ color: TOKEN.textMuted, fontSize: 11 }}>{row.celery_task_id}</code>
            </details>
          )}
          {errMsg && (
            <div style={{ color: '#f87171', fontSize: 12, marginTop: 6 }}>
              {errMsg}
            </div>
          )}
        </div>
        <div style={{ display: 'flex', gap: 6, flexShrink: 0, flexWrap: isMobile ? 'wrap' : 'nowrap' }}>
          {isPending && isMobile && (
            <>
              <Btn size="sm" variant="ghost" icon="chevronUp" onClick={() => moveRow(row, 'up')} disabled={!canMoveUp}>{''}</Btn>
              <Btn size="sm" variant="ghost" icon="chevronDown" onClick={() => moveRow(row, 'down')} disabled={!canMoveDown}>{''}</Btn>
            </>
          )}
          {isPending && <Btn size="sm" variant="secondary" onClick={() => cancelPending(row)}>{t ? '取消' : 'Cancel'}</Btn>}
          {isRunning && <Btn size="sm" variant="danger" onClick={() => openForceCancel(row)}>{t ? '強制取消' : 'Force Cancel'}</Btn>}
          {isFailed && !ignored && (
            <>
              <Btn size="sm" variant="primary" onClick={() => retryRow(row)}>{t ? '重試' : 'Retry'}</Btn>
              <Btn size="sm" variant="ghost" onClick={() => ignoreRow(row)}>{t ? '忽略' : 'Ignore'}</Btn>
            </>
          )}
          {ignored && <Btn size="sm" variant="ghost" onClick={() => unignoreRow(row)}>{t ? '取消忽略' : 'Unignore'}</Btn>}
        </div>
      </div>
    );
  };

  const Section = ({ title, rows, status }) => (
    <div style={{ marginBottom: 24 }}>
      <div style={{ color: TOKEN.textSecondary, fontSize: 13, fontWeight: 600, marginBottom: 10, display: 'flex', alignItems: 'center', gap: 8 }}>
        <span>{title}</span>
        <span style={{ color: TOKEN.textMuted, fontWeight: 400 }}>({rows.length})</span>
      </div>
      {rows.length === 0 ? (
        <div style={{ color: TOKEN.textMuted, fontSize: 13, padding: '14px 16px', background: TOKEN.surface, border: `1px dashed ${TOKEN.surfaceBorder}`, borderRadius: 8 }}>
          {t ? '空' : 'Empty'}
        </div>
      ) : (
        <div
          onDragOver={status === 'pending' && !isMobile ? onDragOverPending : undefined}
          style={{ display: 'flex', flexDirection: 'column', gap: 8, pointerEvents: (status === 'pending' && dragInFlight) ? 'none' : 'auto' }}
        >
          {rows.map((r, i) => (
            <Row
              key={r.id}
              row={r}
              status={status}
              canMoveUp={status === 'pending' && i > 0 && !dragInFlight}
              canMoveDown={status === 'pending' && i < rows.length - 1 && !dragInFlight}
            />
          ))}
        </div>
      )}
    </div>
  );

  return (
    <div>
      {/* Processing progress overview — three progress bars + 24h delta */}
      <ProcessingOverview lang={lang} />

      {/* Header: max_concurrent input */}
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 16, marginBottom: 24, padding: '16px 18px', background: TOKEN.surface, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 10 }}>
        <div>
          <label style={{ display: 'block', color: TOKEN.textMuted, fontSize: 12, marginBottom: 6 }}>
            {t ? '並行上限' : 'Max Concurrent'}
          </label>
          <input
            type="number"
            min={1}
            max={3}
            value={maxLocal}
            onChange={onMaxChange}
            style={{ width: 80, background: TOKEN.surfaceRaised, border: `1px solid ${showMaxWarning ? '#f59e0b' : TOKEN.surfaceBorder}`, borderRadius: 8, padding: '8px 10px', color: TOKEN.text, fontSize: 14, outline: 'none', fontFamily: 'inherit' }}
          />
          {showMaxWarning && (
            <div style={{ color: '#f59e0b', fontSize: 11, marginTop: 4 }}>
              {t ? '上限 3，受 worker concurrency 限制' : 'Max 3, limited by worker concurrency'}
            </div>
          )}
          {maxError && (
            <div style={{ color: '#f87171', fontSize: 11, marginTop: 4 }}>{maxError}</div>
          )}
        </div>
        <div style={{ flex: 1, color: TOKEN.textSecondary, fontSize: 12, paddingBottom: 4 }}>
          {t ? `目前生效值：${settings.max_concurrent_transcriptions}` : `Currently in effect: ${settings.max_concurrent_transcriptions}`}
          {dragInFlight && <span style={{ marginLeft: 12, color: TOKEN.textMuted }}>{t ? '排序處理中…' : 'Reordering…'}</span>}
        </div>
        <Btn variant="secondary" size="sm" icon="refresh" onClick={runBackfill} disabled={backfillBusy}>
          {backfillBusy ? (t ? '排入中…' : 'Queueing…') : (t ? '批次補摘要' : 'Backfill Summaries')}
        </Btn>
      </div>

      {(() => {
        const eligible = (queue.completed || []).filter(r => r.ai_summary_status === 'pending' || r.ai_summary_status === 'failed').length;
        if (eligible === 0) return null;
        return (
          <div style={{ color: TOKEN.textMuted, fontSize: 12, marginBottom: 12, padding: '8px 12px', background: TOKEN.surface, border: `1px dashed ${TOKEN.surfaceBorder}`, borderRadius: 6 }}>
            {t ? `有 ${eligible} 集待生成摘要，可點上方「批次補摘要」` : `${eligible} episodes awaiting summary — use Backfill Summaries above`}
          </div>
        );
      })()}

      {toast && (
        <div style={{ position: 'fixed', bottom: 24, right: 24, background: TOKEN.surfaceRaised, border: `1px solid ${TOKEN.accent}55`, borderRadius: 8, padding: '10px 16px', color: TOKEN.text, fontSize: 13, zIndex: 1000, boxShadow: '0 4px 12px rgba(0,0,0,0.4)' }}>
          {toast}
        </div>
      )}

      {error && (
        <div style={{ background: 'rgba(239,68,68,0.12)', border: '1px solid rgba(239,68,68,0.3)', borderRadius: 8, padding: '9px 13px', color: '#f87171', fontSize: 13, marginBottom: 16 }}>
          {error}
        </div>
      )}

      {/* Sub-tab switcher */}
      {(() => {
        const counts = {
          active: (queue.pending?.length || 0) + (queue.running?.length || 0),
          completed: queue.completed?.length || 0,
          closed: (queue.failed?.length || 0) + (queue.cancelled?.length || 0),
        };
        const tabs = [
          { key: 'active', label: t ? '進行中' : 'Active' },
          { key: 'completed', label: t ? '已完成' : 'Completed' },
          { key: 'closed', label: t ? '已結束' : 'Closed' },
        ];
        return (
          <div style={{ display: 'flex', gap: 4, borderBottom: `1px solid ${TOKEN.surfaceBorder}`, marginBottom: 20 }}>
            {tabs.map(tab => {
              const selected = activeTab === tab.key;
              return (
                <button
                  key={tab.key}
                  onClick={() => setActiveTab(tab.key)}
                  style={{
                    background: 'transparent',
                    border: 'none',
                    borderBottom: `2px solid ${selected ? TOKEN.accent : 'transparent'}`,
                    color: selected ? TOKEN.text : TOKEN.textSecondary,
                    fontSize: 14,
                    fontWeight: selected ? 600 : 500,
                    padding: '10px 16px',
                    cursor: 'pointer',
                    fontFamily: 'inherit',
                    marginBottom: -1,
                  }}
                >
                  {tab.label} ({counts[tab.key]})
                </button>
              );
            })}
          </div>
        );
      })()}

      {activeTab === 'active' && (
        (() => {
          const runningRows = queue.running || [];
          const pendingRows = pendingDisplay || [];
          const total = runningRows.length + pendingRows.length;
          if (total === 0) {
            return (
              <div style={{ color: TOKEN.textMuted, fontSize: 13, padding: '14px 16px', background: TOKEN.surface, border: `1px dashed ${TOKEN.surfaceBorder}`, borderRadius: 8 }}>
                {t ? '空' : 'Empty'}
              </div>
            );
          }
          return (
            <div
              onDragOver={!isMobile && pendingRows.length > 0 ? onDragOverPending : undefined}
              style={{ display: 'flex', flexDirection: 'column', gap: 8, pointerEvents: (dragInFlight) ? 'none' : 'auto' }}
            >
              {runningRows.map(r => (
                <Row key={r.id} row={r} status="running" />
              ))}
              {pendingRows.map((r, i) => (
                <Row
                  key={r.id}
                  row={r}
                  status="pending"
                  position={i + 1}
                  canMoveUp={i > 0 && !dragInFlight}
                  canMoveDown={i < pendingRows.length - 1 && !dragInFlight}
                />
              ))}
            </div>
          );
        })()
      )}
      {activeTab === 'completed' && (
        queue.completed.length === 0 ? (
          <div style={{ color: TOKEN.textMuted, fontSize: 13, padding: '14px 16px', background: TOKEN.surface, border: `1px dashed ${TOKEN.surfaceBorder}`, borderRadius: 8 }}>
            {t ? '空' : 'Empty'}
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {queue.completed.map(r => <Row key={r.id} row={r} status="completed" />)}
          </div>
        )
      )}
      {activeTab === 'closed' && (
        <>
          <Section title={t ? '失敗' : 'Failed'} rows={queue.failed} status="failed" />
          <Section title={t ? '已取消' : 'Cancelled'} rows={queue.cancelled} status="cancelled" />
        </>
      )}

      <ConfirmModal
        open={confirmOpen}
        title={t ? '確認強制取消' : 'Confirm Force Cancel'}
        message={t
          ? '確定要強制取消正在執行的轉錄嗎？此動作會中止 Whisper 呼叫且不可復原'
          : 'Confirm force-cancel? This will abort the running Whisper call and cannot be undone.'}
        confirmLabel={confirmLoading ? (t ? '處理中…' : 'Processing…') : (t ? '確認' : 'Confirm')}
        cancelLabel={t ? '取消' : 'Cancel'}
        danger
        loading={confirmLoading}
        onConfirm={confirmForceCancel}
        onCancel={closeConfirm}
      />
    </div>
  );
};

Object.assign(window, { QueueTab });
