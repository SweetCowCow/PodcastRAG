// Admin Quota Requests tab — list + approve/reject pending quota requests.
const QuotaRequestsTab = ({ lang }) => {
  const t = lang === 'zh';
  const [filter, setFilter] = React.useState('pending');
  const [rows, setRows] = React.useState(null);
  const [error, setError] = React.useState(null);
  const [actionError, setActionError] = React.useState({});  // {id: msg}
  const [toast, setToast] = React.useState(null);
  const [amounts, setAmounts] = React.useState({});  // {id: number}
  const [rejecting, setRejecting] = React.useState(null);  // {id, note}
  const [busy, setBusy] = React.useState({});  // {id: bool}

  const showToast = (msg) => {
    setToast(msg);
    setTimeout(() => setToast(null), 3000);
  };

  const fetchRows = React.useCallback(async () => {
    setError(null);
    try {
      const res = await apiFetch(`/admin/quota-requests?status=${filter}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setRows(data);
    } catch (err) {
      setError(err.message || String(err));
    }
  }, [filter]);

  React.useEffect(() => { fetchRows(); }, [fetchRows]);

  const formatRel = (iso) => {
    try {
      const d = new Date(iso);
      const diffMs = Date.now() - d.getTime();
      const h = Math.floor(diffMs / 3_600_000);
      if (h < 1) return t ? '不到 1 小時前' : '<1h ago';
      if (h < 24) return t ? `${h} 小時前` : `${h}h ago`;
      const days = Math.floor(h / 24);
      return t ? `${days} 天前` : `${days}d ago`;
    } catch {
      return iso;
    }
  };

  const handleApprove = async (id) => {
    if (busy[id]) return;
    const amount = parseInt(amounts[id] ?? '30', 10);
    if (!Number.isFinite(amount) || amount < 1) {
      setActionError(prev => ({ ...prev, [id]: t ? '金額必須 ≥ 1' : 'Amount must be ≥ 1' }));
      return;
    }
    setBusy(prev => ({ ...prev, [id]: true }));
    setActionError(prev => ({ ...prev, [id]: null }));
    try {
      const res = await apiFetch(`/admin/quota-requests/${id}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ amount }),
      });
      if (res.status === 409) {
        showToast(t ? '此申請已被處理' : 'This request has been processed');
        await fetchRows();
        return;
      }
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail?.detail || `HTTP ${res.status}`);
      }
      showToast(t ? `已核准 +${amount}` : `Approved +${amount}`);
      await fetchRows();
    } catch (err) {
      setActionError(prev => ({ ...prev, [id]: err.message || String(err) }));
    } finally {
      setBusy(prev => ({ ...prev, [id]: false }));
    }
  };

  const handleReject = async () => {
    if (!rejecting || !rejecting.id) return;
    const id = rejecting.id;
    const note = (rejecting.note || '').trim();
    if (note.length < 1) {
      setActionError(prev => ({ ...prev, [id]: t ? '請填寫拒絕理由' : 'Reason required' }));
      return;
    }
    setBusy(prev => ({ ...prev, [id]: true }));
    try {
      const res = await apiFetch(`/admin/quota-requests/${id}/reject`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ note }),
      });
      if (res.status === 409) {
        showToast(t ? '此申請已被處理' : 'This request has been processed');
      } else if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail?.detail || `HTTP ${res.status}`);
      } else {
        showToast(t ? '已拒絕' : 'Rejected');
      }
      setRejecting(null);
      await fetchRows();
    } catch (err) {
      setActionError(prev => ({ ...prev, [id]: err.message || String(err) }));
    } finally {
      setBusy(prev => ({ ...prev, [id]: false }));
    }
  };

  const filters = [
    { id: 'pending', label: t ? '待處理' : 'Pending' },
    { id: 'approved', label: t ? '已核准' : 'Approved' },
    { id: 'rejected', label: t ? '已拒絕' : 'Rejected' },
  ];

  return (
    <div>
      {/* Filter chips */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
        {filters.map(f => (
          <button key={f.id} onClick={() => setFilter(f.id)}
            style={{
              padding: '6px 14px',
              borderRadius: 99,
              border: `1px solid ${filter === f.id ? TOKEN.accent : TOKEN.surfaceBorder}`,
              background: filter === f.id ? TOKEN.accent + '22' : TOKEN.surfaceRaised,
              color: filter === f.id ? TOKEN.accent : TOKEN.textSecondary,
              fontSize: 13,
              cursor: 'pointer',
              fontFamily: 'inherit',
            }}>
            {f.label}
          </button>
        ))}
      </div>

      {error && (
        <div style={{ color: TOKEN.danger || '#ef4444', padding: 12, marginBottom: 16, background: TOKEN.surface, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 8 }}>
          {error}
        </div>
      )}

      {!rows && !error && (
        <p style={{ color: TOKEN.textMuted, textAlign: 'center', padding: 40 }}>{t ? '載入中…' : 'Loading…'}</p>
      )}

      {rows && rows.length === 0 && (
        <p style={{ color: TOKEN.textMuted, textAlign: 'center', padding: 40, fontSize: 14 }}>
          {filter === 'pending'
            ? (t ? '目前沒有 pending 的 quota 申請' : 'No pending quota requests')
            : (t ? `沒有 ${filter} 的申請` : `No ${filter} requests`)}
        </p>
      )}

      {rows && rows.length > 0 && (
        <div style={{ background: TOKEN.surface, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 8, overflow: 'hidden' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ background: TOKEN.surfaceRaised, color: TOKEN.textSecondary, textAlign: 'left' }}>
                <th style={{ padding: '10px 12px' }}>{t ? '使用者' : 'User'}</th>
                <th style={{ padding: '10px 12px' }}>{t ? '理由' : 'Reason'}</th>
                <th style={{ padding: '10px 12px' }}>{t ? '送出時間' : 'Submitted'}</th>
                <th style={{ padding: '10px 12px' }}>{t ? '剩餘額度' : 'Remaining'}</th>
                <th style={{ padding: '10px 12px' }}>{t ? '操作' : 'Actions'}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(r => {
                const isPending = r.status === 'pending';
                const reasonShort = (r.reason || '').length > 100
                  ? r.reason.slice(0, 100) + '…'
                  : r.reason;
                return (
                  <tr key={r.id} style={{ borderTop: `1px solid ${TOKEN.surfaceBorder}` }}>
                    <td style={{ padding: '10px 12px', color: TOKEN.text }}>{r.user_email}</td>
                    <td style={{ padding: '10px 12px', color: TOKEN.textSecondary, maxWidth: 320 }} title={r.reason}>
                      {reasonShort}
                    </td>
                    <td style={{ padding: '10px 12px', color: TOKEN.textMuted, whiteSpace: 'nowrap' }}>
                      {formatRel(r.requested_at)}
                    </td>
                    <td style={{ padding: '10px 12px', color: TOKEN.text, fontVariantNumeric: 'tabular-nums' }}>
                      {r.user_quota_remaining}
                    </td>
                    <td style={{ padding: '10px 12px' }}>
                      {isPending ? (
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                          <input type="number" min={1} max={1000}
                            value={amounts[r.id] ?? 30}
                            onChange={(e) => setAmounts(prev => ({ ...prev, [r.id]: e.target.value }))}
                            style={{
                              width: 70,
                              padding: '4px 8px',
                              borderRadius: 6,
                              border: `1px solid ${TOKEN.surfaceBorder}`,
                              background: TOKEN.surfaceRaised,
                              color: TOKEN.text,
                              fontSize: 13,
                            }} />
                          <Btn size="sm" variant="primary" onClick={() => handleApprove(r.id)} disabled={busy[r.id]}>
                            {t ? `核准 +${amounts[r.id] ?? 30}` : `Approve +${amounts[r.id] ?? 30}`}
                          </Btn>
                          <Btn size="sm" variant="ghost" onClick={() => setRejecting({ id: r.id, note: '' })} disabled={busy[r.id]}>
                            {t ? '拒絕' : 'Reject'}
                          </Btn>
                        </div>
                      ) : r.status === 'approved' ? (
                        <span style={{ color: '#22c55e' }}>+{r.granted_amount}</span>
                      ) : (
                        <span style={{ color: TOKEN.textMuted }} title={r.rejection_note || ''}>
                          {t ? '已拒絕' : 'Rejected'}
                        </span>
                      )}
                      {actionError[r.id] && (
                        <div style={{ color: TOKEN.danger || '#ef4444', fontSize: 12, marginTop: 6 }}>
                          {actionError[r.id]}
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Reject confirmation modal */}
      {rejecting && (
        <div onClick={() => setRejecting(null)}
          style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', zIndex: 100, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}>
          <div onClick={(e) => e.stopPropagation()}
            style={{ background: TOKEN.surface, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 12, padding: 24, maxWidth: 440, width: '100%' }}>
            <h3 style={{ margin: '0 0 12px', color: TOKEN.text, fontSize: 16, fontWeight: 700 }}>
              {t ? '拒絕 Quota 申請' : 'Reject quota request'}
            </h3>
            <p style={{ margin: '0 0 12px', color: TOKEN.textSecondary, fontSize: 13 }}>
              {t ? '拒絕原因（會寄給使用者—未來功能）' : 'Rejection reason (will be sent to user — future)'}
            </p>
            <textarea rows={4} value={rejecting.note}
              onChange={(e) => setRejecting(prev => ({ ...prev, note: e.target.value }))}
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
                marginBottom: 16,
              }} />
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
              <Btn variant="ghost" onClick={() => setRejecting(null)}>{t ? '取消' : 'Cancel'}</Btn>
              <Btn variant="danger" onClick={handleReject} disabled={busy[rejecting.id]}>
                {t ? '確定拒絕' : 'Confirm reject'}
              </Btn>
            </div>
          </div>
        </div>
      )}

      {toast && (
        <div style={{ position: 'fixed', bottom: 24, right: 24, padding: '10px 16px', background: TOKEN.surface, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 8, color: TOKEN.text, boxShadow: '0 4px 16px rgba(0,0,0,0.3)', zIndex: 200 }}>
          {toast}
        </div>
      )}
    </div>
  );
};

Object.assign(window, { QuotaRequestsTab });
