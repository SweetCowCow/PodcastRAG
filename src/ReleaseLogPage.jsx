// ReleaseLogPage — vertical timeline of all release entries (newest first).
// Reads window.RELEASE_LOG / TAG_LABELS / MILESTONE_LABELS from src/releaseLog.jsx.

const TAG_VARIANT = {
  feature: 'success',
  fix: 'warning',
  enhancement: 'default',
  ui: 'muted',
};

const ReleaseLogPage = ({ lang }) => {
  const t = lang === 'zh';
  const { isMobile } = useViewport();

  // Live-fetch admin stats; fallback to hardcoded values from releaseLog.jsx.
  const [stats, setStats] = React.useState(null);
  React.useEffect(() => {
    let cancelled = false;
    apiFetch('/stats').then(res => {
      if (cancelled || !res.ok) return;
      return res.json();
    }).then(body => {
      if (cancelled || !body) return;
      setStats(body);
    }).catch(() => {});
    return () => { cancelled = true; };
  }, []);

  // All entries sorted by date DESC across all milestones.
  const sortedEntries = RELEASE_LOG.slice().sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0));

  // Compute where to insert milestone markers: a marker appears before each
  // run of entries belonging to a new milestone (compared to previous entry).
  const items = [];
  let lastMilestone = null;
  sortedEntries.forEach(entry => {
    if (entry.milestone !== lastMilestone) {
      items.push({ type: 'marker', milestone: entry.milestone });
      lastMilestone = entry.milestone;
    }
    items.push({ type: 'entry', entry });
  });

  // Layout: vertical line on the left; nodes/markers attach to it; cards to the right.
  const LINE_LEFT = isMobile ? 14 : 96; // x-position of the timeline line
  const NODE_SIZE = 12;
  const MARKER_SIZE = 18;

  return (
    <div style={{ flex: 1, overflow: 'auto', padding: isMobile ? '24px 16px 48px' : '40px 28px 64px' }}>
      <div style={{ maxWidth: 920, margin: '0 auto' }}>
        {/* Header */}
        <div style={{ marginBottom: 28 }}>
          <h1 style={{ color: TOKEN.text, fontSize: isMobile ? 24 : 30, fontWeight: 700, margin: '0 0 8px' }}>
            {t ? '更新日誌' : 'Change Log'}
          </h1>
          <p style={{ color: TOKEN.textSecondary, fontSize: 14, margin: 0, lineHeight: 1.6 }}>
            {t
              ? 'PodcastRAG 一路長出來的功能,依時間由新到舊排列。'
              : 'What PodcastRAG has grown into, newest first along the timeline.'}
          </p>
        </div>

        {/* Stats banner */}
        <StatsBanner lang={lang} live={stats} isMobile={isMobile} />

        {/* Timeline */}
        <div style={{ position: 'relative', marginTop: 28 }}>
          {/* The vertical line */}
          {items.length > 0 && (
            <div style={{
              position: 'absolute',
              left: LINE_LEFT,
              top: 0,
              bottom: 0,
              width: 2,
              background: TOKEN.surfaceBorder,
            }} />
          )}

          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            {items.map((it, idx) => it.type === 'marker'
              ? <TimelineMarker key={`m-${it.milestone}-${idx}`}
                  milestone={it.milestone} lang={lang} isMobile={isMobile}
                  lineLeft={LINE_LEFT} markerSize={MARKER_SIZE} />
              : <TimelineEntry key={it.entry.slug} entry={it.entry} lang={lang} t={t} isMobile={isMobile}
                  lineLeft={LINE_LEFT} nodeSize={NODE_SIZE} />
            )}
          </div>
        </div>

        {items.length === 0 && (
          <div style={{ textAlign: 'center', padding: '60px 0', color: TOKEN.textMuted }}>
            {t ? '尚無更新紀錄' : 'No release entries yet'}
          </div>
        )}
      </div>
    </div>
  );
};

const StatsBanner = ({ lang, live, isMobile }) => {
  const t = lang === 'zh';
  const figures = live
    ? {
        changes: STATS_CHANGES_COUNT,           // not in admin/stats yet — keep static
        episodes: live.episodes_completed,
        chunks: live.transcript_chunks,
        users: live.users,
      }
    : {
        changes: STATS_CHANGES_COUNT,
        episodes: STATS_EPISODES_COUNT,
        chunks: STATS_VECTORS_COUNT,
        users: null,
      };
  const labelDate = live
    ? (t ? '即時' : 'live')
    : `${t ? '截至' : 'as of'} ${STATS_AS_OF}`;

  const Stat = ({ value, zh, en }) => (
    <div style={{ flex: 1, minWidth: 100, padding: '10px 12px', textAlign: 'center' }}>
      <div style={{ color: TOKEN.text, fontSize: isMobile ? 18 : 22, fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>
        {value === null || value === undefined ? '—' : value.toLocaleString()}
      </div>
      <div style={{ color: TOKEN.textMuted, fontSize: 11, marginTop: 2 }}>{t ? zh : en}</div>
    </div>
  );

  return (
    <div style={{
      background: TOKEN.surface, border: `1px solid ${TOKEN.surfaceBorder}`,
      borderRadius: 12, padding: '6px 4px',
      display: 'flex', flexWrap: 'wrap',
    }}>
      <Stat value={figures.changes} zh="累計 changes" en="Total changes" />
      <Stat value={figures.episodes} zh="集數轉錄完成" en="Episodes done" />
      <Stat value={figures.chunks} zh="向量片段" en="Vector chunks" />
      {live && <Stat value={figures.users} zh="註冊使用者" en="Users" />}
      <div style={{ width: '100%', textAlign: 'center', color: TOKEN.textMuted, fontSize: 11, padding: '4px 0 6px' }}>
        {labelDate}
      </div>
    </div>
  );
};

const TimelineMarker = ({ milestone, lang, isMobile, lineLeft, markerSize }) => {
  const label = MILESTONE_LABELS[milestone] ? MILESTONE_LABELS[milestone][lang] : milestone;
  return (
    <div style={{ position: 'relative', paddingLeft: lineLeft + 24, marginTop: 8 }}>
      {/* large dot */}
      <div style={{
        position: 'absolute',
        left: lineLeft - markerSize / 2 + 1,
        top: 4,
        width: markerSize,
        height: markerSize,
        borderRadius: '50%',
        background: TOKEN.accent,
        boxShadow: `0 0 0 4px ${TOKEN.bg}`,
      }} />
      <div style={{
        color: TOKEN.accent, fontWeight: 700, fontSize: isMobile ? 15 : 17,
        letterSpacing: '0.01em', padding: '4px 0',
      }}>
        {label}
      </div>
    </div>
  );
};

const TimelineEntry = ({ entry, lang, t, isMobile, lineLeft, nodeSize }) => {
  const tagLabel = TAG_LABELS[entry.tag] ? TAG_LABELS[entry.tag][lang] : entry.tag;
  const tagVariant = TAG_VARIANT[entry.tag] || 'default';
  return (
    <div style={{ position: 'relative', paddingLeft: lineLeft + 24 }}>
      {/* node */}
      <div style={{
        position: 'absolute',
        left: lineLeft - nodeSize / 2 + 1,
        top: 12,
        width: nodeSize,
        height: nodeSize,
        borderRadius: '50%',
        background: TOKEN.surface,
        border: `2px solid ${TOKEN.accent}`,
        boxShadow: `0 0 0 3px ${TOKEN.bg}`,
      }} />
      {/* date label on desktop sits to the LEFT of the line */}
      {!isMobile && (
        <div style={{
          position: 'absolute',
          left: 0,
          top: 12,
          width: lineLeft - nodeSize / 2 - 10,
          textAlign: 'right',
          color: TOKEN.textMuted,
          fontSize: 12,
          fontVariantNumeric: 'tabular-nums',
        }}>
          {entry.date}
        </div>
      )}
      {/* card */}
      <div style={{
        background: TOKEN.surface,
        border: `1px solid ${TOKEN.surfaceBorder}`,
        borderRadius: 12,
        padding: isMobile ? '12px 14px' : '14px 18px',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6, flexWrap: 'wrap' }}>
          {isMobile && (
            <span style={{ color: TOKEN.textMuted, fontSize: 11, fontVariantNumeric: 'tabular-nums' }}>
              {entry.date}
            </span>
          )}
          <Badge variant={tagVariant}>{tagLabel}</Badge>
        </div>
        <div style={{ color: TOKEN.text, fontSize: isMobile ? 15 : 16, fontWeight: 600, marginBottom: 5, lineHeight: 1.4 }}>
          {entry.title[lang] || entry.title.en}
        </div>
        <div style={{ color: TOKEN.textSecondary, fontSize: 13, lineHeight: 1.7 }}>
          {entry.summary[lang] || entry.summary.en}
        </div>
      </div>
    </div>
  );
};

Object.assign(window, { ReleaseLogPage });
