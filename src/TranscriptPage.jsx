// Transcript Page — Layer 3: Timeline + Keyword highlight
const TranscriptPage = ({ lang, show, episode, onBack, initSearch, highlightTime }) => {
  const t = lang === 'zh';
  const [search, setSearch] = React.useState(initSearch || '');
  const [activeIdx, setActiveIdx] = React.useState(null);
  const [highlightedIdx, setHighlightedIdx] = React.useState(null);
  const [segments, setSegments] = React.useState(null);
  const [segError, setSegError] = React.useState(null);

  React.useEffect(() => {
    if (!episode?.id) return;
    setSegments(null);
    setSegError(null);
    setActiveIdx(null);
    fetch(`${API_BASE}/episodes/${episode.id}/transcript`)
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then(data => setSegments(data.segments || []))
      .catch(err => setSegError(err.message));
  }, [episode?.id]);

  const fmtTime = (sec) => {
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  };

  React.useEffect(() => {
    if (highlightTime == null || !segments?.length) return;
    let closest = 0, minDiff = Infinity;
    segments.forEach((seg, i) => {
      const diff = Math.abs(seg.start_time - highlightTime);
      if (diff < minDiff) { minDiff = diff; closest = i; }
    });
    setHighlightedIdx(closest);
    setActiveIdx(closest);
    setTimeout(() => {
      const el = document.getElementById(`seg-${closest}`);
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }, 100);
    const timer = setTimeout(() => setHighlightedIdx(null), 3000);
    return () => clearTimeout(timer);
  }, [highlightTime, segments]);

  const highlight = (text) => {
    if (!search.trim()) return text;
    const parts = text.split(new RegExp(`(${search.trim()})`, 'gi'));
    return parts.map((p, i) =>
      p.toLowerCase() === search.trim().toLowerCase()
        ? <mark key={i} style={{ background: '#fbbf24aa', color: '#fef3c7', borderRadius: 3, padding: '0 2px' }}>{p}</mark>
        : p
    );
  };

  const matchCount = search.trim() && segments
    ? segments.filter(s => s.text.toLowerCase().includes(search.trim().toLowerCase())).length
    : 0;

  const totalSec = segments?.length
    ? (segments[segments.length - 1].end_time || segments[segments.length - 1].start_time + 30)
    : 3600;
  const activeSeg = activeIdx != null && segments ? segments[activeIdx] : null;
  const pct = activeSeg ? (activeSeg.start_time / totalSec) * 100 : 0;

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', background: TOKEN.bg }}>
      {/* Top bar */}
      <div style={{ padding: '14px 32px', borderBottom: `1px solid ${TOKEN.surfaceBorder}`, background: TOKEN.surface, flexShrink: 0, display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <Btn variant="ghost" size="sm" icon="arrowLeft" onClick={onBack}>{t ? '返回查詢' : 'Back'}</Btn>
        <div style={{ width: 1, height: 20, background: TOKEN.surfaceBorder }} />
        <div style={{ flex: 1, minWidth: 200 }}>
          <div style={{ color: TOKEN.text, fontWeight: 600, fontSize: 14 }}>{episode.title}</div>
          <div style={{ display: 'flex', gap: 12, marginTop: 3, fontSize: 12, color: TOKEN.textMuted }}>
            {episode.published_at && <span>{episode.published_at.slice(0, 10)}</span>}
            {episode.duration_seconds && <span style={{ display: 'flex', alignItems: 'center', gap: 3 }}><Icon name="clock" size={11} />{fmtTime(episode.duration_seconds)}</span>}
          </div>
        </div>
        <div style={{ width: 260 }}>
          <Input value={search} onChange={e => setSearch(e.target.value)} placeholder={t ? '關鍵字高亮搜尋...' : 'Highlight keywords...'} icon="search" />
        </div>
        {search && <span style={{ fontSize: 12, color: TOKEN.textMuted, whiteSpace: 'nowrap' }}>{matchCount} {t ? '個匹配' : 'matches'}</span>}
      </div>

      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        {/* Left: Timeline */}
        <div style={{ width: 280, borderRight: `1px solid ${TOKEN.surfaceBorder}`, display: 'flex', flexDirection: 'column', overflowY: 'auto', flexShrink: 0 }}>
          <div style={{ padding: '16px 16px 16px' }}>
            <div style={{ fontSize: 12, color: TOKEN.textSecondary, fontWeight: 600, marginBottom: 10 }}>{t ? '時間軸' : 'Timeline'}</div>
            {segments && segments.length > 0 && (
              <>
                <div style={{ position: 'relative', height: 4, background: TOKEN.surfaceBorder, borderRadius: 99, marginBottom: 14, cursor: 'pointer' }}>
                  {segments.filter((_, i) => i % Math.max(1, Math.floor(segments.length / 20)) === 0).map((seg, dotIdx) => {
                    const i = segments.indexOf(seg);
                    return (
                      <div key={i} title={fmtTime(seg.start_time)} onClick={() => setActiveIdx(i)}
                        style={{ position: 'absolute', top: -4, width: 12, height: 12, borderRadius: '50%', background: activeIdx === i ? TOKEN.accent : TOKEN.surfaceBorder, border: `2px solid ${activeIdx === i ? TOKEN.accent : TOKEN.textMuted}`, left: `${(seg.start_time / totalSec) * 100}%`, transform: 'translateX(-50%)', cursor: 'pointer', transition: 'all 0.12s', zIndex: 1 }} />
                    );
                  })}
                  <div style={{ height: '100%', width: `${pct}%`, background: TOKEN.accent, borderRadius: 99 }} />
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                  {segments.filter((_, i) => i % Math.max(1, Math.floor(segments.length / 40)) === 0).map((seg) => {
                    const i = segments.indexOf(seg);
                    const matched = search && seg.text.toLowerCase().includes(search.toLowerCase());
                    return (
                      <div key={i} onClick={() => { setActiveIdx(i); document.getElementById(`seg-${i}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }); }}
                        style={{ display: 'flex', gap: 8, padding: '6px 8px', borderRadius: 7, cursor: 'pointer', background: activeIdx === i ? TOKEN.accentDim : matched ? '#fbbf2422' : 'transparent', border: `1px solid ${activeIdx === i ? TOKEN.accent + '44' : matched ? '#fbbf2444' : 'transparent'}`, transition: 'all 0.1s' }}>
                        <span style={{ color: TOKEN.accent, fontSize: 11, fontFamily: 'monospace', minWidth: 38, paddingTop: 1 }}>{fmtTime(seg.start_time)}</span>
                        <span style={{ color: TOKEN.textSecondary, fontSize: 11, lineHeight: 1.4, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>
                          {seg.text.slice(0, 20)}
                          {matched && <span style={{ marginLeft: 4 }}><Badge variant="warning">●</Badge></span>}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </>
            )}
            {!segments && !segError && (
              <div style={{ color: TOKEN.textMuted, fontSize: 13, textAlign: 'center', paddingTop: 20 }}>
                <div style={{ display: 'flex', gap: 4, justifyContent: 'center' }}>
                  {[0,1,2].map(i => <div key={i} style={{ width: 6, height: 6, borderRadius: '50%', background: TOKEN.accent, animation: 'bounce 1.2s infinite', animationDelay: `${i * 0.2}s` }} />)}
                </div>
              </div>
            )}
            {segError && <div style={{ color: '#f87171', fontSize: 12, padding: 8 }}>{segError}</div>}
          </div>
        </div>

        {/* Right: Full transcript */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '20px 32px' }}>
          {!segments && !segError && (
            <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 60 }}>
              <div style={{ display: 'flex', gap: 6 }}>
                {[0,1,2].map(i => <div key={i} style={{ width: 8, height: 8, borderRadius: '50%', background: TOKEN.accent, animation: 'bounce 1.2s infinite', animationDelay: `${i * 0.2}s` }} />)}
              </div>
            </div>
          )}
          {segError && (
            <div style={{ textAlign: 'center', paddingTop: 60, color: TOKEN.textMuted }}>
              <div style={{ color: '#f87171', marginBottom: 8 }}>{t ? '載入失敗' : 'Failed to load'}</div>
              <div style={{ fontSize: 12 }}>{segError}</div>
            </div>
          )}
          {segments && segments.length === 0 && (
            <div style={{ textAlign: 'center', paddingTop: 60, color: TOKEN.textMuted, fontSize: 14 }}>
              {t ? '此集尚無逐字稿內容' : 'No transcript available for this episode'}
            </div>
          )}
          {segments && segments.length > 0 && (
            <div style={{ maxWidth: 720, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 0 }}>
              {segments.map((seg, i) => {
                const matched = search.trim() && seg.text.toLowerCase().includes(search.trim().toLowerCase());
                const active = activeIdx === i;
                return (
                  <div key={i} id={`seg-${i}`}
                    style={{ display: 'flex', gap: 20, padding: '16px 14px', borderRadius: 10, background: highlightedIdx === i ? TOKEN.accent + '33' : active ? TOKEN.accentDim : matched ? '#fbbf2411' : 'transparent', border: `1px solid ${highlightedIdx === i ? TOKEN.accent : active ? TOKEN.accent + '44' : matched ? '#fbbf2433' : 'transparent'}`, marginBottom: 4, transition: 'all 0.3s', cursor: 'pointer' }}
                    onClick={() => setActiveIdx(i)}>
                    <div style={{ minWidth: 80, textAlign: 'right', flexShrink: 0 }}>
                      <div style={{ color: TOKEN.accent, fontSize: 12, fontFamily: 'monospace', fontWeight: 600 }}>{fmtTime(seg.start_time)}</div>
                    </div>
                    <div style={{ width: 1, background: active ? TOKEN.accent + '55' : TOKEN.surfaceBorder, flexShrink: 0, borderRadius: 99 }} />
                    <p style={{ margin: 0, color: active ? TOKEN.text : TOKEN.textSecondary, fontSize: 14, lineHeight: 1.8, flex: 1 }}>
                      {highlight(seg.text)}
                    </p>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

Object.assign(window, { TranscriptPage });
