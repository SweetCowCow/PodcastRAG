// SemanticResultList — landing-and-mode-orchestration-redesign decision 8,
// updated by `unified-segment-citation-card` (leaf is now SegmentCitationCard).
//
// Hybrid C rendering for the Semantic tab:
//   (a) Flat list ranked by backend RRF score order.
//   (b) When an episode has K>1 chunks in the result set, show ONLY the
//       highest-ranked one with a「+{K-1} 同集」chip; clicking the chip
//       expands the rest in original-RRF order immediately below the lead card.
//   (c) Relevance is now rendered INSIDE the shared SegmentCitationCard via its
//       `relevance` prop (0..1), linearly mapped from rank (rank 0 → 1.0, last →
//       0.1). NO raw RRF score text is shown.
//
// Props:
//   results            : RRF-ordered chunk hits (ChunkHit shape; audio_url enriched
//                        by the QueryPage call site so the play button can render)
//   lang
//   onPlaySegment      : (segment) → play in place (sticky player), no navigation
//   onJumpToTranscript : (segment) → navigate to TranscriptPage at start_time

const _relevanceFrac = (rank, total) => {
  if (total <= 1) return 1;
  const min = 0.1;
  return Math.max(min, 1 - (rank / (total - 1)) * (1 - min));
};

// semantic-topk-bump-and-show-more: with the Semantic tab now over-fetching k=25,
// cap how many episode-groups render initially and reveal more client-side (no new
// API call) — semantic-specific display constants.
const SEM_INITIAL_GROUPS = 10;
const SEM_GROUP_STEP = 5;

const SemanticResultList = ({ results, lang, onPlaySegment, onJumpToTranscript }) => {
  const t = lang === 'zh';
  const list = Array.isArray(results) ? results : [];
  const [expanded, setExpanded] = React.useState({});  // episode_id → bool
  const [shownGroups, setShownGroups] = React.useState(SEM_INITIAL_GROUPS);

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

  const renderCard = (item) => (
    <SegmentCitationCard
      segment={item}
      lang={lang}
      position={item._rank}
      relevance={_relevanceFrac(item._rank, list.length)}
      onPlay={onPlaySegment}
      onJumpToTranscript={(seg) => onJumpToTranscript && onJumpToTranscript(seg)}
    />
  );

  return (
    <div
      data-testid="semantic-result-list"
      style={{ display: 'flex', flexDirection: 'column', gap: 10 }}
    >
      {orderEpisode.slice(0, shownGroups).map(epKey => {
        const g = groups[epKey];
        const lead = g.items[0];
        const rest = g.items.slice(1);
        const isExpanded = !!expanded[epKey];
        return (
          <div key={epKey} style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {renderCard(lead)}
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
            {isExpanded && rest.map(item => (
              <div key={item._rank} style={{ marginLeft: 16 }}>
                {renderCard(item)}
              </div>
            ))}
          </div>
        );
      })}
      {orderEpisode.length > shownGroups && (
        <button
          type="button"
          data-testid="semantic-show-more"
          onClick={() => setShownGroups(n => n + SEM_GROUP_STEP)}
          style={{
            alignSelf: 'center',
            marginTop: 4,
            padding: '6px 16px',
            background: TOKEN.accentDim,
            border: `1px solid ${TOKEN.accent}55`,
            borderRadius: 8,
            color: TOKEN.accent,
            fontSize: 13,
            cursor: 'pointer',
            fontFamily: 'inherit',
          }}
        >
          {t
            ? `顯示更多（還有 ${orderEpisode.length - shownGroups} 集）`
            : `Show more (${orderEpisode.length - shownGroups} more)`}
        </button>
      )}
    </div>
  );
};

Object.assign(window, { SemanticResultList });
