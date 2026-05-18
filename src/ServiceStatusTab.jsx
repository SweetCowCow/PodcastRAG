// ServiceStatusTab — admin tab for circuit breaker state per provider.
//
// Part of task-failure-monitoring-and-circuit-breaker. Wired into
// AdminPage.jsx at page route `admin-service-status`. Polls
// `/admin/service-status` every 15 s. Renders one row per provider with
// state badge, paused task count, last probe info, and a [⏵ 手動恢復]
// button (enabled only when state='open').
//
// Times come from backend as ISO 8601 UTC; we format them as
// Asia/Taipei locale strings in the table for operator readability
// (per workspace convention: 用台北時間).

const _serviceLabels = {
  openai: 'OpenAI (Direct)',
  aihub: 'Zeabur AI Hub',
  zsend: 'ZSend (Email)',
};

const _fmtTaipei = (iso) => {
  if (!iso) return '—';
  try {
    return new Intl.DateTimeFormat('zh-TW', {
      timeZone: 'Asia/Taipei',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    }).format(new Date(iso));
  } catch (_) {
    return iso;
  }
};

const ServiceStatusTab = ({ lang }) => {
  const t = lang === 'zh';
  const [rows, setRows] = React.useState(null);
  const [error, setError] = React.useState(null);
  const [confirming, setConfirming] = React.useState(null); // provider_id
  const [busy, setBusy] = React.useState(false);
  const [toast, setToast] = React.useState(null);

  const reload = React.useCallback(async () => {
    setError(null);
    try {
      const res = await apiFetch('/admin/service-status');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setRows(Array.isArray(data) ? data : []);
    } catch (err) {
      setError(err.message || String(err));
    }
  }, []);

  React.useEffect(() => {
    reload();
    const id = setInterval(reload, 15_000);
    return () => clearInterval(id);
  }, [reload]);

  const doResume = async (providerId) => {
    setBusy(true);
    try {
      const res = await apiFetch(`/admin/service-status/${providerId}/resume`, {
        method: 'POST',
        body: JSON.stringify({}),
      });
      if (res.status === 200) {
        setToast({
          variant: 'success',
          text: (t ? '已手動恢復：' : 'Resumed: ') + providerId,
        });
        await reload();
      } else if (res.status === 409) {
        setToast({
          variant: 'warning',
          text: t ? '服務已是正常狀態' : 'Service is already healthy',
        });
        await reload();
      } else {
        const detail = await res.text().catch(() => '');
        setToast({
          variant: 'danger',
          text: `HTTP ${res.status} ${detail.slice(0, 200)}`,
        });
      }
    } catch (err) {
      setToast({ variant: 'danger', text: err.message || String(err) });
    } finally {
      setBusy(false);
      setConfirming(null);
      setTimeout(() => setToast(null), 4000);
    }
  };

  return (
    <div style={{ maxWidth: 980 }}>
      <p style={{ margin: '0 0 16px', color: TOKEN.textSecondary, fontSize: 14 }}>
        {t
          ? '各外部供應商的 circuit breaker 狀態。state=open 時，所有相關 task 會自動暫停（自我 retry 5 分鐘後再試），系統每 30 分鐘自動探測一次；亦可在此手動恢復。'
          : "External provider circuit breaker states. When state=open, related tasks auto-pause (self-retry every 5 min) and the system probes every 30 min; you can also resume manually here."}
      </p>

      {error && (
        <div style={{ marginBottom: 16, padding: 12, background: 'rgba(239,68,68,0.12)', border: '1px solid rgba(239,68,68,0.3)', borderRadius: 8, color: '#f87171', fontSize: 13 }}>
          {(t ? '載入失敗：' : 'Failed to load: ') + error}
        </div>
      )}

      <div style={{ background: TOKEN.surface, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 12, overflow: 'hidden' }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1.4fr 0.8fr 1.3fr 0.8fr 1.4fr 1fr', padding: '12px 18px', borderBottom: `1px solid ${TOKEN.surfaceBorder}`, color: TOKEN.textMuted, fontSize: 12, fontWeight: 600, letterSpacing: '0.05em', textTransform: 'uppercase' }}>
          <div>{t ? '供應商' : 'Provider'}</div>
          <div>{t ? '狀態' : 'State'}</div>
          <div>{t ? '暫停起時' : 'Opened at'}</div>
          <div style={{ textAlign: 'right' }}>{t ? '影響 task 數' : 'Paused'}</div>
          <div>{t ? '最後探測' : 'Last probe'}</div>
          <div style={{ textAlign: 'right' }}>{t ? '操作' : 'Action'}</div>
        </div>
        {(rows || []).map((r) => {
          const isOpen = r.state === 'open';
          return (
            <div key={r.provider_id}
              style={{ display: 'grid', gridTemplateColumns: '1.4fr 0.8fr 1.3fr 0.8fr 1.4fr 1fr', padding: '14px 18px', borderTop: `1px solid ${TOKEN.surfaceBorder}`, alignItems: 'center', fontSize: 14, color: TOKEN.text }}>
              <div style={{ fontWeight: 600 }}>
                {_serviceLabels[r.provider_id] || r.provider_id}
              </div>
              <div>
                <Badge variant={isOpen ? 'danger' : 'success'}>
                  {isOpen ? 'open' : 'closed'}
                </Badge>
              </div>
              <div style={{ color: isOpen ? TOKEN.text : TOKEN.textMuted, fontSize: 13 }}>
                {isOpen ? _fmtTaipei(r.opened_at) : '—'}
              </div>
              <div style={{ textAlign: 'right', color: TOKEN.text, fontVariantNumeric: 'tabular-nums' }}>
                {r.paused_task_count || 0}
              </div>
              <div style={{ color: TOKEN.textSecondary, fontSize: 12 }}>
                {r.last_probe_at ? (
                  <span>
                    {_fmtTaipei(r.last_probe_at)}{' '}
                    <span style={{ color: r.last_probe_result === 'success' ? '#4ade80' : '#f87171' }}>
                      ({r.last_probe_result})
                    </span>
                  </span>
                ) : '—'}
              </div>
              <div style={{ textAlign: 'right' }}>
                <Btn
                  size="sm"
                  variant={isOpen ? 'primary' : 'ghost'}
                  disabled={!isOpen || busy}
                  onClick={() => setConfirming(r.provider_id)}
                >
                  {t ? '⏵ 手動恢復' : 'Resume'}
                </Btn>
              </div>
            </div>
          );
        })}
        {rows && rows.length === 0 && (
          <div style={{ padding: 24, color: TOKEN.textMuted, textAlign: 'center' }}>
            {t ? '無資料' : 'No data'}
          </div>
        )}
      </div>

      {confirming && (
        <ConfirmModal
          open={true}
          title={t ? '手動恢復服務' : 'Manual resume'}
          message={t
            ? `確定要手動恢復 ${confirming} 服務嗎？影響 ${(rows || []).find(r => r.provider_id === confirming)?.paused_task_count || 0} 個任務會重新加入 queue。`
            : `Resume ${confirming}? ${(rows || []).find(r => r.provider_id === confirming)?.paused_task_count || 0} paused task(s) will return to queue.`}
          confirmLabel={t ? '確定恢復' : 'Confirm'}
          cancelLabel={t ? '取消' : 'Cancel'}
          loading={busy}
          onConfirm={() => doResume(confirming)}
          onCancel={() => setConfirming(null)}
        />
      )}

      {toast && (
        <div style={{ position: 'fixed', bottom: 24, right: 24, padding: '12px 18px', borderRadius: 8, background: TOKEN.surfaceRaised, border: `1px solid ${TOKEN.surfaceBorder}`, color: toast.variant === 'danger' ? '#f87171' : toast.variant === 'warning' ? '#fbbf24' : '#4ade80', fontSize: 13, boxShadow: '0 10px 30px rgba(0,0,0,0.4)', zIndex: 1100 }}>
          {toast.text}
        </div>
      )}
    </div>
  );
};

Object.assign(window, { ServiceStatusTab });
