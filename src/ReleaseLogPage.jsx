// ReleaseLogPage — user-facing changelog grouped by milestone (newest first).
// Reads window.RELEASE_LOG / TAG_LABELS / MILESTONE_LABELS from src/releaseLog.jsx.

const TAG_VARIANT = {
  feature: 'success',
  fix: 'warning',
  enhancement: 'default',
  ui: 'muted',
};

// Milestone version order, newest first.
const MILESTONE_ORDER = ['v0.4', 'v0.3', 'v0.2', 'v0.1'];

const ReleaseLogPage = ({ lang }) => {
  const t = lang === 'zh';
  const { isMobile } = useViewport();

  // Group entries by milestone. Entries inside a milestone are sorted by date DESC.
  const groups = MILESTONE_ORDER.map(m => ({
    milestone: m,
    label: MILESTONE_LABELS[m] ? MILESTONE_LABELS[m][lang] : m,
    entries: RELEASE_LOG
      .filter(e => e.milestone === m)
      .slice()
      .sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0)),
  })).filter(g => g.entries.length > 0);

  return (
    <div style={{ flex: 1, overflow: 'auto', padding: isMobile ? '24px 16px 48px' : '40px 28px 64px' }}>
      <div style={{ maxWidth: 880, margin: '0 auto' }}>
        {/* Header */}
        <div style={{ marginBottom: 32 }}>
          <h1 style={{ color: TOKEN.text, fontSize: isMobile ? 24 : 30, fontWeight: 700, margin: '0 0 8px' }}>
            {t ? '更新日誌' : 'Release Log'}
          </h1>
          <p style={{ color: TOKEN.textSecondary, fontSize: 14, margin: 0, lineHeight: 1.6 }}>
            {t
              ? 'PodcastRAG 一路長出來的功能,依里程碑由新到舊排列。'
              : "What PodcastRAG has grown into, milestone by milestone (newest first)."}
          </p>
        </div>

        {/* Milestones */}
        {groups.map(group => (
          <div key={group.milestone} style={{ marginBottom: 36 }}>
            {/* Milestone heading */}
            <div style={{
              display: 'flex', alignItems: 'baseline', gap: 12,
              paddingBottom: 10, marginBottom: 16,
              borderBottom: `1px solid ${TOKEN.surfaceBorder}`,
            }}>
              <h2 style={{ color: TOKEN.accent, fontSize: isMobile ? 17 : 19, fontWeight: 700, margin: 0, letterSpacing: '0.01em' }}>
                {group.label}
              </h2>
              <span style={{ color: TOKEN.textMuted, fontSize: 12 }}>
                {group.entries.length} {t ? '項更新' : (group.entries.length === 1 ? 'update' : 'updates')}
              </span>
            </div>

            {/* Entries */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {group.entries.map(entry => {
                const tagLabel = TAG_LABELS[entry.tag] ? TAG_LABELS[entry.tag][lang] : entry.tag;
                const tagVariant = TAG_VARIANT[entry.tag] || 'default';
                return (
                  <div key={entry.slug} style={{
                    background: TOKEN.surface,
                    border: `1px solid ${TOKEN.surfaceBorder}`,
                    borderRadius: 12,
                    padding: isMobile ? '14px 14px' : '16px 18px',
                  }}>
                    {/* Top row: date + tag */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8, flexWrap: 'wrap' }}>
                      <span style={{ color: TOKEN.textMuted, fontSize: 12, fontVariantNumeric: 'tabular-nums' }}>
                        {entry.date}
                      </span>
                      <Badge variant={tagVariant}>{tagLabel}</Badge>
                    </div>
                    {/* Title */}
                    <div style={{ color: TOKEN.text, fontSize: isMobile ? 15 : 16, fontWeight: 600, marginBottom: 6, lineHeight: 1.4 }}>
                      {entry.title[lang] || entry.title.en}
                    </div>
                    {/* Summary */}
                    <div style={{ color: TOKEN.textSecondary, fontSize: 13, lineHeight: 1.7 }}>
                      {entry.summary[lang] || entry.summary.en}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ))}

        {/* Empty fallback (shouldn't trigger with seeded data, but safe) */}
        {groups.length === 0 && (
          <div style={{ textAlign: 'center', padding: '60px 0', color: TOKEN.textMuted }}>
            {t ? '尚無更新紀錄' : 'No release entries yet'}
          </div>
        )}
      </div>
    </div>
  );
};

Object.assign(window, { ReleaseLogPage });
