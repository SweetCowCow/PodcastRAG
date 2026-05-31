// KeywordResults — index (keyword) mode sectioned results.
//
// Part of change `keyword-index-mode`. Renders up to three vertically stacked
// sections from the POST /shows/{id}/keyword-search response:
//   T1 (chunk-and)   — chunks where every term matches in the same chunk
//   T2 (episode-and) — episodes where every term matches across pools
//   T3 (or-fallback)  — loose OR hits, only when T1 + T2 are both empty
// plus a bottom mode-switcher chip (always) and a zero-result empty state.
//
// Matched terms are highlighted in two rotating colors keyed by term order:
// even index → orange (solid underline), odd index → cyan (dashed underline).

const KW_COLORS = ['#f97316', '#06b6d4']; // [even=orange, odd=cyan]
const KW_HARD_CAP = 100;
const KW_PAGE_STEP = 5;

function _kwFmtTime(sec) {
  const s = Math.max(0, Math.floor(Number(sec) || 0));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${String(r).padStart(2, '0')}`;
}

// Highlight every occurrence of each term in `text`. Color is deterministic by
// the term's index in `terms` (even=orange solid, odd=cyan dashed) so the same
// term always renders the same color within one render. Returns a React node
// array (safe — no dangerouslySetInnerHTML).
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
    const color = KW_COLORS[idx % 2];
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

// Split a chunk into sentences and return the 3 sentences around the first
// hit (one before + hit + one after). Falls back to the whole text for short
// chunks. Used for the T1 default (collapsed) preview.
function _kwSentencePreview(text, terms) {
  const value = text == null ? '' : String(text);
  const sentences = value.split(/(?<=[。！？!?.])\s*/).filter((s) => s.trim());
  if (sentences.length <= 3) return value;
  let hit = 0;
  for (let i = 0; i < sentences.length; i++) {
    const low = sentences[i].toLowerCase();
    if ((terms || []).some((tm) => tm && low.includes(tm.toLowerCase()))) {
      hit = i;
      break;
    }
  }
  const start = Math.max(0, hit - 1);
  return sentences.slice(start, Math.min(sentences.length, hit + 2)).join('');
}

const _kwSectionHeader = (label, count, unit) => (
  <div
    style={{
      display: 'flex',
      alignItems: 'baseline',
      gap: 8,
      margin: '4px 0 10px',
    }}
  >
    <span style={{ color: TOKEN.text, fontSize: 14, fontWeight: 700 }}>{label}</span>
    <span style={{ color: TOKEN.textMuted, fontSize: 12 }}>
      {count} {unit}
    </span>
  </div>
);

// ─── T1 chunk card ──────────────────────────────────────────────────────────
const T1ChunkCard = ({ hit, terms, lang, onJumpTo }) => {
  const t = lang === 'zh';
  const [expanded, setExpanded] = React.useState(false);
  const preview = expanded ? hit.text : _kwSentencePreview(hit.text, terms);
  const hasMore = preview !== hit.text;
  return (
    <div
      style={{
        background: TOKEN.surface,
        border: `1px solid ${TOKEN.surfaceBorder}`,
        borderRadius: 10,
        padding: '14px 16px',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          marginBottom: 8,
          flexWrap: 'wrap',
        }}
      >
        <span
          style={{
            color: TOKEN.textSecondary,
            fontSize: 12,
            flex: 1,
            minWidth: 0,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {hit.episode_title}
        </span>
        <span
          style={{
            color: TOKEN.textMuted,
            fontSize: 12,
            display: 'flex',
            alignItems: 'center',
            gap: 3,
            flexShrink: 0,
          }}
        >
          <Icon name="clock" size={11} /> {_kwFmtTime(hit.start_time)}
        </span>
      </div>
      <p style={{ margin: 0, color: TOKEN.text, fontSize: 13, lineHeight: 1.7 }}>
        {highlightTerms(preview, terms)}
      </p>
      <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
        {(hasMore || expanded) && (
          <Btn variant="ghost" size="sm" onClick={() => setExpanded((v) => !v)}>
            {expanded ? (t ? '收合' : 'Collapse') : t ? '展開上下文' : 'Show context'}
          </Btn>
        )}
        <Btn variant="secondary" size="sm" icon="play" onClick={() => onJumpTo && onJumpTo(hit)}>
          {t ? '跳播' : 'Jump'}
        </Btn>
      </div>
    </div>
  );
};

// ─── T2 episode card ────────────────────────────────────────────────────────
// Inline expand fetches the episode's matching segments via `onExpand` and
// lists them in-place (no navigation away from the results page).
const T2EpisodeCard = ({ item, terms, lang, onExpand }) => {
  const t = lang === 'zh';
  const pc = item.pool_counts || { title: 0, description: 0, transcript: 0 };
  const [open, setOpen] = React.useState(false);
  const [segs, setSegs] = React.useState(null); // null = not yet fetched
  const [loading, setLoading] = React.useState(false);

  const toggle = async () => {
    if (open) {
      setOpen(false);
      return;
    }
    setOpen(true);
    if (segs === null && onExpand) {
      setLoading(true);
      try {
        const fetched = await onExpand(item.episode_id);
        setSegs(fetched || []);
      } catch (_) {
        setSegs([]);
      } finally {
        setLoading(false);
      }
    }
  };

  return (
    <div
      style={{
        background: TOKEN.surface,
        border: `1px solid ${TOKEN.surfaceBorder}`,
        borderRadius: 10,
        padding: '12px 16px',
      }}
    >
      <div
        style={{
          color: TOKEN.text,
          fontSize: 13,
          fontWeight: 600,
          marginBottom: 6,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
      >
        {item.episode_title}
      </div>
      <div style={{ color: TOKEN.textSecondary, fontSize: 12, marginBottom: 8 }}>
        {t ? '命中分佈：' : 'Hits: '}
        {t ? '標題' : 'Title'} {pc.title} · {t ? '描述' : 'Desc'} {pc.description} ·{' '}
        {t ? '逐字稿' : 'Transcript'} {pc.transcript}
      </div>
      <Btn variant="ghost" size="sm" onClick={toggle}>
        {open ? (t ? '收合' : 'Collapse') : t ? '展開查看各段' : 'View segments'}
      </Btn>
      {open && (
        <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
          {loading && (
            <div style={{ color: TOKEN.textMuted, fontSize: 12 }}>
              {t ? '載入中…' : 'Loading…'}
            </div>
          )}
          {!loading && segs && segs.length === 0 && (
            <div style={{ color: TOKEN.textMuted, fontSize: 12 }}>
              {t ? '（此集無可顯示的命中段落）' : '(no matching segments to show)'}
            </div>
          )}
          {!loading &&
            (segs || []).map((s, i) => (
              <div
                key={i}
                style={{
                  background: TOKEN.surfaceRaised,
                  borderRadius: 6,
                  padding: '7px 10px',
                  fontSize: 12,
                  color: TOKEN.text,
                  lineHeight: 1.6,
                }}
              >
                <span style={{ color: TOKEN.textMuted, marginRight: 6 }}>
                  {_kwFmtTime(s.start_time)}
                </span>
                {highlightTerms(s.text, terms)}
              </div>
            ))}
        </div>
      )}
    </div>
  );
};

// ─── T2 collapsed chip ──────────────────────────────────────────────────────
const T2CollapsedChip = ({ total, lang, children }) => {
  const t = lang === 'zh';
  const [open, setOpen] = React.useState(false);
  if (open) return children;
  return (
    <button
      onClick={() => setOpen(true)}
      style={{
        background: TOKEN.surfaceRaised,
        border: `1px solid ${TOKEN.surfaceBorder}`,
        borderRadius: 999,
        padding: '8px 16px',
        color: TOKEN.textSecondary,
        fontSize: 13,
        cursor: 'pointer',
        fontFamily: 'inherit',
        alignSelf: 'flex-start',
      }}
    >
      {t ? `+${total} 集亦有命中` : `+${total} episodes also match`}
    </button>
  );
};

// ─── Bottom mode switcher (always visible) ──────────────────────────────────
const BottomModeSwitcher = ({ lang, onSwitchMode }) => {
  const t = lang === 'zh';
  const chip = (mode, label) => (
    <button
      onClick={() => onSwitchMode && onSwitchMode(mode)}
      style={{
        background: 'none',
        border: `1px solid ${TOKEN.surfaceBorder}`,
        borderRadius: 999,
        padding: '6px 14px',
        color: TOKEN.accent,
        fontSize: 12,
        cursor: 'pointer',
        fontFamily: 'inherit',
      }}
    >
      {label}
    </button>
  );
  return (
    <div
      style={{
        display: 'flex',
        gap: 8,
        alignItems: 'center',
        justifyContent: 'center',
        padding: '16px 0 8px',
        flexWrap: 'wrap',
      }}
    >
      <span style={{ color: TOKEN.textMuted, fontSize: 12 }}>
        {t ? '換個方式找：' : 'Try another way:'}
      </span>
      {chip('semantic', t ? '語意搜尋' : 'Semantic')}
      {chip('chat', t ? '對話查詢' : 'Chat')}
    </div>
  );
};

// ─── T3 OR fallback section ─────────────────────────────────────────────────
const T3FallbackSection = ({ t3, terms, lang, onSwitchMode }) => {
  const t = lang === 'zh';
  if (!t3) return null;
  return (
    <section
      style={{
        border: `1px dashed ${TOKEN.surfaceBorder}`,
        borderRadius: 10,
        padding: '12px 14px',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8, flexWrap: 'wrap' }}>
        {_kwSectionHeader(t ? '鬆散結果' : 'Loose results', t3.total, t ? '段' : 'segments')}
        <button
          onClick={() => onSwitchMode && onSwitchMode('semantic')}
          style={{
            background: TOKEN.accentDim,
            border: `1px solid ${TOKEN.accent}`,
            borderRadius: 999,
            padding: '4px 12px',
            color: TOKEN.accent,
            fontSize: 12,
            cursor: 'pointer',
            fontFamily: 'inherit',
          }}
        >
          {t ? '改用語意搜尋' : 'Switch to semantic'}
        </button>
      </div>
      <p style={{ color: TOKEN.textMuted, fontSize: 12, margin: '0 0 10px' }}>
        {t
          ? '段內全部命中與全集命中皆無，以下為任一關鍵字的鬆散結果'
          : 'No strict matches; below are loose hits for any keyword'}
      </p>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {(t3.items || []).map((hit) => (
          <div
            key={hit.chunk_id}
            style={{
              background: TOKEN.surface,
              border: `1px solid ${TOKEN.surfaceBorder}`,
              borderRadius: 8,
              padding: '10px 12px',
            }}
          >
            <div style={{ color: TOKEN.textMuted, fontSize: 11, marginBottom: 4 }}>
              {hit.episode_title} · {_kwFmtTime(hit.start_time)}
            </div>
            <p style={{ margin: 0, color: TOKEN.text, fontSize: 12, lineHeight: 1.6 }}>
              {highlightTerms(hit.text, terms)}
            </p>
          </div>
        ))}
      </div>
    </section>
  );
};

// ─── Zero-result empty state ────────────────────────────────────────────────
const _KW_STATIC_EXAMPLES = ['馬世芳', '滅火器', '歌單'];

const KwEmptyState = ({ showId, lang, onSwitchMode, onExample }) => {
  const t = lang === 'zh';
  const [examples, setExamples] = React.useState(_KW_STATIC_EXAMPLES);
  React.useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = await apiFetch(`/shows/${showId}/trending-queries`);
        if (!res.ok) return;
        const data = await res.json();
        const qs = (data && data.queries ? data.queries : [])
          .map((q) => q.query_text)
          .filter(Boolean)
          .slice(0, 3);
        if (alive && qs.length) setExamples(qs);
      } catch (_) {
        /* keep static fallback */
      }
    })();
    return () => {
      alive = false;
    };
  }, [showId]);
  return (
    <div style={{ textAlign: 'center', padding: '40px 24px', color: TOKEN.textSecondary }}>
      <div style={{ fontSize: 34, marginBottom: 10 }}>🔎</div>
      <p style={{ margin: '0 0 16px', fontSize: 14 }}>
        {t ? '找不到符合的段落，換個關鍵字試試：' : 'No matches — try another keyword:'}
      </p>
      <div style={{ display: 'flex', gap: 8, justifyContent: 'center', flexWrap: 'wrap', marginBottom: 8 }}>
        {examples.map((q, i) => (
          <button
            key={i}
            onClick={() => onExample && onExample(q)}
            style={{
              background: TOKEN.surfaceRaised,
              border: `1px solid ${TOKEN.surfaceBorder}`,
              borderRadius: 999,
              padding: '7px 14px',
              color: TOKEN.text,
              fontSize: 13,
              cursor: 'pointer',
              fontFamily: 'inherit',
            }}
          >
            {q}
          </button>
        ))}
      </div>
      <BottomModeSwitcher lang={lang} onSwitchMode={onSwitchMode} />
    </div>
  );
};

// ─── Main ───────────────────────────────────────────────────────────────────
const KeywordResults = ({
  result,
  terms,
  showId,
  lang,
  onMoreT1,
  onMoreT2,
  onJumpTo,
  onExpandEpisode,
  onSwitchMode,
  onExample,
}) => {
  const t = lang === 'zh';
  if (!result) return null;

  const t1 = result.t1 || { total: 0, items: [] };
  const t2 = result.t2 || { total: 0, items: [], collapsed: false };
  const t3 = result.t3;
  const totalAll = (t1.total || 0) + (t2.total || 0) + (t3 ? t3.total || 0 : 0);

  if (totalAll === 0) {
    return (
      <KwEmptyState
        showId={showId}
        lang={lang}
        onSwitchMode={onSwitchMode}
        onExample={onExample}
      />
    );
  }

  const moreVisible = (loaded, total) => loaded < Math.min(total, KW_HARD_CAP);

  const t2Cards = (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {(t2.items || []).map((item) => (
        <T2EpisodeCard
          key={item.episode_id}
          item={item}
          terms={terms}
          lang={lang}
          onExpand={onExpandEpisode}
        />
      ))}
      {moreVisible((t2.items || []).length, t2.total) && (
        <Btn variant="ghost" size="sm" onClick={() => onMoreT2 && onMoreT2()}>
          {t ? '顯示更多 5 集' : 'Show 5 more episodes'}
        </Btn>
      )}
    </div>
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* T1 — same-chunk AND */}
      {t1.total > 0 && (
        <section>
          {_kwSectionHeader(t ? '段內全部命中' : 'All terms in one segment', t1.total, t ? '段' : 'segments')}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {(t1.items || []).map((hit) => (
              <T1ChunkCard key={hit.chunk_id} hit={hit} terms={terms} lang={lang} onJumpTo={onJumpTo} />
            ))}
            {moreVisible((t1.items || []).length, t1.total) && (
              <Btn variant="ghost" size="sm" onClick={() => onMoreT1 && onMoreT1()}>
                {t ? '顯示更多 5 段' : 'Show 5 more segments'}
              </Btn>
            )}
          </div>
        </section>
      )}

      {/* T2 — cross-pool episode AND */}
      {t2.total > 0 && (
        <section>
          {_kwSectionHeader(t ? '全集跨欄位命中' : 'All terms across an episode', t2.total, t ? '集' : 'episodes')}
          {t2.collapsed ? (
            <T2CollapsedChip total={t2.total} lang={lang}>
              {t2Cards}
            </T2CollapsedChip>
          ) : (
            t2Cards
          )}
        </section>
      )}

      {/* T3 — OR fallback (only present when T1+T2 empty) */}
      <T3FallbackSection t3={t3} terms={terms} lang={lang} onSwitchMode={onSwitchMode} />

      <BottomModeSwitcher lang={lang} onSwitchMode={onSwitchMode} />
    </div>
  );
};

Object.assign(window, {
  KeywordResults,
  highlightTerms,
  T1ChunkCard,
  T2EpisodeCard,
  T2CollapsedChip,
  T3FallbackSection,
  BottomModeSwitcher,
});
