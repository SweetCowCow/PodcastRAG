// UserManagementTab — admin-only list + edit role/status/notes/quota for users.
const UserManagementTab = ({ lang, currentUser }) => {
  const t = lang === 'zh';
  const [users, setUsers] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState(null);
  const [editTarget, setEditTarget] = React.useState(null); // user obj for edit modal
  const [topupTarget, setTopupTarget] = React.useState(null);
  const [deleteTarget, setDeleteTarget] = React.useState(null);

  const load = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await apiFetch('/admin/users');
      if (!res.ok) {
        setError(`HTTP ${res.status}`);
        return;
      }
      setUsers(await res.json());
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => { load(); }, [load]);

  if (loading) return <p style={{ color: TOKEN.textMuted }}>{t ? '載入中…' : 'Loading…'}</p>;
  if (error) return <p style={{ color: TOKEN.danger }}>{error}</p>;

  return (
    <div>
      <div style={{ overflowX: 'auto', background: TOKEN.surface, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 12 }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13, color: TOKEN.text, minWidth: 1100 }}>
          <thead>
            <tr style={{ background: TOKEN.surfaceRaised, color: TOKEN.textSecondary, fontSize: 12, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              <th style={th}>{t ? '頭像' : 'Avatar'}</th>
              <th style={th}>{t ? '名稱' : 'Name'}</th>
              <th style={th}>Email</th>
              <th style={th}>{t ? '角色' : 'Role'}</th>
              <th style={th}>{t ? '狀態' : 'Status'}</th>
              <th style={th}>Provider</th>
              <th style={th}>{t ? '註冊日' : 'Created'}</th>
              <th style={th}>{t ? '上次登入' : 'Last login'}</th>
              <th style={th}>{t ? '累計查詢' : 'Total queries'}</th>
              <th style={th}>{t ? '剩餘額度' : 'Quota'}</th>
              <th style={th}>{t ? '備註' : 'Notes'}</th>
              <th style={th}>{t ? '操作' : 'Actions'}</th>
            </tr>
          </thead>
          <tbody>
            {users.map(u => (
              <tr key={u.id} style={{ borderTop: `1px solid ${TOKEN.surfaceBorder}` }}>
                <td style={td}>
                  {u.avatar_url
                    ? <img src={u.avatar_url} alt="" referrerPolicy="no-referrer" style={{ width: 28, height: 28, borderRadius: '50%' }} />
                    : <div style={{ width: 28, height: 28, borderRadius: '50%', background: TOKEN.accentDim, color: TOKEN.accent, display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 700 }}>{(u.name || u.email).slice(0,1).toUpperCase()}</div>}
                </td>
                <td style={td}>{u.name || '—'}</td>
                <td style={{ ...td, fontFamily: 'monospace', fontSize: 12 }}>{u.email}</td>
                <td style={td}><Badge variant={u.role === 'admin' ? 'default' : 'muted'}>{u.role}</Badge></td>
                <td style={td}><Badge variant={u.status === 'active' ? 'success' : u.status === 'pending' ? 'warning' : 'danger'}>{u.status}</Badge></td>
                <td style={td}>{u.provider}</td>
                <td style={td}>{formatDate(u.created_at, lang)}</td>
                <td style={td}>{u.last_login_at ? formatDate(u.last_login_at, lang) : '—'}</td>
                <td style={td}>{u.total_queries.toLocaleString()}</td>
                <td style={{ ...td, color: u.quota_remaining === 0 ? TOKEN.danger : TOKEN.text, fontWeight: 600 }}>{u.quota_remaining}</td>
                <td style={{ ...td, color: TOKEN.textMuted, maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={u.notes || ''}>{u.notes || '—'}</td>
                <td style={{ ...td, whiteSpace: 'nowrap' }}>
                  <Btn size="sm" variant="secondary" onClick={() => setEditTarget(u)}>{t ? '編輯' : 'Edit'}</Btn>
                  <span style={{ display: 'inline-block', width: 6 }} />
                  <Btn size="sm" variant="ghost" onClick={() => setTopupTarget(u)}>{t ? '加值' : 'Top up'}</Btn>
                  <span style={{ display: 'inline-block', width: 6 }} />
                  <Btn size="sm" variant="danger"
                    disabled={currentUser && currentUser.id === u.id}
                    onClick={() => setDeleteTarget(u)}
                    title={currentUser && currentUser.id === u.id ? (t ? '不能刪除自己' : 'Cannot delete your own account') : ''}>
                    {t ? '刪除' : 'Delete'}
                  </Btn>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {editTarget && (
        <EditUserModal lang={lang} user={editTarget}
          onClose={() => setEditTarget(null)}
          onSaved={() => { setEditTarget(null); load(); }} />
      )}
      {topupTarget && (
        <TopUpModal lang={lang} user={topupTarget}
          onClose={() => setTopupTarget(null)}
          onSaved={() => { setTopupTarget(null); load(); }} />
      )}
      {deleteTarget && (
        <DeleteUserModal lang={lang} user={deleteTarget}
          onClose={() => setDeleteTarget(null)}
          onDeleted={() => { setDeleteTarget(null); load(); }} />
      )}
    </div>
  );
};

const th = { padding: '10px 12px', textAlign: 'left', whiteSpace: 'nowrap' };
const td = { padding: '10px 12px', verticalAlign: 'middle' };

function formatDate(iso, lang) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${dd}`;
}

const EditUserModal = ({ lang, user, onClose, onSaved }) => {
  const t = lang === 'zh';
  const [role, setRole] = React.useState(user.role);
  const [status, setStatus] = React.useState(user.status);
  const [notes, setNotes] = React.useState(user.notes || '');
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState(null);

  const submit = async () => {
    const body = {};
    if (role !== user.role) body.role = role;
    if (status !== user.status) body.status = status;
    if ((notes || '') !== (user.notes || '')) body.notes = notes;
    if (Object.keys(body).length === 0) { onClose(); return; }
    setSaving(true);
    setError(null);
    try {
      const res = await apiFetch(`/admin/users/${user.id}`, {
        method: 'PATCH',
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const b = await res.json().catch(() => ({}));
        setError(b?.detail?.detail || `HTTP ${res.status}`);
        return;
      }
      onSaved();
    } finally {
      setSaving(false);
    }
  };

  return (
    <ModalShell title={t ? '編輯使用者' : 'Edit user'} onClose={onClose}>
      <Field label="Email"><div style={{ color: TOKEN.textMuted, fontFamily: 'monospace', fontSize: 13 }}>{user.email}</div></Field>
      <Field label={t ? '角色' : 'Role'}>
        <select value={role} onChange={e => setRole(e.target.value)} style={selectStyle}>
          <option value="member">member</option>
          <option value="admin">admin</option>
        </select>
      </Field>
      <Field label={t ? '狀態' : 'Status'}>
        <select value={status} onChange={e => setStatus(e.target.value)} style={selectStyle}>
          <option value="active">active</option>
          <option value="pending">pending</option>
          <option value="disabled">disabled</option>
        </select>
      </Field>
      <Field label={t ? '備註' : 'Notes'}>
        <textarea value={notes} onChange={e => setNotes(e.target.value)} maxLength={500}
          rows={3} style={{ ...selectStyle, resize: 'vertical', fontFamily: 'inherit' }} />
      </Field>
      {error && <div style={errorBox}>{error}</div>}
      <div style={modalActions}>
        <Btn variant="ghost" onClick={onClose}>{t ? '取消' : 'Cancel'}</Btn>
        <Btn onClick={submit} disabled={saving}>{saving ? (t ? '儲存中…' : 'Saving…') : (t ? '儲存' : 'Save')}</Btn>
      </div>
    </ModalShell>
  );
};

const TopUpModal = ({ lang, user, onClose, onSaved }) => {
  const t = lang === 'zh';
  const [delta, setDelta] = React.useState('100');
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState(null);

  const submit = async () => {
    const n = Number.parseInt(delta, 10);
    if (Number.isNaN(n)) { setError(t ? '請輸入整數' : 'Integer required'); return; }
    setSaving(true);
    setError(null);
    try {
      const res = await apiFetch(`/admin/users/${user.id}/quota`, {
        method: 'PATCH',
        body: JSON.stringify({ delta: n }),
      });
      if (!res.ok) {
        const b = await res.json().catch(() => ({}));
        setError(b?.detail?.detail || `HTTP ${res.status}`);
        return;
      }
      onSaved();
    } finally {
      setSaving(false);
    }
  };

  return (
    <ModalShell title={t ? '加值查詢額度' : 'Top up quota'} onClose={onClose}>
      <Field label="Email"><div style={{ color: TOKEN.textMuted, fontFamily: 'monospace', fontSize: 13 }}>{user.email}</div></Field>
      <Field label={t ? '目前剩餘' : 'Current remaining'}><div style={{ color: TOKEN.text, fontWeight: 700 }}>{user.quota_remaining}</div></Field>
      <Field label={t ? '加值（負值代表扣除）' : 'Delta (negative deducts)'}>
        <input type="number" value={delta} onChange={e => setDelta(e.target.value)} style={selectStyle} />
      </Field>
      {error && <div style={errorBox}>{error}</div>}
      <div style={modalActions}>
        <Btn variant="ghost" onClick={onClose}>{t ? '取消' : 'Cancel'}</Btn>
        <Btn onClick={submit} disabled={saving}>{saving ? (t ? '處理中…' : 'Saving…') : (t ? '套用' : 'Apply')}</Btn>
      </div>
    </ModalShell>
  );
};

const DeleteUserModal = ({ lang, user, onClose, onDeleted }) => {
  const t = lang === 'zh';
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState(null);
  const submit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const res = await apiFetch(`/admin/users/${user.id}`, { method: 'DELETE' });
      if (res.status !== 204 && !res.ok) {
        const b = await res.json().catch(() => ({}));
        setError(b?.detail?.detail || `HTTP ${res.status}`);
        return;
      }
      onDeleted();
    } finally {
      setSubmitting(false);
    }
  };
  return (
    <ModalShell title={t ? '刪除使用者' : 'Delete user'} onClose={onClose}>
      <p style={{ color: TOKEN.text, lineHeight: 1.6 }}>
        {t ? '確認刪除以下使用者？此動作無法復原。' : 'Confirm deleting this user? This cannot be undone.'}
      </p>
      <div style={{ background: TOKEN.surfaceRaised, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 8, padding: 12, marginTop: 12, fontFamily: 'monospace', fontSize: 13, color: TOKEN.text }}>
        {user.email}
      </div>
      {error && <div style={errorBox}>{error}</div>}
      <div style={modalActions}>
        <Btn variant="ghost" onClick={onClose}>{t ? '取消' : 'Cancel'}</Btn>
        <Btn variant="danger" onClick={submit} disabled={submitting}>{submitting ? (t ? '刪除中…' : 'Deleting…') : (t ? '確認刪除' : 'Delete')}</Btn>
      </div>
    </ModalShell>
  );
};

const ModalShell = ({ title, onClose, children }) => (
  <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 700, backdropFilter: 'blur(4px)' }}>
    <div style={{ background: TOKEN.surface, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 14, padding: 24, width: 440, maxWidth: '90vw', boxShadow: '0 20px 60px rgba(0,0,0,0.6)' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 18 }}>
        <h2 style={{ color: TOKEN.text, fontWeight: 700, fontSize: 16, margin: 0 }}>{title}</h2>
        <button onClick={onClose} style={{ background: 'transparent', border: 'none', color: TOKEN.textMuted, cursor: 'pointer', display: 'flex', alignItems: 'center' }}>
          <Icon name="x" size={18} />
        </button>
      </div>
      {children}
    </div>
  </div>
);

const Field = ({ label, children }) => (
  <div style={{ marginBottom: 14 }}>
    <label style={{ display: 'block', color: TOKEN.textMuted, fontSize: 12, marginBottom: 6 }}>{label}</label>
    {children}
  </div>
);

const selectStyle = {
  width: '100%',
  background: TOKEN.surfaceRaised,
  border: `1px solid ${TOKEN.surfaceBorder}`,
  borderRadius: 8,
  padding: '8px 12px',
  color: TOKEN.text,
  fontSize: 14,
  outline: 'none',
  fontFamily: 'inherit',
};

const errorBox = {
  background: 'rgba(239,68,68,0.12)',
  border: '1px solid rgba(239,68,68,0.3)',
  borderRadius: 8,
  padding: '9px 13px',
  color: '#f87171',
  fontSize: 13,
  marginTop: 8,
};

const modalActions = { display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 16 };

Object.assign(window, { UserManagementTab });
