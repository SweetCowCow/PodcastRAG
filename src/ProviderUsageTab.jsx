// ProviderUsageTab — admin tab for multi-provider usage observability.
//
// Wired into AdminPage.jsx at page route `admin-provider-usage`. Polls
// `/admin/provider-usage/monthly` + `/daily` every 60 s and renders:
//
//   1. Threshold banners (yellow ≥ 80 %, red ≥ 95 %) per provider.
//      Red banner contains external links to Zeabur AI Hub / OpenAI
//      dashboard — there is NO auto-recharge button (Non-Goal).
//   2. Per-provider summary card: budget, accumulated spend, ratio bar,
//      top 3 models for the month.
//   3. 30-day stacked SVG bar chart, x = date (Asia/Taipei converted),
//      y = USD spend, hover tooltip with per-provider breakdown.
//
// Chart is hand-drawn `<rect>` SVG — NO chart library (decision in
// design.md: keep CDN footprint minimal).

const PROVIDER_USAGE_COLORS = {
  aihub: '#22d3ee',
  openai: '#22c55e',
  // Fallback palette for future providers — picked deterministically by index.
  _fallback: ['#f59e0b', '#ec4899', '#a855f7', '#10b981', '#fb923c'],
};
const _colorForProvider = (name, index = 0) => {
  if (PROVIDER_USAGE_COLORS[name]) return PROVIDER_USAGE_COLORS[name];
  const pool = PROVIDER_USAGE_COLORS._fallback;
  return pool[index % pool.length];
};

const PROVIDER_DASHBOARD_LINKS = {
  aihub: 'https://dash.zeabur.com/',
  openai: 'https://platform.openai.com/usage',
};

const ProviderUsageTab = ({ lang }) => {
  const t = lang === 'zh';
  const [monthly, setMonthly] = React.useState(null);
  const [daily, setDaily] = React.useState(null);
  const [error, setError] = React.useState(null);
  const [hoverDay, setHoverDay] = React.useState(null); // {date, providers: {p: spend}}

  const reload = React.useCallback(async () => {
    setError(null);
    try {
      const [m, d] = await Promise.all([
        apiFetch('/admin/provider-usage/monthly'),
        apiFetch('/admin/provider-usage/daily'),
      ]);
      if (!m.ok) throw new Error(`monthly HTTP ${m.status}`);
      if (!d.ok) throw new Error(`daily HTTP ${d.status}`);
      setMonthly(await m.json());
      setDaily(await d.json());
    } catch (err) {
      setError(err.message);
    }
  }, []);

  React.useEffect(() => {
    reload();
    const id = setInterval(reload, 60_000);
    return () => clearInterval(id);
  }, [reload]);

  if (error) {
    return (
      <div style={{ padding: 20, color: TOKEN.danger }}>
        {(t ? '載入失敗：' : 'Load failed: ') + error}
      </div>
    );
  }
  if (!monthly || !daily) {
    return (
      <div style={{ padding: 20, color: TOKEN.textMuted }}>
        {t ? '載入中…' : 'Loading…'}
      </div>
    );
  }

  // ── Build banners ──
  const banners = [];
  Object.entries(monthly).forEach(([provider, info]) => {
    const ratio = info.ratio || 0;
    if (ratio >= 0.95) {
      banners.push({ severity: 'red', provider, ratio, info });
    } else if (ratio >= 0.80) {
      banners.push({ severity: 'yellow', provider, ratio, info });
    }
  });

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <p style={{ margin: 0, color: TOKEN.textSecondary, fontSize: 14 }}>
        {t
          ? 'Zeabur AI Hub 與 OpenAI direct 的當月用量。每 60 秒自動更新。資料來源為 hourly Beat task，可能落後 1 小時。'
          : 'Current-month usage for Zeabur AI Hub and OpenAI direct. Auto-refreshes every 60 s. Data is collected hourly by a Beat task and may lag by up to 1 h.'}
      </p>

      {/* Banners */}
      {banners.map(b => (
        <UsageBanner key={`${b.provider}-${b.severity}`} lang={lang}
          severity={b.severity} provider={b.provider} ratio={b.ratio} info={b.info} />
      ))}

      {/* Per-provider summary cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 16 }}>
        {Object.entries(monthly).map(([provider, info], idx) => (
          <ProviderSummaryCard key={provider} lang={lang}
            provider={provider} info={info} color={_colorForProvider(provider, idx)} />
        ))}
      </div>

      {/* 30-day stacked SVG bar chart */}
      <ProviderUsageChart lang={lang} daily={daily} monthly={monthly}
        onHoverDay={setHoverDay} hoverDay={hoverDay} />
    </div>
  );
};

const UsageBanner = ({ lang, severity, provider, ratio, info }) => {
  const t = lang === 'zh';
  const isRed = severity === 'red';
  const bg = isRed ? 'rgba(239,68,68,0.15)' : 'rgba(245,158,11,0.15)';
  const border = isRed ? TOKEN.danger : TOKEN.warning;
  const color = isRed ? '#fca5a5' : '#fbbf24';
  const ratioPct = (ratio * 100).toFixed(1);
  const link = PROVIDER_DASHBOARD_LINKS[provider];
  return (
    <div style={{ background: bg, border: `1px solid ${border}`, borderRadius: 10, padding: '14px 16px', color }}>
      <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 4 }}>
        {isRed
          ? (t ? `${provider} 用量已達 ${ratioPct}% — 請立即至 ${provider === 'openai' ? 'OpenAI dashboard' : 'Zeabur AI Hub'} 充值，否則服務將中斷` :
              `${provider} usage at ${ratioPct}% — please top up immediately at ${provider === 'openai' ? 'OpenAI dashboard' : 'Zeabur AI Hub'}, otherwise service will be interrupted`)
          : (t ? `${provider} 用量已達 ${ratioPct}%（$${info.accumulated_usd.toFixed(2)} / $${info.budget_usd.toFixed(2)}）— 留意是否需要充值` :
              `${provider} usage at ${ratioPct}% ($${info.accumulated_usd.toFixed(2)} / $${info.budget_usd.toFixed(2)}) — consider topping up`)}
      </div>
      {isRed && link && (
        <a href={link} target="_blank" rel="noopener noreferrer"
          style={{ color: '#fca5a5', textDecoration: 'underline', fontSize: 13 }}>
          {provider === 'openai'
            ? (t ? '前往 OpenAI dashboard' : 'Go to OpenAI dashboard')
            : (t ? '前往 Zeabur AI Hub' : 'Go to Zeabur AI Hub')}
        </a>
      )}
    </div>
  );
};

const ProviderSummaryCard = ({ lang, provider, info, color }) => {
  const t = lang === 'zh';
  const ratio = info.ratio || 0;
  const ratioPct = (ratio * 100).toFixed(1);
  const fillW = Math.min(100, ratio * 100);
  return (
    <div style={{ background: TOKEN.surface, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 10, padding: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <span style={{ width: 10, height: 10, background: color, borderRadius: '50%', display: 'inline-block' }} />
        <span style={{ color: TOKEN.text, fontWeight: 700, fontSize: 14 }}>{provider}</span>
      </div>
      <div style={{ color: TOKEN.text, fontSize: 22, fontWeight: 700, marginBottom: 2 }}>
        ${info.accumulated_usd.toFixed(2)}
      </div>
      <div style={{ color: TOKEN.textMuted, fontSize: 12, marginBottom: 12 }}>
        {t ? '本月累積 / 預算' : 'Month-to-date / Budget'} ${info.budget_usd.toFixed(2)}（{ratioPct}%）
      </div>
      <div style={{ height: 8, background: TOKEN.surfaceBorder, borderRadius: 99, overflow: 'hidden', marginBottom: 12 }}>
        <div style={{ width: `${fillW}%`, height: '100%', background: ratio >= 0.95 ? TOKEN.danger : ratio >= 0.8 ? TOKEN.warning : color, transition: 'width 0.3s' }} />
      </div>
      {info.top_models && info.top_models.length > 0 && (
        <div>
          <div style={{ color: TOKEN.textMuted, fontSize: 11, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 6 }}>
            {t ? '本月前 3 名 model' : 'Top 3 models'}
          </div>
          {info.top_models.slice(0, 3).map(m => (
            <div key={m.model} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: TOKEN.textSecondary, padding: '3px 0' }}>
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '70%' }}>{m.model}</span>
              <span>${m.spend_usd.toFixed(2)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

const ProviderUsageChart = ({ lang, daily, monthly, onHoverDay, hoverDay }) => {
  const t = lang === 'zh';
  // Aggregate daily rows: {date -> {provider -> spend}}
  const byDate = {};
  daily.forEach(row => {
    if (!byDate[row.date]) byDate[row.date] = {};
    byDate[row.date][row.provider] = (byDate[row.date][row.provider] || 0) + row.spend_usd;
  });
  const dates = Object.keys(byDate).sort();
  if (dates.length === 0) {
    return (
      <div style={{ padding: 20, color: TOKEN.textMuted, background: TOKEN.surface, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 10 }}>
        {t ? '尚無 30 天用量資料。Beat task 第一次跑完後會出現。' : 'No 30-day usage data yet. Will appear after the first Beat task run.'}
      </div>
    );
  }
  const providers = Array.from(new Set(daily.map(r => r.provider))).sort();
  // Compute max stacked total for y-scale
  let maxStack = 0;
  dates.forEach(d => {
    const sum = providers.reduce((acc, p) => acc + (byDate[d][p] || 0), 0);
    if (sum > maxStack) maxStack = sum;
  });
  if (maxStack <= 0) maxStack = 1;

  const W = 760, H = 220, PAD_L = 40, PAD_R = 12, PAD_T = 12, PAD_B = 28;
  const plotW = W - PAD_L - PAD_R, plotH = H - PAD_T - PAD_B;
  const barGap = 2;
  const barW = Math.max(2, (plotW / dates.length) - barGap);

  // Format date label in Taipei (date strings are already calendar dates, but
  // server emits UTC date; for display we just append "（台北）" hint in tooltip).
  return (
    <div style={{ background: TOKEN.surface, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 10, padding: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <span style={{ color: TOKEN.text, fontWeight: 700, fontSize: 14 }}>
          {t ? '30 天每日用量（USD）' : '30-day daily usage (USD)'}
        </span>
        <div style={{ display: 'flex', gap: 12 }}>
          {providers.map((p, idx) => (
            <span key={p} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: TOKEN.textSecondary, fontSize: 12 }}>
              <span style={{ width: 10, height: 10, background: _colorForProvider(p, idx), borderRadius: 2 }} />
              {p}
            </span>
          ))}
        </div>
      </div>
      <div style={{ position: 'relative' }}>
        <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto', display: 'block' }}>
          {/* Y axis grid (3 lines) */}
          {[0.25, 0.5, 0.75, 1].map(frac => {
            const y = PAD_T + plotH * (1 - frac);
            const val = (maxStack * frac).toFixed(2);
            return (
              <g key={frac}>
                <line x1={PAD_L} y1={y} x2={W - PAD_R} y2={y}
                  stroke={TOKEN.surfaceBorder} strokeWidth="1" />
                <text x={PAD_L - 4} y={y + 3} fontSize="9" fill={TOKEN.textMuted} textAnchor="end">
                  ${val}
                </text>
              </g>
            );
          })}
          {/* Bars */}
          {dates.map((d, i) => {
            const x = PAD_L + i * (barW + barGap);
            let yCursor = PAD_T + plotH;
            return (
              <g key={d}
                onMouseEnter={() => onHoverDay({ date: d, providers: byDate[d] })}
                onMouseLeave={() => onHoverDay(null)}>
                {providers.map((p, idx) => {
                  const v = byDate[d][p] || 0;
                  if (v <= 0) return null;
                  const h = (v / maxStack) * plotH;
                  yCursor -= h;
                  return (
                    <rect key={p} x={x} y={yCursor} width={barW} height={h}
                      fill={_colorForProvider(p, idx)} opacity={hoverDay && hoverDay.date === d ? 1 : 0.85} />
                  );
                })}
                {/* X-axis tick every ~5 days */}
                {i % 5 === 0 && (
                  <text x={x + barW / 2} y={H - PAD_B + 14} fontSize="9"
                    fill={TOKEN.textMuted} textAnchor="middle">{d.slice(5)}</text>
                )}
              </g>
            );
          })}
        </svg>
        {hoverDay && (
          <div style={{ position: 'absolute', top: 8, right: 8, background: TOKEN.bg, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 8, padding: '8px 12px', fontSize: 12, color: TOKEN.text, pointerEvents: 'none' }}>
            <div style={{ fontWeight: 700, marginBottom: 4 }}>
              {hoverDay.date} {t ? '台北' : 'Taipei'}
            </div>
            {Object.entries(hoverDay.providers).map(([p, v]) => (
              <div key={p} style={{ color: TOKEN.textSecondary }}>{p}: ${v.toFixed(2)}</div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

Object.assign(window, { ProviderUsageTab });
