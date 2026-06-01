// Admin ASR Correction tab — manage deterministic typo correction rules
// (wrong→correct, global / per-show), preview match count before saving, and
// trigger a backfill (dry-run preview → confirm → run). Part of EQ2a.
const AdminAsrCorrectionTab = ({ lang }) => {
  const t = lang === 'zh';
  const [rows, setRows] = React.useState(null);
  const [shows, setShows] = React.useState([]);
  const [error, setError] = React.useState(null);
  const [toast, setToast] = React.useState(null);

  // new-rule form
  const [wrong, setWrong] = React.useState('');
  const [correct, setCorrect] = React.useState('');
  const [scope, setScope] = React.useState('show');
  const [showId, setShowId] = React.useState('');
  const [note, setNote] = React.useState('');
  const [adding, setAdding] = React.useState(false);
  const [matchCount, setMatchCount] = React.useState(null);

  // backfill
  const [backfillScope, setBackfillScope] = React.useState(''); // '' = all shows
  const [preview, setPreview] = React.useState(null);
  const [previewing, setPreviewing] = React.useState(false);
  const [backfilling, setBackfilling] = React.useState(false);

  const showToast = (msg, kind = 'success') => {
    setToast({ msg, kind });
    setTimeout(() => setToast(null), 3500);
  };

  const reload = React.useCallback(async () => {
    setError(null);
    try {
      const res = await apiFetch('/admin/asr-corrections');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setRows(await res.json());
    } catch (err) {
      setError(err.message || String(err));
    }
  }, []);

  React.useEffect(() => { reload(); }, [reload]);

  React.useEffect(() => {
    (async () => {
      try {
        const res = await apiFetch('/shows');
        if (res.ok) setShows(await res.json());
      } catch { /* non-fatal */ }
    })();
  }, []);

  const showTitle = (id) => {
    const s = shows.find((x) => x.id === id);
    return s ? s.title : id;
  };

  // ── match-count preview (over-broad rule guard) ──
  React.useEffect(() => {
    if (!wrong.trim() || (scope === 'show' && !showId)) {
      setMatchCount(null);
      return;
    }
    let cancelled = false;
    const tid = setTimeout(async () => {
      try {
        const qs = new URLSearchParams({ wrong: wrong.trim(), scope });
        if (scope === 'show' && showId) qs.set('show_id', showId);
        const res = await apiFetch(`/admin/asr-corrections/match-count?${qs}`);
        if (res.ok && !cancelled) setMatchCount((await res.json()).match_count);
      } catch { /* preview is best-effort */ }
    }, 400);
    return () => { cancelled = true; clearTimeout(tid); };
  }, [wrong, scope, showId]);

  const handleAdd = async (e) => {
    e?.preventDefault?.();
    if (!wrong.trim() || adding) return;
    if (scope === 'show' && !showId) {
      showToast(t ? '請選擇節目' : 'Please choose a show', 'warn');
      return;
    }
    setAdding(true);
    try {
      const body = {
        wrong: wrong.trim(),
        correct: correct,
        scope,
        show_id: scope === 'show' ? showId : null,
        note: note.trim() || null,
      };
      const res = await apiFetch('/admin/asr-corrections', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (res.status === 409) {
        showToast(t ? '規則已存在' : 'Rule already exists', 'warn');
        return;
      }
      if (res.status === 422) {
        showToast(t ? '欄位有誤（綁節目需選節目）' : 'Invalid fields', 'warn');
        return;
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setWrong(''); setCorrect(''); setNote(''); setMatchCount(null);
      showToast(
        t ? '已新增（既有逐字稿需按下方「批次回填」才會更新）'
          : 'Added (existing transcripts need a manual backfill below)',
      );
      await reload();
    } catch (err) {
      showToast(err.message || String(err), 'error');
    } finally {
      setAdding(false);
    }
  };

  const handleToggle = async (r) => {
    try {
      const res = await apiFetch(`/admin/asr-corrections/${r.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: !r.enabled }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await reload();
    } catch (err) {
      showToast(err.message || String(err), 'error');
    }
  };

  const handleDelete = async (r) => {
    if (!confirm(t ? `刪除「${r.wrong}→${r.correct}」？` : `Delete "${r.wrong}→${r.correct}"?`)) return;
    try {
      const res = await apiFetch(`/admin/asr-corrections/${r.id}`, { method: 'DELETE' });
      if (!res.ok && res.status !== 204) throw new Error(`HTTP ${res.status}`);
      showToast(t ? '已刪除' : 'Deleted');
      await reload();
    } catch (err) {
      showToast(err.message || String(err), 'error');
    }
  };

  const handlePreview = async () => {
    if (previewing) return;
    setPreviewing(true);
    setPreview(null);
    try {
      const body = { dry_run: true };
      if (backfillScope) body.show_id = backfillScope;
      const res = await apiFetch('/admin/asr-corrections/backfill', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setPreview(await res.json());
    } catch (err) {
      showToast(err.message || String(err), 'error');
    } finally {
      setPreviewing(false);
    }
  };

  const handleConfirmBackfill = async () => {
    if (backfilling) return;
    setBackfilling(true);
    try {
      const body = { dry_run: false };
      if (backfillScope) body.show_id = backfillScope;
      const res = await apiFetch('/admin/asr-corrections/backfill', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      showToast(
        t ? `回填已在背景啟動（任務 ${data.task_id?.slice(0, 8) || ''}）`
          : `Backfill started in background (task ${data.task_id?.slice(0, 8) || ''})`,
      );
      setPreview(null);
    } catch (err) {
      showToast(err.message || String(err), 'error');
    } finally {
      setBackfilling(false);
    }
  };

  const totalCount = rows?.length ?? 0;

  return (
    <div style={{ maxWidth: 920 }}>
      <p style={{ color: TOKEN.textSecondary, fontSize: 13, marginTop: 0, lineHeight: 1.6 }}>
        {t
          ? 'ASR 校正字典：把 Whisper 聽錯的詞（例「咪有企」）對應到正確的詞（「滅火器」）。整詞精確比對。新轉錄會自動套用；既有逐字稿需按下方「批次回填」才會更新（連搜尋一起修）。'
          : 'ASR correction dictionary: map a mis-transcribed term (e.g. "咪有企") to the correct one ("滅火器"). Whole-term literal match. New transcripts apply it automatically; existing transcripts need the backfill below (which also fixes search).'}
      </p>

      {/* ── new rule form ── */}
      <form onSubmit={handleAdd} style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', marginBottom: 6 }}>
        <Input value={wrong} onChange={(e) => setWrong(e.target.value)}
          placeholder={t ? '錯字，例：咪有企' : 'Wrong, e.g. 咪有企'} style={{ width: 180 }} />
        <span style={{ color: TOKEN.textMuted }}>→</span>
        <Input value={correct} onChange={(e) => setCorrect(e.target.value)}
          placeholder={t ? '正字，例：滅火器' : 'Correct, e.g. 滅火器'} style={{ width: 180 }} />
        <select value={scope} onChange={(e) => setScope(e.target.value)}
          style={{ background: TOKEN.surfaceRaised, color: TOKEN.text, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 6, padding: '8px 10px', fontSize: 14 }}>
          <option value="show">{t ? '綁節目' : 'Show'}</option>
          <option value="global">{t ? '全站' : 'Global'}</option>
        </select>
        {scope === 'show' && (
          <select value={showId} onChange={(e) => setShowId(e.target.value)}
            style={{ background: TOKEN.surfaceRaised, color: TOKEN.text, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 6, padding: '8px 10px', fontSize: 14, maxWidth: 200 }}>
            <option value="">{t ? '選節目…' : 'Choose show…'}</option>
            {shows.map((s) => <option key={s.id} value={s.id}>{s.title}</option>)}
          </select>
        )}
        <Input value={note} onChange={(e) => setNote(e.target.value)}
          placeholder={t ? '備註（選填）' : 'Note (optional)'} style={{ width: 160 }} />
        <Btn type="submit" variant="primary" disabled={!wrong.trim() || adding}>
          {adding ? (t ? '新增中…' : 'Adding…') : (t ? '新增' : 'Add')}
        </Btn>
      </form>

      {/* match-count preview — over-broad rule guard */}
      <div style={{ minHeight: 20, marginBottom: 16, fontSize: 12, color: matchCount > 50 ? '#fbbf24' : TOKEN.textMuted }}>
        {matchCount !== null && (
          t ? `目前命中 ${matchCount} 段逐字稿${matchCount > 50 ? '（範圍偏大，請確認不會誤傷）' : ''}`
            : `Currently matches ${matchCount} segment(s)${matchCount > 50 ? ' (broad — double-check for false hits)' : ''}`
        )}
      </div>

      {error && <div style={{ color: '#f87171', fontSize: 13, marginBottom: 12 }}>{error}</div>}

      {/* ── rules table ── */}
      {rows === null ? (
        <div style={{ color: TOKEN.textMuted, fontSize: 13 }}>{t ? '載入中…' : 'Loading…'}</div>
      ) : rows.length === 0 ? (
        <div style={{ color: TOKEN.textMuted, fontSize: 13 }}>{t ? '尚無規則' : 'No rules yet'}</div>
      ) : (
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
          <thead>
            <tr style={{ borderBottom: `1px solid ${TOKEN.surfaceBorder}`, color: TOKEN.textSecondary, textAlign: 'left' }}>
              <th style={{ padding: '10px 8px', fontWeight: 600 }}>{t ? '錯字 → 正字' : 'Wrong → Correct'}</th>
              <th style={{ padding: '10px 8px', fontWeight: 600 }}>{t ? '範圍' : 'Scope'}</th>
              <th style={{ padding: '10px 8px', fontWeight: 600 }}>{t ? '狀態' : 'Status'}</th>
              <th style={{ padding: '10px 8px', fontWeight: 600 }}></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} style={{ borderBottom: `1px solid ${TOKEN.surfaceBorder}`, color: TOKEN.text }}>
                <td style={{ padding: '10px 8px', fontFamily: 'ui-monospace, monospace' }}>
                  {r.wrong} <span style={{ color: TOKEN.textMuted }}>→</span> {r.correct}
                  {r.note ? <span style={{ color: TOKEN.textMuted, fontSize: 12 }}>　{r.note}</span> : null}
                </td>
                <td style={{ padding: '10px 8px' }}>
                  {r.scope === 'global'
                    ? <Badge variant="warning">{t ? '全站' : 'Global'}</Badge>
                    : <Badge variant="default">{showTitle(r.show_id)}</Badge>}
                </td>
                <td style={{ padding: '10px 8px' }}>
                  <Badge variant={r.enabled ? 'success' : 'muted'}>
                    {r.enabled ? (t ? '啟用' : 'Enabled') : (t ? '停用' : 'Disabled')}
                  </Badge>
                </td>
                <td style={{ padding: '10px 8px', textAlign: 'right', whiteSpace: 'nowrap' }}>
                  <Btn variant="ghost" size="sm" onClick={() => handleToggle(r)}>
                    {r.enabled ? (t ? '停用' : 'Disable') : (t ? '啟用' : 'Enable')}
                  </Btn>
                  <Btn variant="danger" size="sm" onClick={() => handleDelete(r)}>
                    {t ? '刪除' : 'Delete'}
                  </Btn>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {/* ── backfill ── */}
      <div style={{ marginTop: 28, paddingTop: 20, borderTop: `1px solid ${TOKEN.surfaceBorder}` }}>
        <div style={{ fontWeight: 600, color: TOKEN.text, marginBottom: 6 }}>
          {t ? '批次回填既有逐字稿' : 'Backfill existing transcripts'}
        </div>
        <p style={{ color: TOKEN.textSecondary, fontSize: 12, marginTop: 0, lineHeight: 1.6 }}>
          {t
            ? '新增規則後，既有逐字稿不會自動更新。回填會修正既有逐字稿並重算受影響片段的搜尋索引。會先估算範圍與成本，你確認後才執行。'
            : 'Newly added rules do not update existing transcripts automatically. Backfill corrects existing transcripts and recomputes the search index for affected chunks. It previews scope + cost first; it runs only after you confirm.'}
        </p>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <select value={backfillScope} onChange={(e) => { setBackfillScope(e.target.value); setPreview(null); }}
            style={{ background: TOKEN.surfaceRaised, color: TOKEN.text, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 6, padding: '8px 10px', fontSize: 14, maxWidth: 220 }}>
            <option value="">{t ? '全部節目' : 'All shows'}</option>
            {shows.map((s) => <option key={s.id} value={s.id}>{s.title}</option>)}
          </select>
          <Btn variant="secondary" onClick={handlePreview} disabled={previewing}>
            {previewing ? (t ? '估算中…' : 'Estimating…') : (t ? '估算範圍' : 'Preview impact')}
          </Btn>
        </div>

        {preview && (
          <div style={{ marginTop: 12, padding: 14, background: TOKEN.surfaceRaised, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 8 }}>
            <div style={{ color: TOKEN.text, fontSize: 13, lineHeight: 1.7 }}>
              {t
                ? `將更新 ${preview.affected_segments} 段、重算 ${preview.affected_chunks} 個片段索引，預估成本約 $${preview.estimated_cost_usd}（embedding）。`
                : `Will update ${preview.affected_segments} segment(s), recompute ${preview.affected_chunks} chunk index(es), est. ~$${preview.estimated_cost_usd} (embedding).`}
            </div>
            <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
              <Btn variant="primary" onClick={handleConfirmBackfill} disabled={backfilling || preview.affected_chunks === 0}>
                {backfilling ? (t ? '執行中…' : 'Running…') : (t ? '確認執行' : 'Confirm & run')}
              </Btn>
              <Btn variant="ghost" onClick={() => setPreview(null)}>{t ? '取消' : 'Cancel'}</Btn>
            </div>
            {preview.affected_chunks === 0 && (
              <div style={{ color: TOKEN.textMuted, fontSize: 12, marginTop: 6 }}>
                {t ? '沒有需要更新的內容。' : 'Nothing to update.'}
              </div>
            )}
          </div>
        )}
      </div>

      <div style={{ marginTop: 18, color: TOKEN.textMuted, fontSize: 12 }}>
        {t ? `共 ${totalCount} 條規則` : `${totalCount} rule(s) total`}
      </div>

      {toast && (
        <div style={{
          position: 'fixed', bottom: 24, right: 24,
          background: toast.kind === 'error' ? '#ef4444' : toast.kind === 'warn' ? '#f59e0b' : TOKEN.accent,
          color: '#fff', padding: '10px 16px', borderRadius: 6, fontSize: 13, boxShadow: '0 4px 12px rgba(0,0,0,0.4)', maxWidth: 360,
        }}>
          {toast.msg}
        </div>
      )}
    </div>
  );
};
