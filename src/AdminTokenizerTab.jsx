// Admin Tokenizer tab — list / add / delete jieba custom dictionary terms.
const AdminTokenizerTab = ({ lang }) => {
  const t = lang === 'zh';
  const [rows, setRows] = React.useState(null);
  const [error, setError] = React.useState(null);
  const [toast, setToast] = React.useState(null);
  const [newTerm, setNewTerm] = React.useState('');
  const [newIsShowName, setNewIsShowName] = React.useState(false);
  const [adding, setAdding] = React.useState(false);
  const [reloading, setReloading] = React.useState(false);

  const showToast = (msg, kind = 'success') => {
    setToast({ msg, kind });
    setTimeout(() => setToast(null), 3000);
  };

  const reload = React.useCallback(async () => {
    setError(null);
    try {
      const res = await apiFetch('/admin/tokenizer/terms');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setRows(await res.json());
    } catch (err) {
      setError(err.message || String(err));
    }
  }, []);
  React.useEffect(() => { reload(); }, [reload]);

  const handleAdd = async (e) => {
    e?.preventDefault?.();
    if (!newTerm.trim() || adding) return;
    setAdding(true);
    try {
      const res = await apiFetch('/admin/tokenizer/terms', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ term: newTerm.trim(), is_show_name: newIsShowName }),
      });
      if (res.status === 409) {
        showToast(t ? '詞已存在' : 'Term already exists', 'warn');
        return;
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setNewTerm('');
      setNewIsShowName(false);
      showToast(t ? '已新增' : 'Added');
      await reload();
    } catch (err) {
      showToast(err.message || String(err), 'error');
    } finally {
      setAdding(false);
    }
  };

  const handleDelete = async (id, term) => {
    if (!confirm(t ? `刪除「${term}」？` : `Delete "${term}"?`)) return;
    try {
      const res = await apiFetch(`/admin/tokenizer/terms/${id}`, {
        method: 'DELETE',
      });
      if (!res.ok && res.status !== 204) throw new Error(`HTTP ${res.status}`);
      showToast(t ? '已刪除' : 'Deleted');
      await reload();
    } catch (err) {
      showToast(err.message || String(err), 'error');
    }
  };

  const handleToggleShowName = async (id, term, current) => {
    try {
      const res = await apiFetch(`/admin/tokenizer/terms/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_show_name: !current }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      showToast(t ? `已更新「${term}」` : `Updated "${term}"`);
      await reload();
    } catch (err) {
      showToast(err.message || String(err), 'error');
    }
  };

  const handleReload = async () => {
    if (reloading) return;
    setReloading(true);
    try {
      const res = await apiFetch('/admin/tokenizer/reload', { method: 'POST' });
      if (res.status !== 202 && !res.ok) throw new Error(`HTTP ${res.status}`);
      showToast(t ? '已觸發重新載入（後端 + workers）' : 'Reload dispatched');
    } catch (err) {
      showToast(err.message || String(err), 'error');
    } finally {
      setReloading(false);
    }
  };

  return (
    <div style={{ maxWidth: 880 }}>
      <p style={{ color: TOKEN.textSecondary, fontSize: 13, marginTop: 0 }}>
        {t ? '為 jieba 新增專有名詞（節目主自創字、來賓名等），讓中文 BM25 檢索能正確切詞。' : 'Custom jieba dictionary terms used by Chinese BM25 retrieval.'}
      </p>

      <form onSubmit={handleAdd} style={{ display: 'flex', gap: 8, marginBottom: 20, alignItems: 'center' }}>
        <Input
          value={newTerm}
          onChange={(e) => setNewTerm(e.target.value)}
          placeholder={t ? '新增詞，例：迪拉胖' : 'New term, e.g. 迪拉胖'}
          style={{ flex: 1, maxWidth: 320 }}
        />
        <label style={{ display: 'flex', alignItems: 'center', gap: 4, color: TOKEN.textSecondary, fontSize: 13 }}>
          <input
            type="checkbox"
            checked={newIsShowName}
            onChange={(e) => setNewIsShowName(e.target.checked)}
          />
          {t ? '節目名（不進關鍵字檢索）' : 'Show name (lexical-excluded)'}
        </label>
        <Btn type="submit" variant="primary" disabled={!newTerm.trim() || adding}>
          {adding ? (t ? '新增中…' : 'Adding…') : (t ? '新增' : 'Add')}
        </Btn>
        <div style={{ flex: 1 }} />
        <Btn variant="secondary" onClick={handleReload} disabled={reloading}>
          {reloading ? (t ? '重新載入中…' : 'Reloading…') : (t ? '重新載入詞典' : 'Reload')}
        </Btn>
      </form>

      {error && (
        <div style={{ color: '#f87171', fontSize: 13, marginBottom: 12 }}>
          {error}
        </div>
      )}

      {rows === null ? (
        <div style={{ color: TOKEN.textMuted, fontSize: 13 }}>{t ? '載入中…' : 'Loading…'}</div>
      ) : rows.length === 0 ? (
        <div style={{ color: TOKEN.textMuted, fontSize: 13 }}>{t ? '尚無詞' : 'No terms yet'}</div>
      ) : (
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
          <thead>
            <tr style={{ borderBottom: `1px solid ${TOKEN.surfaceBorder}`, color: TOKEN.textSecondary, textAlign: 'left' }}>
              <th style={{ padding: '10px 8px', fontWeight: 600 }}>{t ? '詞' : 'Term'}</th>
              <th style={{ padding: '10px 8px', fontWeight: 600 }}>{t ? '權重' : 'Weight'}</th>
              <th style={{ padding: '10px 8px', fontWeight: 600 }}>{t ? '來源' : 'Source'}</th>
              <th style={{ padding: '10px 8px', fontWeight: 600 }}>{t ? '節目名' : 'Show name'}</th>
              <th style={{ padding: '10px 8px', fontWeight: 600 }}>{t ? '建立時間' : 'Created'}</th>
              <th style={{ padding: '10px 8px', fontWeight: 600 }}></th>
            </tr>
          </thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.id} style={{ borderBottom: `1px solid ${TOKEN.surfaceBorder}`, color: TOKEN.text }}>
                <td style={{ padding: '10px 8px', fontFamily: 'ui-monospace, monospace' }}>{r.term}</td>
                <td style={{ padding: '10px 8px' }}>{r.weight}</td>
                <td style={{ padding: '10px 8px' }}>
                  <Badge variant={r.source === 'manual' ? 'default' : 'muted'}>{r.source}</Badge>
                </td>
                <td style={{ padding: '10px 8px' }}>
                  <input
                    type="checkbox"
                    checked={!!r.is_show_name}
                    onChange={() => handleToggleShowName(r.id, r.term, r.is_show_name)}
                  />
                </td>
                <td style={{ padding: '10px 8px', color: TOKEN.textMuted, fontSize: 12 }}>
                  {r.created_at ? new Date(r.created_at).toLocaleString() : ''}
                </td>
                <td style={{ padding: '10px 8px', textAlign: 'right' }}>
                  <Btn variant="danger" size="sm" onClick={() => handleDelete(r.id, r.term)}>
                    {t ? '刪除' : 'Delete'}
                  </Btn>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {toast && (
        <div style={{
          position: 'fixed', bottom: 24, right: 24,
          background: toast.kind === 'error' ? '#ef4444' : toast.kind === 'warn' ? '#f59e0b' : TOKEN.accent,
          color: '#fff', padding: '10px 16px', borderRadius: 6, fontSize: 13, boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
        }}>
          {toast.msg}
        </div>
      )}
    </div>
  );
};
