// SegmentCitationCard — unified citation leaf shared across Index / Semantic / Chat modes.
//
// Part of change `unified-segment-citation-card`. Renders ONE transcript-segment
// citation: segment text (with highlight) + episode title + timestamp + optional
// AI-summary excerpt + optional relevance bar + two SEPARATE action buttons
// ("播放此段" play-in-place / "跳到逐字稿" jump-to-transcript).
//
// Load order (index.html): after Shared.jsx (needs TOKEN / Icon / Btn /
// sanitiseMarkOnly) and BEFORE the consumers (SemanticResultList /
// ConversationSourcePanel / KeywordResults / QueryPage).
//
// This file is the single canonical owner of `highlightTerms` (moved here from
// KeywordResults per design D2). Because all <script type="text/babel"> share one
// global lexical scope, KeywordResults must NOT redeclare it — it references this one.

const SCC_COLORS = ['#f97316', '#06b6d4']; // [even=orange solid, odd=cyan dashed] — keyed by term order
const CITATION_DISPLAY_CAP = 5;            // D6: per-section / per-group initial display cap

// Highlight every occurrence of each term in `text`. Color is deterministic by the
// term's index in `terms` (even=orange solid underline, odd=cyan dashed underline) so
// the same term always renders the same color within one render. Returns a React node
// array (safe — no dangerouslySetInnerHTML). Moved from KeywordResults (design D2).
function highlightTerms(text, terms) {
  const value = text == null ? '' : String(text);
  const valid = (terms || []).filter(Boolean);
  if (!value || !valid.length) return value;
  const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const pattern = new RegExp('(' + valid.map(esc).join('|') + ')', 'gi');
  const parts = value.split(pattern);
  return parts.map((part, i) => {
    if (!part) return null;
    const idx = valid.findIndex((tm) => tm.toLowerCase() === part.toLowerCase());
    if (idx === -1) return part;
    const color = SCC_COLORS[idx % 2];
    const dashed = idx % 2 === 1;
    return (
      <mark
        key={i}
        style={{
          background: color + '40',
          color: TOKEN.text,
          borderRadius: 2,
          padding: '0 1px',
          textDecoration: 'underline',
          textDecorationStyle: dashed ? 'dashed' : 'solid',
          textDecorationColor: color,
          textUnderlineOffset: 2,
        }}
      >
        {part}
      </mark>
    );
  });
}

const _sccFmtTs = (sec) => {
  if (typeof sec !== 'number' || !Number.isFinite(sec)) return '--:--';
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
};

// CJK-aware spacer: only add a latin space between context and excerpt when the
// boundary char is not already a space and not a CJK glyph (matches old SourceCard).
const _sccPad = (s, side) => {
  if (!s) return s;
  const edge = side === 'before' ? s.slice(-1) : s.slice(0, 1);
  if ((side === 'before' ? s.endsWith(' ') : s.startsWith(' ')) || /[　-鿿]/.test(edge)) return s;
  return side === 'before' ? s + ' ' : ' ' + s;
};

// ─────────────────────────────────────────────────────────────────────────────
// SegmentCitationCard
//
// props:
//   segment   { episode_id, episode_title, start_time, end_time, text,
//               before_text?, after_text?, highlights?, ai_summary_excerpt?,
//               ai_summary_full?, source?, audio_url? }
//   terms?      string[]  — non-empty → client two-color highlight (D2.1)
//   position?   number    — ordinal badge (Semantic / Chat)
//   relevance?  number    — 0..1 fill fraction for the relevance bar (Semantic); no numeric text
//   lang
//   onPlay?              (segment)=>void  — play in place; omitted/absent audio → no play button
//   onJumpToTranscript?  (segment)=>void  — navigate to transcript at start_time
// ─────────────────────────────────────────────────────────────────────────────
const SegmentCitationCard = ({ segment, terms, position, relevance, lang, onPlay, onJumpToTranscript }) => {
  const t = lang === 'zh';
  const { isMobile } = useViewport();
  const [expanded, setExpanded] = React.useState(false);
  if (!segment) return null;

  const before = segment.before_text || '';
  const after = segment.after_text || '';
  const highlights = segment.highlights || '';
  const aiSummary = segment.ai_summary_excerpt || '';
  const mainText = segment.text || '';
  const epTitle = segment.episode_title || (t ? '片段' : 'Clip');
  const ts = segment.start_time;
  const isDescription = segment.source === 'description';
  const validTerms = (terms || []).filter(Boolean);

  // D2 highlight precedence: (1) terms → two-color; (2) server highlights → single-color
  // sanitised; (3) plain text. Two-color marks carry inline styles, so they must NOT sit
  // inside `.scc-server-hl` (whose CSS is the single-color override).
  let body;
  if (validTerms.length) {
    body = (
      <p style={{ margin: 0, color: TOKEN.text, fontSize: 13, lineHeight: 1.7 }}>
        {before && <span style={{ color: TOKEN.textMuted }}>{_sccPad(before, 'before')}</span>}
        {highlightTerms(mainText, validTerms)}
        {after && <span style={{ color: TOKEN.textMuted }}>{_sccPad(after, 'after')}</span>}
      </p>
    );
  } else if (highlights) {
    body = (
      <p style={{ margin: 0, color: TOKEN.text, fontSize: 13, lineHeight: 1.65 }}>
        {before && <span style={{ color: TOKEN.textMuted }}>{_sccPad(before, 'before')}</span>}
        <span className="scc-server-hl" dangerouslySetInnerHTML={{ __html: sanitiseMarkOnly(highlights) }} />
        {after && <span style={{ color: TOKEN.textMuted }}>{_sccPad(after, 'after')}</span>}
      </p>
    );
  } else {
    body = (
      <p style={{ margin: 0, color: TOKEN.text, fontSize: 13, lineHeight: 1.65 }}>
        {before && <span style={{ color: TOKEN.textMuted }}>{_sccPad(before, 'before')}</span>}
        <span>{mainText}</span>
        {after && <span style={{ color: TOKEN.textMuted }}>{_sccPad(after, 'after')}</span>}
      </p>
    );
  }

  const showPlay = !isDescription && typeof onPlay === 'function' && !!segment.audio_url;
  const showJump = typeof onJumpToTranscript === 'function';
  const jumpLabel = isDescription ? (t ? '打開該集' : 'Open episode') : (t ? '跳到逐字稿' : 'Jump to transcript');

  // Relevance bar: caller passes a normalized 0..1 fill (top result → 1.0, bottom → ≥0.1).
  // Render a fill width only; the numeric score is never shown as text.
  const relPct = (typeof relevance === 'number' && Number.isFinite(relevance))
    ? Math.max(10, Math.min(100, Math.round(relevance * 100)))
    : null;

  return (
    <div
      className="scc-card"
      style={{
        background: TOKEN.surface,
        border: `1px solid ${TOKEN.surfaceBorder}`,
        borderRadius: 10,
        padding: isMobile ? '12px 6px' : '14px 16px',
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
      }}
    >
      {/* App.jsx sets a global `mark { background: transparent }`; restore the single-color
          highlight ONLY for server-rendered <mark> spans (scoped class), so the two-color
          term marks (inline-styled) are never overridden by this rule. */}
      <style>{`.scc-card .scc-server-hl mark { background: ${TOKEN.accent}33; color: ${TOKEN.accentHover || TOKEN.accent}; border-radius: 2px; padding: 0 2px; font-weight: 600; border-bottom: 1px solid ${TOKEN.accent}; }`}</style>

      {/* Header: optional position badge + episode title + timestamp + relevance bar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        {typeof position === 'number' && (
          <span style={{
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            minWidth: 22, height: 22, padding: '0 6px',
            background: TOKEN.accentDim, color: TOKEN.accent,
            border: `1px solid ${TOKEN.accent}55`, borderRadius: 6,
            fontSize: 11, fontWeight: 700, flexShrink: 0,
          }}>{position + 1}</span>
        )}
        <span style={{ color: TOKEN.textSecondary, fontSize: 12, flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{epTitle}</span>
        {!isDescription && typeof ts === 'number' && (
          <span style={{ color: TOKEN.textMuted, fontSize: 12, display: 'flex', alignItems: 'center', gap: 3, flexShrink: 0 }}>
            <Icon name="clock" size={11} /> {_sccFmtTs(ts)}
          </span>
        )}
        {relPct !== null && (
          <span
            role="img"
            aria-label={t ? `相關度 ${relPct}%` : `Relevance ${relPct}%`}
            title={t ? '相關度' : 'Relevance'}
            style={{ width: 48, height: 5, background: TOKEN.surfaceBorder, borderRadius: 3, overflow: 'hidden', flexShrink: 0, display: 'inline-block' }}
          >
            <span style={{ display: 'block', width: `${relPct}%`, height: '100%', background: TOKEN.accent }} />
          </span>
        )}
      </div>

      {/* Segment body */}
      {body}

      {/* Optional AI summary excerpt with show-more toggle */}
      {aiSummary && (() => {
        const aiFull = segment.ai_summary_full || '';
        const hasMore = aiFull && aiFull.length > aiSummary.replace(/…$/, '').length;
        const display = expanded && hasMore ? aiFull : aiSummary;
        return (
          <div style={{ fontSize: 12, color: TOKEN.textSecondary, lineHeight: 1.55 }}>
            <span style={{ color: TOKEN.textMuted, marginRight: 6, fontWeight: 600 }}>{t ? '本集摘要' : 'Summary'}:</span>
            <span>{display}</span>
            {hasMore && (
              <button type="button" onClick={() => setExpanded(v => !v)} style={{
                background: 'none', border: 'none', padding: 0, marginLeft: 6,
                color: TOKEN.accent, fontSize: 12, cursor: 'pointer', fontFamily: 'inherit',
              }}>
                {expanded ? (t ? '收合' : 'Show less') : (t ? '展開' : 'Show more')}
              </button>
            )}
          </div>
        );
      })()}

      {/* Two SEPARATE actions (D3): play-in-place + jump-to-transcript */}
      {(showPlay || showJump) && (
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
          {showPlay && (
            <Btn variant="secondary" size="sm" icon="play" onClick={() => onPlay(segment)}>
              {t ? '播放此段' : 'Play'}
            </Btn>
          )}
          {showJump && (
            <Btn variant="ghost" size="sm" icon={isDescription ? 'fileText' : 'chevronRight'} onClick={() => onJumpToTranscript(segment)}>
              {jumpLabel}
            </Btn>
          )}
        </div>
      )}
    </div>
  );
};

Object.assign(window, { SegmentCitationCard, highlightTerms, CITATION_DISPLAY_CAP });
