// ConversationSourcePanel — landing-and-mode-orchestration-redesign decision 5,
// updated by `unified-segment-citation-card` (leaf is now SegmentCitationCard,
// per-group display cap + show-more, separate play / jump actions).
//
// Renders ONE episode-grouped panel below a chat answer:
//   header  →「答案參考來源（共 N 集 · M 段引用）」(zh) /
//             "Answer sources (N episodes · M citations)" (en)
//   groups  → per-episode collapsible block; within each, at most
//             CITATION_DISPLAY_CAP cards render initially with a「顯示更多」
//             affordance to reveal the rest incrementally.
//   leaf    → SegmentCitationCard (play-in-place + jump-to-transcript).
//
// The panel shows ONLY the chunks actually cited by the answer (`citations`);
// the displayed count is decoupled from retrieval top_k (D6).
//
// Props:
//   citations          : cited chunks (ChunkHit shape; audio_url enriched here
//                        via audioUrlFor so the play button can render)
//   lang
//   queryId            : forwarded into the citation_click beacon on jump
//   audioUrlFor        : (episode_id) → audio_url | null  (from QueryPage episodes)
//   onPlaySegment      : (segment) → play in place, no navigation
//   onJumpToTranscript : (segment, position?, queryId?) → beacon + navigate

const ConversationSourcePanel = ({ citations, lang, queryId, audioUrlFor, onPlaySegment, onJumpToTranscript }) => {
  const t = lang === 'zh';
  const { isMobile } = useViewport();
  const list = Array.isArray(citations) ? citations : [];
  const [collapsed, setCollapsed] = React.useState({});  // episode_id → bool
  const [shownMap, setShownMap] = React.useState({});     // episode_id → number shown
  const CAP = (typeof window !== 'undefined' && window.CITATION_DISPLAY_CAP) || 5;

  if (list.length === 0) return null;

  // Group preserving first-appearance order so RRF ranking shines through.
  const order = [];
  const groups = {};
  let globalIdx = 0;
  for (const c of list) {
    const epId = c.episode_id != null ? String(c.episode_id) : `__noep_${globalIdx}`;
    if (!groups[epId]) {
      groups[epId] = { episode_id: c.episode_id, episode_title: c.episode_title, items: [] };
      order.push(epId);
    }
    groups[epId].items.push({ ...c, _globalIdx: globalIdx });
    globalIdx += 1;
  }
  const N = order.length;
  const M = list.length;
  const header = t
    ? `答案參考來源（共 ${N} 集 · ${M} 段引用）`
    : `Answer sources (${N} episode${N === 1 ? '' : 's'} · ${M} citation${M === 1 ? '' : 's'})`;

  return (
    <div
      data-testid="conversation-source-panel"
      style={{
        marginTop: 12,
        background: TOKEN.bg,
        border: `1px solid ${TOKEN.surfaceBorder}`,
        borderRadius: 10,
        padding: isMobile ? '10px 6px' : '12px 14px',
        display: 'flex',
        flexDirection: 'column',
        gap: 10,
      }}
    >
      <div
        style={{ fontSize: 12, fontWeight: 600, color: TOKEN.textSecondary, letterSpacing: '0.02em' }}
        data-testid="conversation-source-panel-header"
      >
        {header}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {order.map(epId => {
          const g = groups[epId];
          const isCollapsed = !!collapsed[epId];
          const shown = shownMap[epId] || CAP;
          const visible = g.items.slice(0, shown);
          const hasMore = g.items.length > shown;
          return (
            <div
              key={epId}
              data-testid="conversation-source-group"
              style={{ border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 8, background: TOKEN.surface }}
            >
              <button
                type="button"
                onClick={() => setCollapsed(s => ({ ...s, [epId]: !isCollapsed }))}
                style={{
                  width: '100%', padding: '8px 12px', background: 'transparent', border: 'none',
                  display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontFamily: 'inherit',
                  color: TOKEN.text, fontSize: 13, fontWeight: 600, textAlign: 'left',
                }}
              >
                <Icon name={isCollapsed ? 'chevronRight' : 'chevronDown'} size={12} color={TOKEN.textMuted} />
                <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {g.episode_title || (t ? '未命名集數' : 'Untitled episode')}
                </span>
                <span style={{ color: TOKEN.textMuted, fontSize: 11, fontWeight: 400 }}>
                  {g.items.length} {t ? '段' : 'clip' + (g.items.length === 1 ? '' : 's')}
                </span>
              </button>
              {!isCollapsed && (
                <div style={{ padding: isMobile ? '0 6px 8px' : '0 10px 10px', display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {visible.map((c) => {
                    const segment = { ...c, audio_url: c.audio_url || (audioUrlFor ? audioUrlFor(c.episode_id) : null) };
                    return (
                      <SegmentCitationCard
                        key={c._globalIdx}
                        segment={segment}
                        lang={lang}
                        position={c._globalIdx}
                        onPlay={onPlaySegment}
                        onJumpToTranscript={(seg) => onJumpToTranscript && onJumpToTranscript(seg, c._globalIdx, queryId)}
                      />
                    );
                  })}
                  {hasMore && (
                    <Btn variant="ghost" size="sm" onClick={() => setShownMap(s => ({ ...s, [epId]: shown + CAP }))}>
                      {t ? `顯示更多（剩 ${g.items.length - shown}）` : `Show more (${g.items.length - shown} left)`}
                    </Btn>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};

Object.assign(window, { ConversationSourcePanel });
