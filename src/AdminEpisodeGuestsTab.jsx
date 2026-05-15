// Admin Episode Guests tab — pick a show, list episodes with their guest chips,
// open a modal to edit (textarea: one guest per line). Persists via PUT
// /admin/episodes/{id}/guests. Backend caps at 20 entries × 100 chars each.
const AdminEpisodeGuestsTab = ({ lang }) => {
  const t = lang === 'zh';
  const [shows, setShows] = React.useState(null);
  const [selectedShowId, setSelectedShowId] = React.useState('');
  const [episodes, setEpisodes] = React.useState(null);
  const [loadingEpisodes, setLoadingEpisodes] = React.useState(false);
  const [error, setError] = React.useState(null);
  const [editing, setEditing] = React.useState(null); // { episode_id, title, guestsText }
  const [saving, setSaving] = React.useState(false);
  const [toast, setToast] = React.useState(null);

  const showToast = (msg, kind = 'success') => {
    setToast({ msg, kind });
    setTimeout(() => setToast(null), 3000);
  };

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await apiFetch('/shows');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (!cancelled) setShows(data);
      } catch (err) {
        if (!cancelled) setError(err.message || String(err));
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const loadEpisodes = React.useCallback(async (showId) => {
    if (!showId) { setEpisodes(null); return; }
    setLoadingEpisodes(true);
    setError(null);
    try {
      const res = await apiFetch(`/admin/shows/${showId}/guests`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setEpisodes(await res.json());
    } catch (err) {
      setError(err.message || String(err));
      setEpisodes(null);
    } finally {
      setLoadingEpisodes(false);
    }
  }, []);

  React.useEffect(() => { loadEpisodes(selectedShowId); }, [selectedShowId, loadEpisodes]);

  const openEdit = (ep) => {
    setEditing({
      episode_id: ep.episode_id,
      title: ep.title,
      guestsText: (ep.guests || []).join('\n'),
    });
  };
  const closeEdit = () => { if (!saving) setEditing(null); };

  const saveEdit = async () => {
    if (!editing) return;
    const guests = editing.guestsText
      .split('\n')
      .map(s => s.trim())
      .filter(Boolean);
    if (guests.length > 20) {
      showToast(t ? '最多 20 位來賓' : 'Max 20 guests', 'error');
      return;
    }
    if (guests.some(g => g.length > 100)) {
      showToast(t ? '單一來賓名稱超過 100 字' : 'Guest name exceeds 100 chars', 'error');
      return;
    }
    setSaving(true);
    try {
      const res = await apiFetch(`/admin/episodes/${editing.episode_id}/guests`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ guests }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const updated = await res.json();
      setEpisodes(eps => (eps || []).map(e =>
        e.episode_id === editing.episode_id ? { ...e, guests: updated.guests } : e
      ));
      setEditing(null);
      showToast(t ? '已儲存' : 'Saved');
    } catch (err) {
      showToast(err.message || String(err), 'error');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ maxWidth: 960 }}>
      <p style={{ color: TOKEN.textSecondary, fontSize: 13, marginTop: 0 }}>
        {t
          ? '檢視 / 編輯每集的來賓清單。RSS 自動抽取覆蓋不到的（譬如「來賓：馬世芳」這種寫法）可在這裡補。'
          : 'View / edit each episode\'s guest list. Use this to fix the long tail RSS regex extraction misses.'}
      </p>

      <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 20 }}>
        <label style={{ color: TOKEN.textSecondary, fontSize: 13 }}>
          {t ? '節目：' : 'Show: '}
        </label>
        {shows === null ? (
          <span style={{ color: TOKEN.textMuted, fontSize: 13 }}>{t ? '載入中…' : 'Loading…'}</span>
        ) : (
          <select
            value={selectedShowId}
            onChange={(e) => setSelectedShowId(e.target.value)}
            style={{
              background: TOKEN.surfaceRaised, border: `1px solid ${TOKEN.surfaceBorder}`,
              borderRadius: 8, padding: '8px 12px', color: TOKEN.text, fontSize: 14,
              fontFamily: 'inherit', minWidth: 280,
            }}>
            <option value="">{t ? '— 請選擇 —' : '— Select —'}</option>
            {shows.map(s => (
              <option key={s.id} value={s.id}>{s.title}</option>
            ))}
          </select>
        )}
      </div>

      {error && (
        <div style={{ color: '#f87171', fontSize: 13, marginBottom: 12 }}>{error}</div>
      )}

      {selectedShowId && (
        loadingEpisodes ? (
          <div style={{ color: TOKEN.textMuted, fontSize: 13 }}>{t ? '載入集數中…' : 'Loading episodes…'}</div>
        ) : !episodes || episodes.length === 0 ? (
          <div style={{ color: TOKEN.textMuted, fontSize: 13 }}>{t ? '此節目尚無集數' : 'No episodes for this show'}</div>
        ) : (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
            <thead>
              <tr style={{ borderBottom: `1px solid ${TOKEN.surfaceBorder}`, color: TOKEN.textSecondary, textAlign: 'left' }}>
                <th style={{ padding: '10px 8px', fontWeight: 600, width: '50%' }}>{t ? '集數標題' : 'Episode Title'}</th>
                <th style={{ padding: '10px 8px', fontWeight: 600 }}>{t ? '發佈時間' : 'Published'}</th>
                <th style={{ padding: '10px 8px', fontWeight: 600 }}>{t ? '來賓' : 'Guests'}</th>
                <th style={{ padding: '10px 8px', fontWeight: 600 }}></th>
              </tr>
            </thead>
            <tbody>
              {episodes.map(ep => (
                <tr key={ep.episode_id} style={{ borderBottom: `1px solid ${TOKEN.surfaceBorder}`, color: TOKEN.text }}>
                  <td style={{ padding: '10px 8px' }}>{ep.title}</td>
                  <td style={{ padding: '10px 8px', color: TOKEN.textMuted, fontSize: 12 }}>
                    {ep.published_at ? new Date(ep.published_at).toLocaleDateString() : ''}
                  </td>
                  <td style={{ padding: '10px 8px' }}>
                    {(ep.guests && ep.guests.length > 0) ? (
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                        {ep.guests.map((g, i) => <Badge key={i}>{g}</Badge>)}
                      </div>
                    ) : (
                      <span style={{ color: TOKEN.textMuted, fontSize: 12 }}>{t ? '（無）' : '(none)'}</span>
                    )}
                  </td>
                  <td style={{ padding: '10px 8px', textAlign: 'right' }}>
                    <Btn variant="secondary" size="sm" icon="edit" onClick={() => openEdit(ep)}>
                      {t ? '編輯' : 'Edit'}
                    </Btn>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )
      )}

      {editing && (
        <div onClick={closeEdit} style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
        }}>
          <div onClick={e => e.stopPropagation()} style={{
            background: TOKEN.surface, border: `1px solid ${TOKEN.surfaceBorder}`,
            borderRadius: 12, padding: 24, width: 'min(560px, 92vw)',
            boxShadow: '0 20px 60px rgba(0,0,0,0.5)',
          }}>
            <h3 style={{ color: TOKEN.text, fontSize: 16, fontWeight: 700, margin: '0 0 4px' }}>
              {t ? '編輯來賓' : 'Edit Guests'}
            </h3>
            <p style={{ color: TOKEN.textMuted, fontSize: 12, margin: '0 0 16px' }}>
              {editing.title}
            </p>
            <label style={{ display: 'block', color: TOKEN.textSecondary, fontSize: 12, marginBottom: 6 }}>
              {t ? '每行一位來賓（最多 20 位，單名 ≤ 100 字）' : 'One guest per line (max 20, ≤ 100 chars each)'}
            </label>
            <textarea
              value={editing.guestsText}
              onChange={e => setEditing(s => ({ ...s, guestsText: e.target.value }))}
              rows={8}
              style={{
                width: '100%', boxSizing: 'border-box',
                background: TOKEN.surfaceRaised, border: `1px solid ${TOKEN.surfaceBorder}`,
                borderRadius: 8, padding: '10px 12px', color: TOKEN.text, fontSize: 14,
                fontFamily: 'inherit', outline: 'none', resize: 'vertical',
              }}
              placeholder={t ? '例：\n馬世芳\n方品融' : 'e.g.\nGuest A\nGuest B'}
            />
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 16 }}>
              <Btn variant="ghost" onClick={closeEdit} disabled={saving}>
                {t ? '取消' : 'Cancel'}
              </Btn>
              <Btn variant="primary" onClick={saveEdit} disabled={saving}>
                {saving ? (t ? '儲存中…' : 'Saving…') : (t ? '儲存' : 'Save')}
              </Btn>
            </div>
          </div>
        </div>
      )}

      {toast && (
        <div style={{
          position: 'fixed', bottom: 24, right: 24,
          background: toast.kind === 'error' ? '#ef4444' : toast.kind === 'warn' ? '#f59e0b' : TOKEN.accent,
          color: '#fff', padding: '10px 16px', borderRadius: 6, fontSize: 13,
          boxShadow: '0 4px 12px rgba(0,0,0,0.4)', zIndex: 1100,
        }}>
          {toast.msg}
        </div>
      )}
    </div>
  );
};
