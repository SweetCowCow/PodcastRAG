// PresentationPage — fullscreen 13-slide deck. Chinese-only by design.
// Entry: URL hash #presentation. Exit: Escape (clears hash).
// Reads window.RELEASE_LOG / STATS_* / TAG_LABELS from src/releaseLog.jsx.

const TOTAL_SLIDES = 13;

// Inline case study summaries (3 lines each: 問題 / 轉折 / 學到的事).
// Sourced from docs/case-studies/ but written here as constants — no fetch.
const CASE_STUDIES = [
  {
    file: 'transcription-queue-discussion.md',
    title: '把模糊的「排程」需求拆成 6 個明確決策',
    problem: '後端有 ShowSchedule 表存頻率/時間,但專案完全沒有 cron。死資料放了兩週沒人動。',
    turn: '使用者沒順 Claude 的技術假設答,而是退回畫出自己的 mental model:節目 → 集數 →（更新清單 / 轉錄）兩個動詞。',
    lesson: '討論卡住時,從技術假設退回使用者情境;Claude 主動 challenge 並標推薦,使用者只需 confirm 不用每題從零想。',
  },
  {
    file: 'sync-naming-redesign.md',
    title: '「同步」這個詞讓使用者搞不清楚按鈕會做什麼',
    problem: '「同步集數」(只抓 RSS)和「同步所有」(會燒 OpenAI 額度)語意混在一起,使用者點下去無法預期會不會花錢。',
    turn: '使用者反問:「目前的同步,這件事會去執行什麼動作?」Claude 把所有按鈕的真實行為列表攤開,根因立刻清楚。',
    lesson: '一個動詞被掛在性質完全不同的兩件事上時,UX 必然出問題。把名字和行為對照列出,就能找到該分裂的地方。',
  },
  {
    file: 'local-vs-prod-verification-violation.md',
    title: '明明寫好不准 local 驗,Claude 還是默默開了 http.server',
    problem: '規則寫了「禁止 local 驗證」,Claude 卻自我合理化「我沒用 mock 資料只是繞 CORS」就跑了 python3 -m http.server。',
    turn: '使用者沒罵人,只說「我之前好像有提過類似要求」—— 把「不是新規則,是你忘了用」這個訊號傳給 Claude。',
    lesson: '規則要寫清楚 why 與「即使 X 也不行」的延伸條款;否則 AI 會字面化解讀並自我合理化。',
  },
];

const NEXT_STEPS = [
  '使用量統計 Dashboard(token / cost 計價)',
  '正式帳號驗證系統(目前是寫死的示範帳密)',
  'Pre-built base image(build 時間 10min → 30sec)',
  'pg_dump 定期備份',
  'API Keys tab 後端連動(目前是 mock)',
];

// Reusable slide chrome — fullscreen card with footer counter & hint.
const SlideShell = ({ slideIndex, children, accent = TOKEN.accent }) => (
  <div style={{
    width: '100%', height: '100%',
    background: `radial-gradient(ellipse at top, ${TOKEN.surface} 0%, ${TOKEN.bg} 60%)`,
    display: 'flex', flexDirection: 'column',
    color: TOKEN.text,
    fontFamily: "'Inter', 'Helvetica Neue', Arial, sans-serif",
  }}>
    <div style={{
      flex: 1, display: 'flex', flexDirection: 'column',
      justifyContent: 'center', alignItems: 'stretch',
      padding: '60px 80px',
      maxWidth: 1080, margin: '0 auto', width: '100%',
      boxSizing: 'border-box',
    }}>
      {children}
    </div>
    {/* Footer */}
    <div style={{
      padding: '14px 32px',
      borderTop: `1px solid ${TOKEN.surfaceBorder}`,
      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      color: TOKEN.textMuted, fontSize: 12,
    }}>
      <span>← → 切換 ｜ Space 下一張 ｜ Esc 退出</span>
      <span style={{ fontVariantNumeric: 'tabular-nums', color: accent }}>
        {slideIndex + 1} / {TOTAL_SLIDES}
      </span>
    </div>
  </div>
);

// ── Slide 0: Cover ──
const SlideCover = () => (
  <div style={{ textAlign: 'center' }}>
    <div style={{
      display: 'inline-flex', alignItems: 'center', gap: 14,
      padding: '8px 18px', borderRadius: 99,
      background: TOKEN.accentDim, color: TOKEN.accent,
      fontSize: 13, fontWeight: 600, letterSpacing: '0.08em',
      marginBottom: 32,
    }}>
      <Icon name="zap" size={14} color={TOKEN.accent} />
      PODCASTRAG · 系統介紹
    </div>
    <h1 style={{ fontSize: 56, fontWeight: 800, margin: '0 0 24px', lineHeight: 1.15, letterSpacing: '-0.01em' }}>
      一個 Podcast RAG 系統的<br />
      <span style={{ color: TOKEN.accent }}>成長軌跡</span>
    </h1>
    <p style={{ fontSize: 18, color: TOKEN.textSecondary, margin: 0, lineHeight: 1.6 }}>
      從 24 個 archived changes 看見產品如何一塊一塊長出來
    </p>
  </div>
);

// ── Slide 1: System intro ──
const SlideIntro = () => (
  <div>
    <div style={{ color: TOKEN.accent, fontSize: 14, fontWeight: 600, letterSpacing: '0.1em', marginBottom: 16 }}>
      WHAT IS PODCASTRAG
    </div>
    <h2 style={{ fontSize: 40, fontWeight: 700, margin: '0 0 28px', lineHeight: 1.25 }}>
      讓使用者用<span style={{ color: TOKEN.accent }}>對話</span>查 Podcast 內容,<br />
      不用聽完整集就找得到關鍵段落。
    </h2>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 20, marginTop: 16 }}>
      {[
        { icon: 'rss', title: 'RSS → 逐字稿', desc: '貼一個 RSS URL,系統自動抓集數、用 Whisper 轉錄成帶時間戳的逐字稿。' },
        { icon: 'brain', title: '語意檢索 + RAG', desc: '逐字稿切 chunk → embedding → pgvector 搜尋 → LLM 帶引用回答。' },
        { icon: 'play', title: '點擊跳轉時間段', desc: '回答中的引用 Badge 點下去,直接跳到逐字稿對應時間點。' },
      ].map(item => (
        <div key={item.title} style={{ background: TOKEN.surface, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 14, padding: 22 }}>
          <div style={{ width: 36, height: 36, borderRadius: 9, background: TOKEN.accentDim, display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: 14 }}>
            <Icon name={item.icon} size={18} color={TOKEN.accent} />
          </div>
          <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 8 }}>{item.title}</div>
          <div style={{ fontSize: 13, color: TOKEN.textSecondary, lineHeight: 1.6 }}>{item.desc}</div>
        </div>
      ))}
    </div>
  </div>
);

// ── Slide 2: Architecture diagram (pure div) ──
const ArchBox = ({ label, sub, color = TOKEN.accent, width = 140 }) => (
  <div style={{
    width, padding: '14px 12px',
    background: TOKEN.surface, border: `2px solid ${color}`, borderRadius: 12,
    textAlign: 'center', boxShadow: `0 0 0 4px ${color}1a`,
  }}>
    <div style={{ fontSize: 14, fontWeight: 700, color: TOKEN.text }}>{label}</div>
    <div style={{ fontSize: 11, color: TOKEN.textMuted, marginTop: 4 }}>{sub}</div>
  </div>
);
const ArchArrow = ({ width = 60 }) => (
  <div style={{ flex: 'none', width, height: 2, background: TOKEN.surfaceBorder, position: 'relative' }}>
    <div style={{ position: 'absolute', right: -1, top: -3, width: 0, height: 0, borderLeft: `8px solid ${TOKEN.surfaceBorder}`, borderTop: '4px solid transparent', borderBottom: '4px solid transparent' }} />
  </div>
);

const SlideArchitecture = () => (
  <div>
    <div style={{ color: TOKEN.accent, fontSize: 14, fontWeight: 600, letterSpacing: '0.1em', marginBottom: 16 }}>
      ARCHITECTURE
    </div>
    <h2 style={{ fontSize: 32, fontWeight: 700, margin: '0 0 40px' }}>系統架構</h2>
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 0, marginBottom: 32 }}>
      <ArchBox label="Frontend" sub="React CDN + Inline JSX" color="#22d3ee" />
      <ArchArrow />
      <ArchBox label="Backend API" sub="FastAPI" color={TOKEN.accent} />
      <ArchArrow />
      <ArchBox label="Worker" sub="Celery × 3" color="#f59e0b" />
    </div>
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 32 }}>
      <ArchBox label="PostgreSQL" sub="+ pgvector" color="#22c55e" width={160} />
      <ArchBox label="Redis" sub="Broker + Result" color="#ef4444" width={160} />
      <ArchBox label="Cloudflare R2" sub="音檔物件儲存" color="#a78bfa" width={160} />
    </div>
    <p style={{ marginTop: 36, color: TOKEN.textSecondary, fontSize: 14, textAlign: 'center', lineHeight: 1.7 }}>
      部署於 <span style={{ color: TOKEN.accent }}>Zeabur</span> + Linode SIN VPS / LLM 走 <span style={{ color: TOKEN.accent }}>Zeabur AI Hub</span>(OpenAI-compatible)
    </p>
  </div>
);

// ── Slides 3–6: Milestones (data-driven from RELEASE_LOG) ──
const SlideMilestone = ({ milestone }) => {
  const entries = RELEASE_LOG
    .filter(e => e.milestone === milestone)
    .slice()
    .sort((a, b) => (a.date < b.date ? -1 : 1));
  const label = MILESTONE_LABELS[milestone] ? MILESTONE_LABELS[milestone].zh : milestone;
  return (
    <div>
      <div style={{ color: TOKEN.accent, fontSize: 14, fontWeight: 600, letterSpacing: '0.1em', marginBottom: 16 }}>
        MILESTONE · {milestone.toUpperCase()}
      </div>
      <h2 style={{ fontSize: 32, fontWeight: 700, margin: '0 0 8px' }}>{label}</h2>
      <div style={{ color: TOKEN.textMuted, fontSize: 13, marginBottom: 28 }}>
        {entries[0]?.date} – {entries[entries.length - 1]?.date} ｜ 共 {entries.length} 項更新
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10, maxHeight: 420, overflowY: 'auto', paddingRight: 8 }}>
        {entries.map(e => (
          <div key={e.slug} style={{
            display: 'flex', alignItems: 'flex-start', gap: 14,
            padding: '12px 16px', background: TOKEN.surface,
            border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 10,
          }}>
            <div style={{
              flex: 'none', minWidth: 86,
              color: TOKEN.textMuted, fontSize: 12,
              fontVariantNumeric: 'tabular-nums', paddingTop: 2,
            }}>
              {e.date}
            </div>
            <div style={{ flex: 'none' }}>
              <Badge variant={
                e.tag === 'feature' ? 'success' :
                e.tag === 'fix' ? 'warning' :
                e.tag === 'enhancement' ? 'default' : 'muted'
              }>{TAG_LABELS[e.tag].zh}</Badge>
            </div>
            <div style={{ flex: 1, fontSize: 15, fontWeight: 500, color: TOKEN.text, lineHeight: 1.5 }}>
              {e.title.zh}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

// ── Slide 7: Stats ──
const SlideStats = () => {
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

  const epCount = stats ? stats.episodes_completed : STATS_EPISODES_COUNT;
  const chunkCount = stats ? stats.transcript_chunks : STATS_VECTORS_COUNT;
  const cards = [
    { value: STATS_CHANGES_COUNT, label: 'Archived Changes', sub: '從 4/19 到 5/01' },
    { value: epCount.toLocaleString(), label: '已轉錄集數', sub: '使用 OpenAI Whisper' },
    { value: chunkCount.toLocaleString(), label: '向量索引筆數', sub: 'pgvector 1536-dim' },
  ];
  return (
    <div>
      <div style={{ color: TOKEN.accent, fontSize: 14, fontWeight: 600, letterSpacing: '0.1em', marginBottom: 16 }}>
        BY THE NUMBERS
      </div>
      <h2 style={{ fontSize: 32, fontWeight: 700, margin: '0 0 12px' }}>數字成長</h2>
      <div style={{ color: TOKEN.textMuted, fontSize: 13, marginBottom: 40 }}>
        截至 {STATS_AS_OF}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 24 }}>
        {cards.map(c => (
          <div key={c.label} style={{
            background: TOKEN.surface, border: `1px solid ${TOKEN.surfaceBorder}`,
            borderRadius: 18, padding: '32px 24px', textAlign: 'center',
          }}>
            <div style={{
              fontSize: 64, fontWeight: 800, color: TOKEN.accent,
              fontVariantNumeric: 'tabular-nums', lineHeight: 1, marginBottom: 12,
            }}>
              {c.value}
            </div>
            <div style={{ fontSize: 16, fontWeight: 600, color: TOKEN.text, marginBottom: 4 }}>
              {c.label}
            </div>
            <div style={{ fontSize: 12, color: TOKEN.textMuted }}>
              {c.sub}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

// ── Slides 8–10: Case studies ──
const SlideCaseStudy = ({ index }) => {
  const cs = CASE_STUDIES[index];
  return (
    <div>
      <div style={{ color: TOKEN.accent, fontSize: 14, fontWeight: 600, letterSpacing: '0.1em', marginBottom: 16 }}>
        過程心得 · {index + 1} / {CASE_STUDIES.length}
      </div>
      <h2 style={{ fontSize: 30, fontWeight: 700, margin: '0 0 36px', lineHeight: 1.3 }}>
        {cs.title}
      </h2>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
        {[
          { tag: '問題', body: cs.problem, color: TOKEN.danger },
          { tag: '轉折', body: cs.turn,    color: TOKEN.warning },
          { tag: '學到的事', body: cs.lesson, color: TOKEN.success },
        ].map(row => (
          <div key={row.tag} style={{ display: 'flex', alignItems: 'flex-start', gap: 16 }}>
            <div style={{
              flex: 'none', minWidth: 88,
              padding: '6px 10px', borderRadius: 6,
              background: `${row.color}1a`, color: row.color,
              fontSize: 13, fontWeight: 700, textAlign: 'center',
            }}>
              {row.tag}
            </div>
            <div style={{ flex: 1, fontSize: 17, color: TOKEN.text, lineHeight: 1.7 }}>
              {row.body}
            </div>
          </div>
        ))}
      </div>
      <div style={{ marginTop: 40, fontSize: 11, color: TOKEN.textMuted, fontFamily: 'monospace' }}>
        docs/case-studies/{cs.file}
      </div>
    </div>
  );
};

// ── Slide 11: Next steps ──
const SlideNext = () => (
  <div>
    <div style={{ color: TOKEN.accent, fontSize: 14, fontWeight: 600, letterSpacing: '0.1em', marginBottom: 16 }}>
      WHAT'S NEXT
    </div>
    <h2 style={{ fontSize: 32, fontWeight: 700, margin: '0 0 36px' }}>接下來</h2>
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      {NEXT_STEPS.map((step, idx) => (
        <div key={idx} style={{
          display: 'flex', alignItems: 'center', gap: 18,
          padding: '16px 20px',
          background: TOKEN.surface, border: `1px solid ${TOKEN.surfaceBorder}`,
          borderRadius: 12,
        }}>
          <div style={{
            flex: 'none', width: 32, height: 32, borderRadius: 8,
            background: TOKEN.accentDim, color: TOKEN.accent,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontWeight: 700, fontSize: 14,
          }}>
            {idx + 1}
          </div>
          <div style={{ fontSize: 17, color: TOKEN.text }}>{step}</div>
        </div>
      ))}
    </div>
  </div>
);

// ── Slide 12: Closing ──
const SlideClosing = () => (
  <div style={{ textAlign: 'center' }}>
    <div style={{
      display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
      width: 72, height: 72, borderRadius: 18,
      background: TOKEN.accentDim, marginBottom: 28,
    }}>
      <Icon name="zap" size={36} color={TOKEN.accent} />
    </div>
    <h1 style={{ fontSize: 52, fontWeight: 800, margin: '0 0 20px', letterSpacing: '-0.01em' }}>
      謝謝聆聽
    </h1>
    <p style={{ fontSize: 18, color: TOKEN.textSecondary, margin: '0 0 36px', lineHeight: 1.6 }}>
      PodcastRAG · podcastrag.zeabur.app
    </p>
    <p style={{ fontSize: 13, color: TOKEN.textMuted, margin: 0, fontStyle: 'italic' }}>
      "從 24 個小決定堆出來的系統。"
    </p>
  </div>
);

// ── Main ──
const PresentationPage = () => {
  const [slideIndex, setSlideIndex] = React.useState(0);

  React.useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'ArrowRight' || e.key === ' ' || e.key === 'Spacebar') {
        e.preventDefault();
        setSlideIndex(i => Math.min(TOTAL_SLIDES - 1, i + 1));
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault();
        setSlideIndex(i => Math.max(0, i - 1));
      } else if (e.key === 'Escape') {
        e.preventDefault();
        if (window.location.hash) {
          history.replaceState(null, '', window.location.pathname + window.location.search);
          window.dispatchEvent(new HashChangeEvent('hashchange'));
        }
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  let slide;
  if (slideIndex === 0) slide = <SlideCover />;
  else if (slideIndex === 1) slide = <SlideIntro />;
  else if (slideIndex === 2) slide = <SlideArchitecture />;
  else if (slideIndex === 3) slide = <SlideMilestone milestone="v0.1" />;
  else if (slideIndex === 4) slide = <SlideMilestone milestone="v0.2" />;
  else if (slideIndex === 5) slide = <SlideMilestone milestone="v0.3" />;
  else if (slideIndex === 6) slide = <SlideMilestone milestone="v0.4" />;
  else if (slideIndex === 7) slide = <SlideStats />;
  else if (slideIndex === 8) slide = <SlideCaseStudy index={0} />;
  else if (slideIndex === 9) slide = <SlideCaseStudy index={1} />;
  else if (slideIndex === 10) slide = <SlideCaseStudy index={2} />;
  else if (slideIndex === 11) slide = <SlideNext />;
  else slide = <SlideClosing />;

  return <SlideShell slideIndex={slideIndex}>{slide}</SlideShell>;
};

Object.assign(window, { PresentationPage });
