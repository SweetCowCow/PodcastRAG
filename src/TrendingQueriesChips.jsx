// TrendingQueriesChips — landing-and-mode-orchestration-redesign decision 4,
// extended by `per-show-mode-example-prompts` with a cold-start fallback.
//
// Chip-source precedence (per mode):
//   1. `GET /shows/{showId}/trending-queries?days=7` — if it returns ≥3 entries,
//      render those as「熱搜 / Trending」chips.
//   2. otherwise `GET /shows/{showId}/example-prompts` — render that mode's
//      LLM-pre-generated examples as「範例 / Examples」chips.
//   3. if neither yields entries, render NOTHING (silent no-op).
// Clicking any chip calls onSelect(text), which the host wires to populate +
// run the query for the current mode.
//
// `mode` is one of 'index' | 'semantic' | 'chat'. Without it, only trending is
// attempted (back-compat).

// `hideLabel`: 呼叫端已自帶區塊標題(如手機對話 dock 的「範例」收合開關)時,
// 隱藏內建的「範例/熱搜」小標籤避免重複。
const TrendingQueriesChips = ({ showId, lang, onSelect, layout, mode, hideLabel }) => {
  const t = lang === 'zh';
  // null = loading; otherwise { kind: 'trending'|'example', items: string[] }
  const [chips, setChips] = React.useState(null);

  React.useEffect(() => {
    if (!showId) return;
    let cancelled = false;
    (async () => {
      // 1. trending — needs ≥3 to win the slot.
      let trending = [];
      try {
        const res = await apiFetch(`/shows/${showId}/trending-queries?days=7`);
        if (res.ok) {
          const data = await res.json();
          trending = Array.isArray(data.queries) ? data.queries : [];
        }
      } catch (_) { /* silent */ }
      if (cancelled) return;
      if (trending.length >= 3) {
        setChips({ kind: 'trending', items: trending.slice(0, 5).map(q => q.query_text).filter(Boolean) });
        return;
      }
      // 2. cold-start fallback — this mode's pre-generated examples.
      let examples = [];
      if (mode) {
        try {
          const res = await apiFetch(`/shows/${showId}/example-prompts`);
          if (res.ok) {
            const data = await res.json();
            examples = Array.isArray(data[mode]) ? data[mode] : [];
          }
        } catch (_) { /* silent */ }
      }
      if (cancelled) return;
      if (examples.length) {
        setChips({ kind: 'example', items: examples.slice(0, 5).filter(Boolean) });
        return;
      }
      // 3. nothing to show.
      setChips({ kind: 'none', items: [] });
    })();
    return () => { cancelled = true; };
  }, [showId, mode]);

  if (!chips || chips.items.length === 0) return null;

  const horizontal = layout !== 'vertical';
  const label = chips.kind === 'example'
    ? uiString('chip_examples_label', lang)
    : (t ? '熱搜' : 'Trending');

  return (
    <div
      data-testid="trending-queries-chips"
      data-chip-kind={chips.kind}
      style={{
        display: 'flex',
        flexWrap: 'wrap',
        gap: 6,
        alignItems: 'center',
        flexDirection: horizontal ? 'row' : 'column',
      }}
    >
      {!hideLabel && (
        <span style={{ color: TOKEN.textMuted, fontSize: 11, marginRight: 4 }}>
          {label}
        </span>
      )}
      {chips.items.map((text, i) => (
        <button
          key={i}
          type="button"
          onClick={() => onSelect && onSelect(text)}
          data-testid={chips.kind === 'example' ? 'example-chip' : 'trending-chip'}
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
          {text}
        </button>
      ))}
    </div>
  );
};

Object.assign(window, { TrendingQueriesChips });
