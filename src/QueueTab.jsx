// Transcription Queue Tab — admin queue rows + max_concurrent input + drag reorder
const QueueTab = ({ lang }) => {
  const t = lang === 'zh';
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
          fetch(`${API_BASE}/admin/queue`),
          fetch(`${API_BASE}/admin/settings`),
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
      const qRes = await fetch(`${API_BASE}/admin/queue`);
      if (qRes.ok) setQueue(await qRes.json());
    } catch {}
  };

  const setActionErr = (id, msg) => setActionError(e => ({ ...e, [id]: msg }));
  const clearActionErr = (id) => setActionError(e => { const c = { ...e }; delete c[id]; return c; });

  // ── Cancel pending ──
  const cancelPending = async (row) => {
    clearActionErr(row.id);
    try {
      const res = await fetch(`${API_BASE}/admin/queue/${row.id}/cancel`, { method: 'POST' });
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
      const res = await fetch(`${API_BASE}/admin/queue/${confirmTarget.id}/cancel?force=true`, { method: 'POST' });
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
      const res = await fetch(`${API_BASE}/episodes/${row.episode_id}/transcribe`, { method: 'POST' });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setActionErr(row.id, body.detail || `HTTP ${res.status}`);
      }
    } catch (e) { setActionErr(row.id, e.message || String(e)); }
  };
  const ignoreRow = async (row) => {
    clearActionErr(row.id);
    try {
      const res = await fetch(`${API_BASE}/admin/queue/${row.id}/ignore`, { method: 'POST' });
      if (!res.ok) setActionErr(row.id, `HTTP ${res.status}`);
    } catch (e) { setActionErr(row.id, e.message || String(e)); }
  };
  const unignoreRow = async (row) => {
    clearActionErr(row.id);
    try {
      const res = await fetch(`${API_BASE}/admin/queue/${row.id}/unignore`, { method: 'POST' });
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
        const res = await fetch(`${API_BASE}/admin/settings`, {
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
      const res = await fetch(`${API_BASE}/admin/queue/${sourceId}/position`, {
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

  const Row = ({ row, status }) => {
    const isPending = status === 'pending';
    const isRunning = status === 'running';
    const isFailed = status === 'failed';
    const ignored = row.ignored;
    const dragging = draggingId === row.id;
    const errMsg = actionError[row.id];
    return (
      <div
        draggable={isPending && !dragInFlight}
        onDragStart={isPending ? (e) => onDragStart(e, row) : undefined}
        onDragEnd={isPending ? onDragEnd : undefined}
        onDragOver={isPending ? onDragOverPending : undefined}
        onDrop={isPending ? (e) => onDropPending(e, row) : undefined}
        style={{
          background: ignored ? TOKEN.bg : TOKEN.surface,
          border: `1px solid ${TOKEN.surfaceBorder}`,
          borderRadius: 8,
          padding: '12px 14px',
          display: 'flex',
          gap: 12,
          alignItems: 'flex-start',
          opacity: ignored ? 0.55 : (dragging ? 0.4 : 1),
          cursor: isPending ? (dragInFlight ? 'wait' : 'grab') : 'default',
          transition: 'opacity 0.15s',
        }}
      >
        {isPending && (
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
        <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
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
          onDragOver={status === 'pending' ? onDragOverPending : undefined}
          style={{ display: 'flex', flexDirection: 'column', gap: 8, pointerEvents: (status === 'pending' && dragInFlight) ? 'none' : 'auto' }}
        >
          {rows.map(r => <Row key={r.id} row={r} status={status} />)}
        </div>
      )}
    </div>
  );

  return (
    <div>
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
      </div>

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
        <>
          <Section title={t ? '排隊中（可拖動排序）' : 'Pending (drag to reorder)'} rows={pendingDisplay} status="pending" />
          <Section title={t ? '執行中' : 'Running'} rows={queue.running} status="running" />
        </>
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
