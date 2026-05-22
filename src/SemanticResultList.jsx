// SemanticResultList — landing-and-mode-orchestration-redesign decision 8.
//
// Hybrid C rendering for the Semantic tab:
//   (a) Flat list ranked by backend RRF score order.
//   (b) When an episode has K>1 chunks in the result set, show ONLY the
//       highest-ranked one with a「+{K-1} 同集」chip; clicking the chip
//       expands the rest in original-RRF order immediately below the lead card.
//   (c) Each card shows a relevance bar on the right, linearly mapped from
//       its rank (rank 0 → 100%, last → 10%). NO raw RRF score text is shown.
//
// Props:
//   results : RRF-ordered chunk hits (same shape SourceCard consumes)
//   lang
//   onJump  : (citation, position) → opens TranscriptPage

const _relevancePct = (rank, total) => {
  if (total <= 1) return 100;
  const minPct = 10;
  const span = 100 - minPct;
  return Math.round(100 - (rank / (total - 1)) * span);
};

const SemanticResultList = ({ results, lang, onJump }) => {
  const t = lang === 'zh';
  const list = Array.isArray(results) ? results : [];
  const [expanded, setExpanded] = React.useState({});  // episode_id → bool

  if (list.length === 0) return null;

  // Build per-episode groups while keeping each item's original RRF rank.
  const orderEpisode = [];
  const groups = {};
  list.forEach((r, rank) => {
    const epKey = r.episode_id != null ? String(r.episode_id) : `__noep_${rank}`;
    if (!groups[epKey]) {
      groups[epKey] = { epId: r.episode_id, epTitle: r.episode_title, items: [] };
      orderEpisode.push(epKey);
    }
    groups[epKey].items.push({ ...r, _rank: rank });
  });

  return (
    <div
      data-testid="semantic-result-list"
      style={{ display: 'flex', flexDirection: 'column', gap: 10 }}
    >
      {orderEpisode.map(epKey => {
        const g = groups[epKey];
        const lead = g.items[0];
        const rest = g.items.slice(1);
        const isExpanded = !!expanded[epKey];
        const leadPct = _relevancePct(lead._rank, list.length);
        return (
          <div key={epKey} style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <div style={{ display: 'flex', gap: 10, alignItems: 'stretch' }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <SourceCard
                  source={lead}
                  lang={lang}
                  position={lead._rank}
                  onJump={(src) => onJump && onJump(src, lead._rank)}
                />
              </div>
              <div
                data-testid="semantic-relevance-bar"
                aria-label={`relevance ${leadPct}%`}
                style={{
                  width: 6,
                  borderRadius: 3,
                  background: TOKEN.surfaceBorder,
                  position: 'relative',
                  overflow: 'hidden',
                }}
              >
                <div style={{
                  position: 'absolute',
                  left: 0, right: 0, bottom: 0,
                  height: `${leadPct}%`,
                  background: TOKEN.accent,
                  borderRadius: 3,
                }} />
              </div>
            </div>
            {rest.length > 0 && (
              <div style={{ display: 'flex', justifyContent: 'flex-start' }}>
                <button
                  type="button"
                  onClick={() => setExpanded(s => ({ ...s, [epKey]: !isExpanded }))}
                  data-testid="semantic-same-episode-chip"
                  style={{
                    padding: '3px 10px',
                    background: TOKEN.bg,
                    border: `1px dashed ${TOKEN.surfaceBorder}`,
                    borderRadius: 99,
                    color: TOKEN.accent,
                    fontSize: 11,
                    cursor: 'pointer',
                    fontFamily: 'inherit',
                  }}
                >
                  {isExpanded
                    ? (t ? `收合（${rest.length} 段）` : `Collapse (${rest.length})`)
                    : (t ? `+${rest.length} 同集` : `+${rest.length} in same episode`)}
                </button>
              </div>
            )}
            {isExpanded && rest.map(item => {
              const pct = _relevancePct(item._rank, list.length);
              return (
                <div key={item._rank} style={{ display: 'flex', gap: 10, alignItems: 'stretch', marginLeft: 16 }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <SourceCard
                      source={item}
                      lang={lang}
                      position={item._rank}
                      onJump={(src) => onJump && onJump(src, item._rank)}
                    />
                  </div>
                  <div
                    aria-label={`relevance ${pct}%`}
                    style={{
                      width: 6,
                      borderRadius: 3,
                      background: TOKEN.surfaceBorder,
                      position: 'relative',
                      overflow: 'hidden',
                    }}
                  >
                    <div style={{
                      position: 'absolute',
                      left: 0, right: 0, bottom: 0,
                      height: `${pct}%`,
                      background: TOKEN.accent,
                      borderRadius: 3,
                    }} />
                  </div>
                </div>
              );
            })}
          </div>
        );
      })}
    </div>
  );
};

Object.assign(window, { SemanticResultList });
