// Transcript Page — Layer 3: Timeline + Keyword highlight
//
// R2.1 section 4 (deep-link receiver):
//   • On mount we parse `?t=<seconds>` from the URL once and treat it as the
//     authoritative deep-link target (Decision 3: pure-seconds URL, no
//     auto-play). The legacy `highlightTime` prop is kept as a fallback for
//     in-app navigation that did not yet round-trip through the URL.
//   • A matched segment must fall within ±5 s of `t`; outside the window we
//     scroll the transcript to the top and skip the highlight (no error).
const _readDeepLinkSeconds = () => {
  try {
    const params = new URLSearchParams(window.location.search);
    const raw = params.get('t');
    if (raw == null || raw === '') return null;
    const n = Number(raw);
    return Number.isFinite(n) && n >= 0 ? n : null;
  } catch (_) {
    return null;
  }
};

const TranscriptPage = ({ lang, show, episode, onBack, initSearch, highlightTime }) => {
  const t = lang === 'zh';
  const { isMobile } = useViewport();
  // landing-and-mode-orchestration-redesign decision 6: use the cross-page
  // AudioPlayerContext so playback survives QueryPage ↔ TranscriptPage.
  const audio = (typeof useAudioPlayer === 'function') ? useAudioPlayer() : null;
  const [search, setSearch] = React.useState(initSearch || '');
  const [activeIdx, setActiveIdx] = React.useState(null);
  const [highlightedIdx, setHighlightedIdx] = React.useState(null);
  const [segments, setSegments] = React.useState(null);
  const [segError, setSegError] = React.useState(null);
  // Resolve deep-link seconds once on mount: URL `?t=` wins, prop is fallback.
  const deepLinkSecondsRef = React.useRef(undefined);
  if (deepLinkSecondsRef.current === undefined) {
    const fromUrl = _readDeepLinkSeconds();
    deepLinkSecondsRef.current = fromUrl != null ? fromUrl : (typeof highlightTime === 'number' ? highlightTime : null);
  }

  React.useEffect(() => {
    if (!episode?.id) return;
    setSegments(null);
    setSegError(null);
    setActiveIdx(null);
    apiFetch(`/episodes/${episode.id}/transcript`)
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then(data => setSegments(data.segments || []))
      .catch(err => setSegError(err.message));
  }, [episode?.id]);

  // landing-and-mode-orchestration-redesign decision 7: derive paragraphs from
  // segments using the shared aggregateParagraphs util (gap ≥ 1.5s OR speaker
  // change). Memoize so we don't recompute on every render.
  const paragraphs = React.useMemo(() => {
    if (!segments || segments.length === 0) return [];
    if (typeof window.aggregateParagraphs !== 'function') return segments.map((s, i) => ({
      paragraph_text: s.text, start_time: s.start_time, end_time: s.end_time, speaker: s.speaker, segment_ids: [String(i)],
    }));
    return window.aggregateParagraphs(segments, { gap_threshold_seconds: 1.5 });
  }, [segments]);

  const fmtTime = (sec) => {
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  };

  React.useEffect(() => {
    const target = deepLinkSecondsRef.current;
    if (target == null || !segments?.length) return;
    let closest = 0, minDiff = Infinity;
    segments.forEach((seg, i) => {
      const diff = Math.abs(seg.start_time - target);
      if (diff < minDiff) { minDiff = diff; closest = i; }
    });
    // R2.1 Decision: only highlight if the closest segment is within ±5 s of
    // the requested timestamp. Outside the window we scroll to the top and
    // skip the highlight — no error UI per spec.
    const WINDOW_SECONDS = 5;
    if (minDiff > WINDOW_SECONDS) {
      setHighlightedIdx(null);
      setTimeout(() => {
        const scroller = document.getElementById('transcript-scroll');
        if (scroller) scroller.scrollTop = 0;
      }, 100);
      return;
    }
    setHighlightedIdx(closest);
    setActiveIdx(closest);
    setTimeout(() => {
      const el = document.getElementById(`seg-${closest}`);
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }, 100);
    const timer = setTimeout(() => setHighlightedIdx(null), 3000);
    return () => clearTimeout(timer);
  }, [segments]);

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
      <div style={{ padding: isMobile ? '10px 12px' : '14px 32px', borderBottom: `1px solid ${TOKEN.surfaceBorder}`, background: TOKEN.surface, flexShrink: 0, display: 'flex', alignItems: 'center', gap: isMobile ? 8 : 12, flexWrap: 'wrap' }}>
        <Btn variant="ghost" size="sm" icon="arrowLeft" onClick={onBack}>{isMobile ? '' : (t ? '返回查詢' : 'Back')}</Btn>
        {!isMobile && <div style={{ width: 1, height: 20, background: TOKEN.surfaceBorder }} />}
        <div style={{ flex: 1, minWidth: isMobile ? 0 : 200 }}>
          <div style={{ color: TOKEN.text, fontWeight: 600, fontSize: 14, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{episode.title}</div>
          <div style={{ display: 'flex', gap: 12, marginTop: 3, fontSize: 12, color: TOKEN.textMuted }}>
            {episode.published_at && <span>{episode.published_at.slice(0, 10)}</span>}
            {episode.duration_seconds && <span style={{ display: 'flex', alignItems: 'center', gap: 3 }}><Icon name="clock" size={11} />{fmtTime(episode.duration_seconds)}</span>}
          </div>
        </div>
        <div style={{ width: isMobile ? '100%' : 260 }}>
          <Input value={search} onChange={e => setSearch(e.target.value)} placeholder={t ? '關鍵字高亮搜尋...' : 'Highlight keywords...'} icon="search" />
        </div>
        {search && <span style={{ fontSize: 12, color: TOKEN.textMuted, whiteSpace: 'nowrap' }}>{matchCount} {t ? '個匹配' : 'matches'}</span>}
        {episode && episode.audio_url && (
          <Btn variant="secondary" size="sm" icon="play"
            disabled={!audio}
            onClick={() => {
              // landing-redesign-hotfix-transcript-and-audio task 4.4 — single
              // deploy cycle of instrumentation; remove in task 8.1 after prod
              // smoke confirms which condition was previously falsy.
              try { console.log('[transcript-play]', {
                hasAudio: !!audio,
                hasEpisode: !!episode,
                hasUrl: !!episode?.audio_url,
                paragraphsLen: paragraphs?.length,
              }); } catch (_) { /* ignore */ }
              if (!audio) return;
              const startSec = (activeIdx != null && segments && segments[activeIdx])
                ? segments[activeIdx].start_time : 0;
              audio.playFromTime(episode.id, startSec, {
                title: episode.title,
                audio_url: episode.audio_url,
              });
            }}>
            {t ? '從此處播放' : 'Play here'}
          </Btn>
        )}
      </div>

      {(episode.ai_summary_status === 'done' && episode.ai_summary) || episode.description ? (
        <div style={{ padding: isMobile ? '10px 12px' : '12px 32px', borderBottom: `1px solid ${TOKEN.surfaceBorder}`, background: TOKEN.bg }}>
          <div style={{ fontSize: 11, color: TOKEN.textMuted, fontWeight: 600, marginBottom: 4, letterSpacing: 0.5, textTransform: 'uppercase' }}>{t ? '本集摘要' : 'Episode summary'}</div>
          <EpisodeBlurb episode={episode} lang={lang} style={{ fontSize: 13, WebkitLineClamp: 4 }} />
        </div>
      ) : null}

      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        {/* Left: Timeline (desktop only) */}
        {!isMobile && (
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
        )}

        {/* Right: Full transcript */}
        <div id="transcript-scroll" style={{ flex: 1, overflowY: 'auto', padding: isMobile ? '14px 12px' : '20px 32px' }}>
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
              {/* landing-and-mode-orchestration-redesign decision 7: render
                  by paragraph (gap ≥ 1.5s) instead of raw segments. We keep
                  per-segment `id="seg-{i}"` anchors for the deep-link
                  scroll-to-segment logic; the paragraph wrapper holds the
                  outer paragraph and within it the original segment lines
                  remain individually targetable. */}
              {/* landing-redesign-hotfix-transcript-and-audio task 6.2a:
                  segment_ids are UUID strings — must map back via findIndex,
                  NOT parseInt (which would stop at the first non-digit char). */}
              {paragraphs.map((para, pIdx) => {
                const segIds = para.segment_ids || [];
                const segIndexFor = (sid) => segments.findIndex((s, idx) => String(s.id != null ? s.id : idx) === sid);
                const containsActive = segIds.some(sid => segIndexFor(sid) === activeIdx);
                const matched = search.trim() && (para.paragraph_text || '').toLowerCase().includes(search.trim().toLowerCase());
                return (
                  <div key={pIdx}
                    style={{
                      display: 'flex',
                      gap: isMobile ? 10 : 20,
                      padding: isMobile ? '12px 8px' : '16px 14px',
                      borderRadius: 10,
                      background: containsActive ? TOKEN.accentDim : matched ? '#fbbf2411' : 'transparent',
                      border: `1px solid ${containsActive ? TOKEN.accent + '44' : matched ? '#fbbf2433' : 'transparent'}`,
                      marginBottom: 6,
                      transition: 'all 0.3s',
                    }}
                  >
                    <div style={{ minWidth: isMobile ? 50 : 80, textAlign: 'right', flexShrink: 0 }}>
                      <div style={{ color: TOKEN.accent, fontSize: isMobile ? 11 : 12, fontFamily: 'monospace', fontWeight: 600 }}>{fmtTime(para.start_time || 0)}</div>
                    </div>
                    <div style={{ width: 1, background: containsActive ? TOKEN.accent + '55' : TOKEN.surfaceBorder, flexShrink: 0, borderRadius: 99 }} />
                    <p style={{ margin: 0, color: containsActive ? TOKEN.text : TOKEN.textSecondary, fontSize: 14, lineHeight: 1.85, flex: 1 }}>
                      {/* Internal segment anchors preserved for deep-link */}
                      {segIds.map((sid, sIdx) => {
                        const segIndex = segIndexFor(sid);
                        const seg = (segIndex >= 0 && segments[segIndex]) ? segments[segIndex] : null;
                        if (!seg) return null;
                        const active = activeIdx === segIndex;
                        const isHighlighted = highlightedIdx === segIndex;
                        return (
                          <span
                            key={sIdx}
                            id={`seg-${segIndex}`}
                            onClick={() => setActiveIdx(segIndex)}
                            style={{
                              cursor: 'pointer',
                              background: isHighlighted ? TOKEN.accent + '33' : 'transparent',
                              borderRadius: 4,
                              transition: 'background 0.3s',
                            }}
                          >
                            {highlight(seg.text)}
                            {sIdx < segIds.length - 1 ? ' ' : ''}
                          </span>
                        );
                      })}
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
