// AppealModal — opened from the disabled-state Lock card. Read-only email
// (from the OAuth callback redirect query) + reason textarea (maxLength 2000)
// + Submit/Cancel buttons. POSTs to /auth/appeal. Three terminal states:
//   200 → success confirmation, hides Submit
//   400 invalid_reason → inline error
//   429 rate_limited → "今天的申訴次數已達上限，請明天再試"
const APPEAL_REASON_MAX = 2000;

const AppealModal = ({ open, lang, email, onClose }) => {
  const t = lang === 'zh';
  const [reason, setReason] = React.useState('');
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState(null);
  const [success, setSuccess] = React.useState(false);
  const [rateLimited, setRateLimited] = React.useState(false);

  React.useEffect(() => {
    if (!open) return;
    setReason('');
    setError(null);
    setSuccess(false);
    setRateLimited(false);
    setSubmitting(false);
  }, [open]);

  if (!open) return null;

  const handleSubmit = async () => {
    if (submitting) return;
    const trimmed = reason.trim();
    if (trimmed.length < 1) {
      setError(t ? '請填寫申訴內容' : 'Please enter your appeal reason');
      return;
    }
    if (trimmed.length > APPEAL_REASON_MAX) {
      setError(t ? `內容不可超過 ${APPEAL_REASON_MAX} 字元` : `Reason must be ${APPEAL_REASON_MAX} chars or fewer`);
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      // Public unauthenticated endpoint — use raw fetch (apiFetch would inject
      // CSRF + cookies which we don't have because disabled users have no
      // session).
      const res = await fetch(`${API_BASE}/auth/appeal`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, reason: trimmed }),
      });
      if (res.status === 200) {
        setSuccess(true);
        return;
      }
      const body = await res.json().catch(() => null);
      const code = body?.detail?.error_code || body?.error_code;
      if (res.status === 429 || code === 'rate_limited') {
        setRateLimited(true);
        return;
      }
      if (res.status === 400 || code === 'invalid_reason') {
        setError(t ? '申訴內容格式不正確（不可空白，最多 2000 字）' : 'Invalid reason (must be non-empty, ≤2000 chars)');
        return;
      }
      setError(`HTTP ${res.status}`);
    } catch (err) {
      setError(err.message || String(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div onClick={submitting ? undefined : onClose}
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', zIndex: 100, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}>
      <div onClick={(e) => e.stopPropagation()}
        style={{ background: TOKEN.surface, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 12, padding: 24, maxWidth: 480, width: '100%' }}>
        <h3 style={{ margin: '0 0 16px', color: TOKEN.text, fontSize: 18, fontWeight: 700 }}>
          {t ? '提出申訴' : 'Submit Appeal'}
        </h3>

        {success ? (
          <>
            <p style={{ color: '#22c55e', fontSize: 14, lineHeight: 1.6, margin: '0 0 20px' }}>
              {t
                ? '已收到你的申訴，管理員會在 1-2 個工作天內回覆'
                : 'Your appeal has been received. An admin will reply within 1–2 business days.'}
            </p>
            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <Btn variant="primary" onClick={onClose}>{t ? '關閉' : 'Close'}</Btn>
            </div>
          </>
        ) : (
          <>
            <div style={{ marginBottom: 12 }}>
              <label style={{ display: 'block', color: TOKEN.textMuted, fontSize: 12, marginBottom: 4 }}>
                {t ? '帳號 Email' : 'Account email'}
              </label>
              <div style={{
                padding: '8px 10px',
                background: TOKEN.surfaceRaised,
                border: `1px solid ${TOKEN.surfaceBorder}`,
                borderRadius: 6,
                color: TOKEN.text,
                fontSize: 13,
              }}>
                {email || (t ? '（未提供）' : '(not provided)')}
              </div>
            </div>

            <label style={{ display: 'block', color: TOKEN.textMuted, fontSize: 12, marginBottom: 4 }}>
              {t ? '申訴內容' : 'Appeal reason'}
            </label>
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              maxLength={APPEAL_REASON_MAX}
              rows={6}
              placeholder={t ? '請簡述為什麼你認為這是誤判' : 'Briefly describe why you believe this is a mistake'}
              disabled={submitting}
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
              <span>{reason.length} / {APPEAL_REASON_MAX}</span>
            </div>

            {rateLimited && (
              <p style={{ color: TOKEN.warning, fontSize: 13, margin: '0 0 12px' }}>
                {t ? '今天的申訴次數已達上限，請明天再試' : 'Daily appeal limit reached — please try again tomorrow.'}
              </p>
            )}
            {error && !rateLimited && (
              <p style={{ color: TOKEN.danger || '#ef4444', fontSize: 13, margin: '0 0 12px' }}>{error}</p>
            )}

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
              <Btn variant="ghost" onClick={onClose} disabled={submitting}>
                {t ? '取消' : 'Cancel'}
              </Btn>
              <Btn variant="primary" onClick={handleSubmit}
                disabled={submitting || rateLimited || reason.trim().length < 1}>
                {submitting ? (t ? '送出中…' : 'Submitting…') : (t ? '送出申訴' : 'Submit Appeal')}
              </Btn>
            </div>
          </>
        )}
      </div>
    </div>
  );
};

Object.assign(window, { AppealModal });
