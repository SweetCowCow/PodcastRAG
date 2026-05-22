// TrendingQueriesChips — landing-and-mode-orchestration-redesign decision 4.
//
// Calls `GET /shows/{showId}/trending-queries?days=7`. Renders up to 5
// chips (count desc) inline. On failure / empty / not-yet-wired-backend,
// renders NOTHING (silent no-op — design risk-mitigation: tolerate sparse
// early data + missing endpoint).
//
// NOTE: the trending-queries endpoint is delivered by the backend portion
// of this change (`trending-queries-api`). Per worktree instructions the
// backend implementation is a carry-over to the main thread — until then
// this component logs a debug line on 404 and renders nothing. Once the
// endpoint exists it will start surfacing chips automatically.

const TrendingQueriesChips = ({ showId, lang, onSelect, layout }) => {
  const t = lang === 'zh';
  const [queries, setQueries] = React.useState(null);   // null = loading, [] = empty
  React.useEffect(() => {
    if (!showId) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await apiFetch(`/shows/${showId}/trending-queries?days=7`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (cancelled) return;
        const list = Array.isArray(data.queries) ? data.queries : [];
        // Already sorted desc by backend; defensive cap at 5.
        setQueries(list.slice(0, 5));
      } catch (_) {
        // Silent failure — no error UI per design (decision 4 failure mode).
        if (!cancelled) setQueries([]);
      }
    })();
    return () => { cancelled = true; };
  }, [showId]);

  if (!queries || queries.length === 0) return null;

  const horizontal = layout !== 'vertical';
  return (
    <div
      data-testid="trending-queries-chips"
      style={{
        display: 'flex',
        flexWrap: 'wrap',
        gap: 6,
        alignItems: 'center',
        flexDirection: horizontal ? 'row' : 'column',
      }}
    >
      <span style={{ color: TOKEN.textMuted, fontSize: 11, marginRight: 4 }}>
        {t ? '熱搜' : 'Trending'}
      </span>
      {queries.map((q, i) => (
        <button
          key={i}
          type="button"
          onClick={() => onSelect && onSelect(q.query_text)}
          data-testid="trending-chip"
          style={{
            padding: '3px 10px',
            background: TOKEN.bg,
            border: `1px solid ${TOKEN.surfaceBorder}`,
            borderRadius: 99,
            color: TOKEN.accent,
            fontSize: 12,
            cursor: 'pointer',
            fontFamily: 'inherit',
            transition: 'border-color 0.12s',
          }}
          onMouseEnter={e => (e.currentTarget.style.borderColor = TOKEN.accent)}
          onMouseLeave={e => (e.currentTarget.style.borderColor = TOKEN.surfaceBorder)}
        >
          {q.query_text}
        </button>
      ))}
    </div>
  );
};

Object.assign(window, { TrendingQueriesChips });
