// Admin Tokenizer tab — list / add / delete jieba custom dictionary terms.
const TOKENIZER_LAST_SYNC_KEY = 'tokenizerLastSyncAt';

const AdminTokenizerTab = ({ lang }) => {
  const t = lang === 'zh';
  const [rows, setRows] = React.useState(null);
  const [error, setError] = React.useState(null);
  const [toast, setToast] = React.useState(null);
  const [newTerm, setNewTerm] = React.useState('');
  const [adding, setAdding] = React.useState(false);
  const [reloading, setReloading] = React.useState(false);
  const [lastSyncAt, setLastSyncAt] = React.useState(() => {
    try { return localStorage.getItem(TOKENIZER_LAST_SYNC_KEY); } catch { return null; }
  });

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
        body: JSON.stringify({ term: newTerm.trim() }),
      });
      if (res.status === 409) {
        showToast(t ? '詞已存在' : 'Term already exists', 'warn');
        return;
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setNewTerm('');
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

  const handleReload = async () => {
    if (reloading) return;
    setReloading(true);
    try {
      const res = await apiFetch('/admin/tokenizer/reload', { method: 'POST' });
      if (res.status !== 202 && !res.ok) throw new Error(`HTTP ${res.status}`);
      const nowIso = new Date().toISOString();
      setLastSyncAt(nowIso);
      try { localStorage.setItem(TOKENIZER_LAST_SYNC_KEY, nowIso); } catch {}
      showToast(t ? '已套用到搜尋（轉錄 worker 會在幾秒內同步）' : 'Applied to search (transcription worker syncs in seconds)');
    } catch (err) {
      showToast(err.message || String(err), 'error');
    } finally {
      setReloading(false);
    }
  };

  const formatSync = (iso) => {
    if (!iso) return t ? '尚未同步' : 'Not synced yet';
    try {
      const d = new Date(iso);
      const pad = (n) => String(n).padStart(2, '0');
      return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
    } catch {
      return iso;
    }
  };

  const totalCount = rows?.length ?? 0;

  return (
    <div style={{ maxWidth: 880 }}>
      <p style={{ color: TOKEN.textSecondary, fontSize: 13, marginTop: 0, lineHeight: 1.6 }}>
        {t
          ? '加進來的詞會被當作一個整體，不會被拆開。例如把「迪拉胖」加進來後，搜尋時就不會被切成「迪 / 拉 / 胖」三個字。'
          : 'Terms added here are treated as single units and won\'t be split. For example, adding "迪拉胖" prevents it from being cut into "迪 / 拉 / 胖".'}
      </p>

      <form onSubmit={handleAdd} style={{ display: 'flex', gap: 8, marginBottom: 12, alignItems: 'center' }}>
        <Input
          value={newTerm}
          onChange={(e) => setNewTerm(e.target.value)}
          placeholder={t ? '新增詞，例：迪拉胖' : 'New term, e.g. 迪拉胖'}
          style={{ flex: 1, maxWidth: 320 }}
        />
        <Btn type="submit" variant="primary" disabled={!newTerm.trim() || adding}>
          {adding ? (t ? '新增中…' : 'Adding…') : (t ? '新增' : 'Add')}
        </Btn>
        <div style={{ flex: 1 }} />
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 2 }}>
          <Btn variant="secondary" onClick={handleReload} disabled={reloading}>
            {reloading ? (t ? '套用中…' : 'Applying…') : (t ? '立刻套用到搜尋' : 'Apply to search now')}
          </Btn>
          <span style={{ color: TOKEN.textMuted, fontSize: 11 }}>
            {t ? '幾秒內生效' : 'Takes effect in seconds'}
          </span>
        </div>
      </form>

      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        marginBottom: 12, color: TOKEN.textMuted, fontSize: 12,
      }}>
        <span>
          {t ? '上次同步：' : 'Last synced: '}{formatSync(lastSyncAt)}
          {lastSyncAt && rows !== null ? `（${totalCount} ${t ? '詞' : 'terms'}）` : ''}
        </span>
        <span>
          {t ? `共 ${totalCount} 詞` : `${totalCount} terms total`}
        </span>
      </div>

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
              <th style={{ padding: '10px 8px', fontWeight: 600 }}>{t ? '來源' : 'Source'}</th>
              <th style={{ padding: '10px 8px', fontWeight: 600 }}>{t ? '建立時間' : 'Created'}</th>
              <th style={{ padding: '10px 8px', fontWeight: 600 }}></th>
            </tr>
          </thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.id} style={{ borderBottom: `1px solid ${TOKEN.surfaceBorder}`, color: TOKEN.text }}>
                <td style={{ padding: '10px 8px', fontFamily: 'ui-monospace, monospace' }}>{r.term}</td>
                <td style={{ padding: '10px 8px' }}>
                  <Badge variant={r.source === 'manual' ? 'default' : 'muted'}>{r.source}</Badge>
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
