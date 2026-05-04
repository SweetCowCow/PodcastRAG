// QuotaApplyModal — opens from QueryPage's "申請更多額度" button. On open it
// checks /quota-requests/me?status=pending; if a row exists the modal renders
// a "you already have a pending request" state with no textarea. Otherwise
// renders a textarea and POSTs to /quota-requests on submit.
const QUOTA_APPLY_MIN = 10;
const QUOTA_APPLY_MAX = 1000;

const QuotaApplyModal = ({ open, lang, onClose }) => {
  const t = lang === 'zh';
  const [reason, setReason] = React.useState('');
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState(null);
  const [pendingRow, setPendingRow] = React.useState(null);
  const [loadingPending, setLoadingPending] = React.useState(false);
  const [success, setSuccess] = React.useState(false);

  // Reset state on each open
  React.useEffect(() => {
    if (!open) return;
    setReason('');
    setError(null);
    setSuccess(false);
    setPendingRow(null);
    setLoadingPending(true);
    let cancelled = false;
    (async () => {
      try {
        const res = await apiFetch('/quota-requests/me?status=pending');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const rows = await res.json();
        if (!cancelled) setPendingRow(rows.length > 0 ? rows[0] : null);
      } catch (err) {
        if (!cancelled) setError(err.message || String(err));
      } finally {
        if (!cancelled) setLoadingPending(false);
      }
    })();
    return () => { cancelled = true; };
  }, [open]);

  if (!open) return null;

  const handleSubmit = async () => {
    if (submitting) return;
    const trimmed = reason.trim();
    if (trimmed.length < QUOTA_APPLY_MIN) {
      setError(t ? `理由至少 ${QUOTA_APPLY_MIN} 字元` : `Reason must be at least ${QUOTA_APPLY_MIN} characters`);
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const res = await apiFetch('/quota-requests', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: trimmed }),
      });
      if (res.status === 201) {
        setSuccess(true);
        setTimeout(() => { onClose && onClose(); }, 2000);
        return;
      }
      const body = await res.json().catch(() => null);
      const code = body?.detail?.error_code || body?.error_code;
      if (res.status === 409 && code === 'quota_request_pending') {
        // Re-fetch the pending row to render blocked state
        const me = await apiFetch('/quota-requests/me?status=pending');
        if (me.ok) {
          const rows = await me.json();
          setPendingRow(rows[0] || null);
        }
        return;
      }
      const detailText = body?.detail?.detail || body?.detail || `HTTP ${res.status}`;
      setError(typeof detailText === 'string' ? detailText : JSON.stringify(detailText));
    } catch (err) {
      setError(err.message || String(err));
    } finally {
      setSubmitting(false);
    }
  };

  const formatDate = (iso) => {
    if (!iso) return '';
    try {
      return new Date(iso).toLocaleString();
    } catch {
      return iso;
    }
  };

  return (
    <div onClick={submitting ? undefined : onClose}
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', zIndex: 100, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}>
      <div onClick={(e) => e.stopPropagation()}
        style={{ background: TOKEN.surface, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 12, padding: 24, maxWidth: 480, width: '100%' }}>
        <h3 style={{ margin: '0 0 16px', color: TOKEN.text, fontSize: 18, fontWeight: 700 }}>
          {t ? '申請更多額度' : 'Request more quota'}
        </h3>

        {loadingPending && (
          <p style={{ color: TOKEN.textMuted, fontSize: 14 }}>{t ? '載入中…' : 'Loading…'}</p>
        )}

        {!loadingPending && pendingRow && (
          <div>
            <p style={{ color: TOKEN.textSecondary, fontSize: 14, lineHeight: 1.6, margin: '0 0 16px' }}>
              {t
                ? `您已有一筆審核中的申請（送出於 ${formatDate(pendingRow.requested_at)}）。`
                : `You already have a pending request (submitted ${formatDate(pendingRow.requested_at)}).`}
            </p>
            <p style={{ color: TOKEN.textMuted, fontSize: 13, margin: '0 0 20px' }}>
              {t ? '請耐心等候管理員處理。' : 'Please wait while an admin reviews it.'}
            </p>
            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <Btn variant="primary" onClick={onClose}>{t ? '關閉' : 'Close'}</Btn>
            </div>
          </div>
        )}

        {!loadingPending && !pendingRow && success && (
          <p style={{ color: '#22c55e', fontSize: 14, margin: 0 }}>
            {t ? '已送出，admin 收到通知後會處理' : 'Submitted — admin will be notified.'}
          </p>
        )}

        {!loadingPending && !pendingRow && !success && (
          <>
            <p style={{ color: TOKEN.textSecondary, fontSize: 13, margin: '0 0 12px', lineHeight: 1.5 }}>
              {t ? '請告訴我們你的用途' : "Tell us how you'll use it"}
            </p>
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              maxLength={QUOTA_APPLY_MAX}
              rows={5}
              placeholder={t ? '例如：在做研究、想多用 AI 整理整集內容…' : "e.g. doing research, want to summarize multiple episodes…"}
              style={{
                width: '100%',
                padding: 10,
                fontSize: 14,
                fontFamily: 'inherit',
                borderRadius: 8,
                border: `1px solid ${TOKEN.surfaceBorder}`,
                background: TOKEN.surfaceRaised,
                color: TOKEN.text,
                resize: 'vertical',
                marginBottom: 8,
              }}
            />
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: TOKEN.textMuted, marginBottom: 16 }}>
              <span>{reason.length} / {QUOTA_APPLY_MAX}</span>
              {reason.length > 0 && reason.length < QUOTA_APPLY_MIN && (
                <span style={{ color: '#f59e0b' }}>
                  {t ? `至少 ${QUOTA_APPLY_MIN} 字元` : `Min ${QUOTA_APPLY_MIN} chars`}
                </span>
              )}
            </div>
            {error && (
              <p style={{ color: TOKEN.danger || '#ef4444', fontSize: 13, margin: '0 0 12px' }}>{error}</p>
            )}
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
              <Btn variant="ghost" onClick={onClose} disabled={submitting}>
                {t ? '取消' : 'Cancel'}
              </Btn>
              <Btn variant="primary" onClick={handleSubmit}
                disabled={submitting || reason.trim().length < QUOTA_APPLY_MIN}>
                {submitting ? (t ? '送出中…' : 'Submitting…') : (t ? '送出申請' : 'Submit request')}
              </Btn>
            </div>
          </>
        )}
      </div>
    </div>
  );
};

Object.assign(window, { QuotaApplyModal });
