// Podcast Selection Page — Layer 1
const COLOR_PALETTE = ['#6366f1', '#22d3ee', '#f59e0b', '#22c55e', '#ec4899'];

const deriveColor = (id) => {
  if (!id) return COLOR_PALETTE[0];
  let hash = 2166136261;
  for (let i = 0; i < id.length; i++) {
    hash ^= id.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return COLOR_PALETTE[Math.abs(hash) % COLOR_PALETTE.length];
};

const PodcastSelect = ({ lang, onSelect, user, setPage }) => {
  const t = lang === 'zh';
  const { isMobile } = useViewport();
  const [search, setSearch] = React.useState('');
  const [hovered, setHovered] = React.useState(null);
  const [shows, setShows] = React.useState(null);
  const [error, setError] = React.useState(null);

  React.useEffect(() => {
    let cancelled = false;
    setShows(null);
    setError(null);
    (async () => {
      try {
        const res = await apiFetch(`/shows`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (!cancelled) setShows(data);
      } catch (err) {
        if (!cancelled) setError(err.message);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const filtered = (shows || []).filter(s => {
    const q = search.toLowerCase();
    return (
      (s.title || '') + (s.description || '') + (s.rss_url || '')
    ).toLowerCase().includes(q);
  });

  const totalTranscribed = (shows || []).reduce((a, s) => a + (s.transcribed_count || 0), 0);

  return (
    <div style={{ flex: 1, overflowY: 'auto', background: TOKEN.bg }}>
      {/* Header */}
      <div style={{ padding: isMobile ? '20px 16px 16px' : '36px 40px 24px', borderBottom: `1px solid ${TOKEN.surfaceBorder}` }}>
        <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', flexWrap: 'wrap', gap: isMobile ? 12 : 16 }}>
          <div style={{ flex: isMobile ? '1 1 100%' : 'none' }}>
            <p style={{ color: TOKEN.accent, fontSize: 12, fontWeight: 600, letterSpacing: '0.1em', textTransform: 'uppercase', margin: '0 0 6px' }}>
              {t ? '節目庫' : 'Show Library'}
            </p>
            <h1 style={{ color: TOKEN.text, fontSize: isMobile ? 22 : 28, fontWeight: 700, margin: 0, lineHeight: 1.2 }}>
              {t ? '選擇 Podcast 節目' : 'Select a Podcast Show'}
            </h1>
            <p style={{ color: TOKEN.textSecondary, fontSize: 14, margin: '8px 0 0' }}>
              {shows
                ? (t ? `共 ${shows.length} 個節目，${totalTranscribed} 集已轉錄完成` : `${shows.length} shows, ${totalTranscribed} episodes transcribed`)
                : (t ? '載入中...' : 'Loading...')}
            </p>
          </div>
          <div style={{ width: isMobile ? '100%' : 280 }}>
            <Input value={search} onChange={e => setSearch(e.target.value)} placeholder={t ? '搜尋節目名稱...' : 'Search shows...'} icon="search" />
          </div>
        </div>
      </div>

      {/* Content */}
      <div style={{ padding: isMobile ? '20px 16px 32px' : '28px 40px 40px' }}>
        {error && (
          <div style={{ textAlign: 'center', padding: '60px 0', color: TOKEN.danger }}>
            <Icon name="search" size={36} color={TOKEN.danger} />
            <p style={{ marginTop: 12, fontSize: 14 }}>
              {t ? `載入節目失敗：${error}` : `Failed to load shows: ${error}`}
            </p>
          </div>
        )}

        {!error && shows === null && (
          <div style={{ textAlign: 'center', padding: '60px 0', color: TOKEN.textMuted }}>
            {t ? '載入中...' : 'Loading...'}
          </div>
        )}

        {!error && shows && shows.length === 0 && (
          <div style={{ textAlign: 'center', padding: '60px 0', color: TOKEN.textMuted }}>
            <Icon name="rss" size={36} color={TOKEN.textMuted} />
            {user && user.role === 'admin' && user.status === 'active' ? (
              <>
                <p style={{ marginTop: 12, fontSize: 14, marginBottom: 14 }}>
                  {t ? '目前尚無節目' : 'No shows yet'}
                </p>
                <Btn onClick={() => setPage && setPage('admin-rag')}>
                  {uiString('empty_shows_admin_cta', lang)}
                </Btn>
              </>
            ) : (
              <p style={{ marginTop: 12, fontSize: 14 }}>
                {uiString('empty_shows_member_hint', lang)}
              </p>
            )}
          </div>
        )}

        {!error && shows && shows.length > 0 && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 20 }}>
            {filtered.map(show => (
              <ShowCard key={show.id} show={show} lang={lang} hovered={hovered === show.id}
                onMouseEnter={() => setHovered(show.id)} onMouseLeave={() => setHovered(null)}
                onClick={() => onSelect(show)} />
            ))}
          </div>
        )}

        {!error && shows && shows.length > 0 && filtered.length === 0 && (
          <div style={{ textAlign: 'center', padding: '60px 0', color: TOKEN.textMuted }}>
            <Icon name="search" size={40} color={TOKEN.textMuted} />
            <p style={{ marginTop: 12 }}>{t ? '找不到符合的節目' : 'No matching shows found'}</p>
          </div>
        )}
      </div>
    </div>
  );
};

const ShowCard = ({ show, lang, hovered, onMouseEnter, onMouseLeave, onClick }) => {
  const t = lang === 'zh';
  const episodeCount = show.episode_count || 0;
  const transcribedCount = show.transcribed_count || 0;
  const pct = episodeCount > 0 ? Math.round((transcribedCount / episodeCount) * 100) : 0;
  const color = deriveColor(show.id);

  return (
    <div onClick={onClick} onMouseEnter={onMouseEnter} onMouseLeave={onMouseLeave}
      style={{ background: TOKEN.surface, border: `1px solid ${hovered ? color + '55' : TOKEN.surfaceBorder}`, borderRadius: 14, padding: 24, cursor: 'pointer', transition: 'all 0.18s', transform: hovered ? 'translateY(-2px)' : 'none', boxShadow: hovered ? `0 8px 30px rgba(0,0,0,0.3), 0 0 0 1px ${color}33` : 'none', display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Cover + title */}
      <div style={{ display: 'flex', gap: 14, alignItems: 'flex-start' }}>
        <div style={{ width: 64, height: 64, borderRadius: 12, background: color + '22', border: `1px solid ${color}44`, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, overflow: 'hidden' }}>
          {show.image_url ? (
            <img src={show.image_url} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
          ) : (
            <Icon name="mic" size={28} color={color} />
          )}
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ color: TOKEN.text, fontWeight: 700, fontSize: 16, lineHeight: 1.3, marginBottom: 4 }}>
            {show.title}
          </div>
          {show.language && (
            <div style={{ color: TOKEN.textSecondary, fontSize: 12 }}>{show.language}</div>
          )}
        </div>
      </div>

      {/* Description */}
      {show.description && (
        <p style={{ color: TOKEN.textSecondary, fontSize: 13, lineHeight: 1.6, margin: 0,
          display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
          {show.description}
        </p>
      )}

      {/* Stats */}
      <div style={{ display: 'flex', gap: 16, fontSize: 13 }}>
        <div style={{ color: TOKEN.textSecondary }}>
          <span style={{ color: TOKEN.text, fontWeight: 600 }}>{episodeCount}</span> {t ? '集' : 'eps'}
        </div>
        <div style={{ color: TOKEN.textSecondary }}>
          <span style={{ color: '#4ade80', fontWeight: 600 }}>{transcribedCount}</span> {t ? '已轉錄' : 'transcribed'}
        </div>
      </div>

      {/* Progress bar */}
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: TOKEN.textMuted, marginBottom: 5 }}>
          <span>{t ? '轉錄進度' : 'Transcription'}</span>
          <span style={{ color: pct === 100 ? '#4ade80' : TOKEN.textSecondary, fontWeight: 600 }}>{pct}%</span>
        </div>
        <div style={{ height: 4, background: TOKEN.surfaceBorder, borderRadius: 99, overflow: 'hidden' }}>
          <div style={{ height: '100%', width: `${pct}%`, background: pct === 100 ? '#22c55e' : color, borderRadius: 99, transition: 'width 0.4s' }} />
        </div>
      </div>

      {/* CTA */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, color: TOKEN.textMuted, minWidth: 0, overflow: 'hidden' }}>
          <Icon name="rss" size={13} color={TOKEN.textMuted} />
          <span style={{ fontFamily: 'monospace', fontSize: 11, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {show.rss_url}
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 4, color: hovered ? color : TOKEN.textMuted, fontSize: 13, fontWeight: 500, transition: 'color 0.15s', flexShrink: 0, marginLeft: 8 }}>
          {t ? '進入節目' : 'Open Show'} <Icon name="chevronRight" size={16} color="currentColor" />
        </div>
      </div>
    </div>
  );
};

Object.assign(window, { PodcastSelect, deriveColor });
