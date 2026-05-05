// Query Page — Layer 2: Search/Chat + Resizable/Collapsible Episode Panel
const MOCK_EPISODES = [
  { id: 'ep142', num: 142, title: '輝達 CUDA 護城河與台積電先進封裝的共生關係', titleEn: 'NVIDIA\'s CUDA Moat and TSMC Advanced Packaging Symbiosis', date: '2026-04-18', duration: '58:24', summary: '本集深度解析輝達 CUDA 生態系統如何形成技術護城河，以及台積電 CoWoS 先進封裝技術在 AI 晶片供應鏈中的不可替代性。專訪台積電前研發副總裁，揭露 2nm 製程量產挑戰。', summaryEn: 'Deep analysis of how NVIDIA\'s CUDA ecosystem forms a technological moat, and the indispensability of TSMC\'s CoWoS advanced packaging in the AI chip supply chain.', transcribed: true },
  { id: 'ep141', num: 141, title: '英特爾重組後的殘局：晶圓代工業務存活機率評估', titleEn: 'Intel Post-Restructuring: Assessing Foundry Survival Odds', date: '2026-04-11', duration: '64:10', summary: '英特爾宣布將晶圓代工業務分拆為獨立子公司後，業界對其存活率看法分歧。本集邀請三位半導體分析師進行辯論，並提出關鍵觀察指標。', summaryEn: 'Intel announced the spin-off of its foundry business. Three semiconductor analysts debate its survival odds.', transcribed: true },
  { id: 'ep140', num: 140, title: '日本半導體復興計畫：熊本廠之後的下一步', titleEn: 'Japan\'s Semiconductor Revival: What Comes After Kumamoto', date: '2026-04-04', duration: '51:33', summary: '熊本廠量產後，日本政府持續推動半導體自主化。本集分析 Rapidus 2nm 計畫的可行性，以及日本吸引 TSMC 第三廠的籌碼。', summaryEn: 'After the Kumamoto plant, Japan continues its semiconductor independence push.', transcribed: true },
  { id: 'ep139', num: 139, title: '亞利桑那廠良率困境與美國供應鏈在地化的現實', titleEn: 'Arizona Yield Struggles and the Reality of US Supply Chain Localization', date: '2026-03-28', duration: '55:48', summary: '台積電亞利桑那廠量產後良率低於台灣廠的問題持續受關注。本集訪談在地工程師，分析人才、文化與製程轉移的多重挑戰。', summaryEn: 'TSMC Arizona yield rates remain below Taiwan fabs post-production ramp.', transcribed: true },
  { id: 'ep138', num: 138, title: '中國半導體自主化進展：突破與限制的真實現況', titleEn: 'China Chip Autonomy Progress: Reality Behind the Breakthroughs', date: '2026-03-21', duration: '61:07', summary: '中國 7nm 晶片量產消息持續發酵，但與世界先進水準的差距究竟有多大？本集拆解各方說法，提供有數據支撐的客觀評估。', summaryEn: 'China\'s 7nm chip production news continues to stir debate.', transcribed: true },
  { id: 'ep137', num: 137, title: '量子電腦商業化時間表：Google Willow 之後的賽局', titleEn: 'Quantum Computing Timeline: The Race After Google Willow', date: '2026-03-14', duration: '49:22', summary: 'Google Willow 晶片突破後，各大科技公司紛紛加速量子路線圖。', summaryEn: 'After Google Willow\'s breakthrough, major tech companies accelerate quantum roadmaps.', transcribed: false },
];

const MOCK_CHAT = [];

const formatTimestamp = (seconds) => {
  if (seconds == null || Number.isNaN(seconds)) return '--:--';
  const total = Math.floor(seconds);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
};

// ── Resizable Episode Panel (desktop) / Drawer (mobile) ──
const ResizableLayout = ({ lang, leftContent, rightContent, epCount, epTotal, drawerOpen, setDrawerOpen }) => {
  const t = lang === 'zh';
  const { isMobile } = useViewport();
  const containerRef = React.useRef(null);
  const [panelWidth, setPanelWidth] = React.useState(340);
  const [collapsed, setCollapsed] = React.useState(false);
  const [dragging, setDragging] = React.useState(false);
  const MIN_WIDTH = 200;
  const MAX_RATIO = 0.45; // max 45% of container

  const onDragStart = (e) => {
    e.preventDefault();
    setDragging(true);
    const startX = e.clientX;
    const startW = panelWidth;
    const move = (ev) => {
      if (!containerRef.current) return;
      const maxW = containerRef.current.offsetWidth * MAX_RATIO;
      const delta = startX - ev.clientX;
      const newW = Math.min(maxW, Math.max(MIN_WIDTH, startW + delta));
      setPanelWidth(newW);
    };
    const up = () => { setDragging(false); window.removeEventListener('mousemove', move); window.removeEventListener('mouseup', up); };
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', up);
  };

  if (isMobile) {
    return (
      <div ref={containerRef} style={{ flex: 1, display: 'flex', overflow: 'hidden', position: 'relative' }}>
        {/* Chat full width */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minWidth: 0 }}>
          {leftContent}
        </div>

        {/* Overlay */}
        {drawerOpen && (
          <div onClick={() => setDrawerOpen(false)}
            style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', zIndex: 99 }} />
        )}

        {/* Drawer */}
        <div style={{
          position: 'fixed', right: 0, top: 0, bottom: 0,
          width: 'min(85vw, 360px)',
          transform: drawerOpen ? 'translateX(0)' : 'translateX(100%)',
          transition: 'transform 0.18s ease-out',
          background: TOKEN.surface,
          borderLeft: `1px solid ${TOKEN.surfaceBorder}`,
          display: 'flex', flexDirection: 'column',
          zIndex: 100, boxShadow: drawerOpen ? '-8px 0 32px rgba(0,0,0,0.4)' : 'none',
        }}>
          <div style={{ padding: '0 12px', height: 52, borderBottom: `1px solid ${TOKEN.surfaceBorder}`, display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ color: TOKEN.text, fontWeight: 600, fontSize: 14, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {t ? '已轉錄集數' : 'Transcribed Episodes'}
              </div>
              <div style={{ color: TOKEN.textMuted, fontSize: 11 }}>{epCount} / {epTotal} {t ? '集' : 'eps'}</div>
            </div>
            <button onClick={() => setDrawerOpen(false)} aria-label={t ? '關閉' : 'Close'}
              style={{ width: 36, height: 36, borderRadius: 7, background: TOKEN.surfaceRaised, border: `1px solid ${TOKEN.surfaceBorder}`, color: TOKEN.textSecondary, cursor: 'pointer', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', padding: 0, flexShrink: 0 }}>
              <Icon name="x" size={16} color="currentColor" />
            </button>
          </div>
          <div style={{ flex: 1, overflowY: 'auto', padding: '10px 10px' }}>
            {rightContent}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div ref={containerRef} style={{ flex: 1, display: 'flex', overflow: 'hidden', position: 'relative', cursor: dragging ? 'col-resize' : 'auto', userSelect: dragging ? 'none' : 'auto' }}>
      {/* Left: Query panel */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minWidth: 0 }}>
        {leftContent}
      </div>

      {/* Drag handle */}
      <div onMouseDown={onDragStart}
        style={{ width: 5, flexShrink: 0, background: dragging ? TOKEN.accent : TOKEN.surfaceBorder, cursor: 'col-resize', transition: 'background 0.15s', position: 'relative', zIndex: 10 }}
        onMouseEnter={e => { if (!dragging) e.currentTarget.style.background = TOKEN.accent + '88'; }}
        onMouseLeave={e => { if (!dragging) e.currentTarget.style.background = TOKEN.surfaceBorder; }}>
        <div style={{ position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%,-50%)', display: 'flex', flexDirection: 'column', gap: 3 }}>
          {[0,1,2].map(i => <div key={i} style={{ width: 3, height: 3, borderRadius: '50%', background: TOKEN.textMuted }} />)}
        </div>
      </div>

      {/* Right: Episode panel (collapsible) */}
      <div style={{ width: collapsed ? 36 : panelWidth, flexShrink: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden', borderLeft: `1px solid ${TOKEN.surfaceBorder}`, transition: collapsed ? 'width 0.2s' : 'none', background: TOKEN.surface }}>
        <div style={{ padding: '0 12px', height: 49, borderBottom: `1px solid ${TOKEN.surfaceBorder}`, display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0, background: TOKEN.surface }}>
          <button onClick={() => setCollapsed(v => !v)}
            style={{ width: 26, height: 26, borderRadius: 6, background: TOKEN.surfaceRaised, border: `1px solid ${TOKEN.surfaceBorder}`, display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', flexShrink: 0 }}>
            <Icon name={collapsed ? 'chevronLeft' : 'chevronRight'} size={14} color={TOKEN.textSecondary} />
          </button>
          {!collapsed && (
            <>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ color: TOKEN.text, fontWeight: 600, fontSize: 14, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {t ? '已轉錄集數' : 'Transcribed Episodes'}
                </div>
                <div style={{ color: TOKEN.textMuted, fontSize: 11 }}>{epCount} / {epTotal} {t ? '集' : 'eps'}</div>
              </div>
            </>
          )}
        </div>

        {!collapsed && (
          <div style={{ flex: 1, overflowY: 'auto', padding: '10px 10px' }}>
            {rightContent}
          </div>
        )}

        {collapsed && (
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <span style={{ color: TOKEN.textMuted, fontSize: 11, writingMode: 'vertical-rl', transform: 'rotate(180deg)', letterSpacing: '0.05em' }}>
              {t ? '集數列表' : 'Episodes'}
            </span>
          </div>
        )}
      </div>
    </div>
  );
};

// ── Main QueryPage ──
// Locked card replacing the chat answer area for unauthenticated visitors.
// Height-capped so segment results below stay visible without forced scrolling.
const LockedAnswerCard = ({ lang }) => {
  const t = lang === 'zh';
  return (
    <div style={{
      flex: 1,
      display: 'flex',
      alignItems: 'flex-start',
      justifyContent: 'center',
      padding: '24px 24px 40px',
      overflow: 'hidden',
    }}>
      <div style={{
        maxWidth: 480,
        width: '100%',
        maxHeight: 200,
        background: TOKEN.surface,
        border: `1px solid ${TOKEN.surfaceBorder}`,
        borderRadius: 12,
        padding: '20px 24px',
        textAlign: 'center',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
        gap: 8,
      }}>
        <div style={{ fontSize: 24 }}>🔒</div>
        <h3 style={{ margin: 0, color: TOKEN.text, fontSize: 16, fontWeight: 700 }}>
          {t ? '想看 AI 整段統整？' : 'Want the AI summary?'}
        </h3>
        <p style={{ margin: 0, color: TOKEN.textSecondary, fontSize: 13 }}>
          {t ? '不用一段段拼湊。' : 'Skip stitching segments together.'}
        </p>
        <div style={{ marginTop: 6 }}>
          <Btn variant="primary" size="sm" onClick={() => { window.location.href = googleLoginUrl(); }}>
            {t ? '以 Google 登入解鎖' : 'Sign in with Google to unlock'}
          </Btn>
        </div>
        <div style={{ fontSize: 11, color: TOKEN.textMuted }}>
          {t ? '30 次免費' : '30 free uses'}
        </div>
      </div>
    </div>
  );
};

const QueryPage = ({ lang, show, onBack, onOpenEpisode, queryMode, user, onUserChange, initialQuery }) => {
  const t = lang === 'zh';
  const quotaExhausted = user && user.quota_remaining === 0;
  const { isMobile } = useViewport();
  const [drawerOpen, setDrawerOpen] = React.useState(false);
  // Anonymous visitors land on the search tab so they can use the free
  // segment search; chat tab shows a locked card for them.
  const [activeTab, setActiveTab] = React.useState(user ? 'chat' : 'search');
  const [chatInput, setChatInput] = React.useState('');
  const [messages, setMessages] = React.useState(MOCK_CHAT);
  const [searchQ, setSearchQ] = React.useState(initialQuery || '');
  const [searching, setSearching] = React.useState(false);
  const [searchResults, setSearchResults] = React.useState(null);
  const [selectedEp, setSelectedEp] = React.useState(null);
  const [sending, setSending] = React.useState(false);
  const [episodes, setEpisodes] = React.useState(null);
  const [epError, setEpError] = React.useState(null);
  const [quotaModalOpen, setQuotaModalOpen] = React.useState(false);
  // R1.1: thumbs vote state — keyed by query_id; value is 'up' | 'down'.
  const [votes, setVotes] = React.useState({});
  // R1.1: admin debug — 7-day rolling thumbs ratio. Fetched once per session
  // when admin and at least one AI answer is present.
  const [adminStats, setAdminStats] = React.useState(null);
  const adminStatsFetchedRef = React.useRef(false);
  const chatEndRef = React.useRef(null);

  // If we arrived from LandingPage with a query, fire the search once on mount
  const didAutoSearchRef = React.useRef(false);
  React.useEffect(() => {
    if (didAutoSearchRef.current) return;
    if (initialQuery && initialQuery.trim()) {
      didAutoSearchRef.current = true;
      // Defer one tick so handleSearch sees the populated state
      setTimeout(() => handleSearch(initialQuery.trim()), 0);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialQuery]);

  React.useEffect(() => {
    if (chatEndRef.current) chatEndRef.current.scrollTop = chatEndRef.current.scrollHeight;
  }, [messages]);

  React.useEffect(() => {
    let cancelled = false;
    setEpisodes(null);
    setEpError(null);
    (async () => {
      try {
        const res = await apiFetch(`/shows/${show.id}/episodes?limit=200`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (!cancelled) setEpisodes(data);
      } catch (err) {
        if (!cancelled) setEpError(err.message);
      }
    })();
    return () => { cancelled = true; };
  }, [show.id]);

  const handleSend = async () => {
    const question = chatInput.trim();
    if (!question || sending) return;
    const nextHistory = [...messages, { role: 'user', text: question }];
    setMessages(nextHistory);
    setChatInput('');
    setSending(true);
    try {
      const history = nextHistory
        .slice(0, -1)
        .slice(-10)
        .map(m => ({ role: m.role, content: m.text }));
      let res;
      try {
        res = await apiFetch(`/shows/${show.id}/query`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ mode: 'chat', question, messages: history }),
        });
      } catch (netErr) {
        throw new Error(networkErrorMessage(lang));
      }
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(formatError(body, lang));
      }
      const data = await res.json();
      setMessages(m => [...m, { role: 'assistant', text: data.answer, citations: data.citations || [], query_id: data.query_id }]);
      if (typeof data.quota_remaining === 'number' && onUserChange) onUserChange();
    } catch (err) {
      setMessages(m => [...m, { role: 'assistant', text: err.message, citations: [] }]);
    } finally {
      setSending(false);
    }
  };

  const handleSearch = async (overrideQuestion) => {
    const question = (overrideQuestion ?? searchQ).trim();
    if (!question || searching) return;
    setSearching(true);
    setSearchResults(null);
    try {
      let res;
      try {
        // New public-search endpoint: works for anonymous (IP rate-limited)
        // and authenticated users (no quota decrement). Keeps the chat
        // endpoint as the only LLM-cost path.
        res = await apiFetch(`/shows/${show.id}/search`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ question }),
        });
      } catch (netErr) {
        throw new Error(networkErrorMessage(lang));
      }
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(formatError(body, lang));
      }
      const data = await res.json();
      const mapped = (data.results || []).map(r => ({
        epId: r.episode_id,
        epTitle: r.episode_title,
        startTime: r.start_time,
        timestamp: formatTimestamp(r.start_time),
        text: r.text,
      }));
      setSearchResults(mapped);
    } catch (err) {
      setSearchResults({ error: err.message });
    } finally {
      setSearching(false);
    }
  };

  const showChat = queryMode !== 2;
  const showSearch = queryMode !== 1;
  const effectiveTabs = [showChat && 'chat', showSearch && 'search'].filter(Boolean);
  const curTab = effectiveTabs.includes(activeTab) ? activeTab : effectiveTabs[0];
  const showName = show.title;
  const transcribedCount = show.transcribed_count || 0;
  const showColor = deriveColor(show.id);
  const epCount = episodes
    ? episodes.filter(e => e.transcript_status === 'completed').length
    : transcribedCount;

  // R1.1: fire-and-forget citation_click event. sendBeacon if available,
  // else fetch keepalive. Navigation always proceeds regardless.
  const sendCitationBeacon = (query_id, chunk_id, position) => {
    if (!query_id || !chunk_id) return;
    const body = JSON.stringify({
      event_type: 'citation_click',
      payload: { query_id, chunk_id, position },
    });
    const url = `${API_BASE}/events`;
    try {
      if (navigator.sendBeacon) {
        const blob = new Blob([body], { type: 'application/json' });
        navigator.sendBeacon(url, blob);
        return;
      }
    } catch (_) { /* fall through to fetch keepalive */ }
    try {
      fetch(url, {
        method: 'POST',
        keepalive: true,
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body,
      }).catch(() => {});
    } catch (_) { /* swallow — beacon is best-effort */ }
  };

  const onCitationClick = (citation, query_id, position) => {
    const chunk_id = citation.episode_id != null && citation.start_time != null
      ? `ep:${citation.episode_id}@${citation.start_time.toFixed(2)}`
      : null;
    sendCitationBeacon(query_id, chunk_id, position);
    onOpenEpisode({ id: citation.episode_id, title: citation.episode_title }, citation.start_time);
  };

  // R1.1: thumbs vote handler. Fires POST /qa-feedback; on 201 updates local
  // 'votes' state so the UI reflects the latest vote (re-vote allowed).
  const submitVote = async (query_id, vote, comment) => {
    if (!user || !query_id) return;
    try {
      const res = await apiFetch('/qa-feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query_id, vote, comment: comment || null }),
      });
      if (res.ok) {
        setVotes(v => ({ ...v, [query_id]: vote }));
      }
    } catch (_) { /* network error: silently ignore; user can retry */ }
  };

  // R1.1: admin-only stats fetch — run once when an AI answer is present.
  React.useEffect(() => {
    if (adminStatsFetchedRef.current) return;
    if (!user || user.role !== 'admin') return;
    const hasAnswer = messages.some(m => m.role === 'assistant' && m.query_id);
    if (!hasAnswer) return;
    adminStatsFetchedRef.current = true;
    (async () => {
      try {
        const res = await apiFetch('/qa-feedback/stats');
        if (res.ok) setAdminStats(await res.json());
      } catch (_) { /* ignore */ }
    })();
  }, [user, messages]);

  const leftContent = (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      {/* Quota meter — authenticated only. Anon visitors see no meter (no
          quota concept until they sign in). */}
      {user && <QuotaMeter user={user} lang={lang} onApply={() => setQuotaModalOpen(true)} />}

      {/* Tab bar */}
      {effectiveTabs.length > 1 && (
        <div style={{ display: 'flex', gap: 0, borderBottom: `1px solid ${TOKEN.surfaceBorder}`, background: TOKEN.surface, flexShrink: 0 }}>
          {effectiveTabs.map(tab => (
            <button key={tab} onClick={() => setActiveTab(tab)}
              style={{ padding: '13px 20px', background: 'none', border: 'none', borderBottom: `2px solid ${curTab === tab ? TOKEN.accent : 'transparent'}`, color: curTab === tab ? TOKEN.accent : TOKEN.textSecondary, cursor: 'pointer', fontSize: 14, fontWeight: curTab === tab ? 600 : 400, fontFamily: 'inherit', transition: 'all 0.12s' }}>
              {tab === 'chat' ? (t ? '對話查詢' : 'Chat') : (t ? '語意搜尋' : 'Semantic Search')}
            </button>
          ))}
        </div>
      )}

      {/* Chat */}
      {curTab === 'chat' && (
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          {!user ? (
            <LockedAnswerCard lang={lang} />
          ) : (
            <>
              <div ref={chatEndRef} style={{ flex: 1, overflowY: 'auto', padding: '20px 24px', display: 'flex', flexDirection: 'column', gap: 16 }}>
                {user && user.role === 'admin' && messages.some(m => m.role === 'assistant' && m.query_id) && (
                  <div style={{ fontSize: 11, color: TOKEN.textMuted, fontFamily: 'monospace' }}>
                    {adminStats == null
                      ? '[admin] 7d thumbs: …'
                      : adminStats.ratio == null
                        ? '[admin] 7d thumbs: no data'
                        : `[admin] 7d thumbs: ${adminStats.up_7d}↑ ${adminStats.down_7d}↓ (${Math.round(adminStats.ratio * 100)}%)`}
                  </div>
                )}
                {messages.map((msg, i) => (
                  <ChatBubble key={i} msg={msg} lang={lang} user={user}
                    onCitationClick={onCitationClick}
                    voted={msg.query_id ? votes[msg.query_id] : undefined}
                    onVote={submitVote} />
                ))}
                {sending && <TypingIndicator />}
              </div>
              <div style={{ padding: '14px 24px', borderTop: `1px solid ${TOKEN.surfaceBorder}`, background: TOKEN.surface, flexShrink: 0 }}>
                <div style={{ display: 'flex', gap: 8 }}>
                  <Input value={chatInput} onChange={e => setChatInput(e.target.value)}
                    placeholder={quotaExhausted ? (t ? '查詢額度已用完' : 'Quota exhausted') : (t ? '針對此節目內容提問...' : 'Ask anything about this show...')}
                    onKeyDown={e => e.key === 'Enter' && handleSend()} />
                  <Btn onClick={handleSend} disabled={sending || !chatInput.trim() || quotaExhausted} icon="send">{t ? '送出' : 'Send'}</Btn>
                </div>
                <p style={{ margin: '7px 0 0', fontSize: 12, color: quotaExhausted ? TOKEN.danger : TOKEN.textMuted }}>
                  {quotaExhausted
                    ? (t ? '查詢額度已用完，可從上方申請更多' : 'Quota exhausted — request more above')
                    : (t ? `RAG 範圍：${transcribedCount} 集逐字稿 · 剩餘 ${user.quota_remaining} 次` : `RAG scope: ${transcribedCount} transcripts · ${user.quota_remaining} queries left`)}
                </p>
              </div>
            </>
          )}
        </div>
      )}

      {/* Search */}
      {curTab === 'search' && (
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          <div style={{ padding: '16px 24px', borderBottom: `1px solid ${TOKEN.surfaceBorder}`, background: TOKEN.surface, flexShrink: 0 }}>
            <div style={{ display: 'flex', gap: 8 }}>
              <Input value={searchQ} onChange={e => setSearchQ(e.target.value)}
                placeholder={t ? '輸入關鍵字或語意搜尋...' : 'Keyword or semantic search...'}
                icon="search" onKeyDown={e => e.key === 'Enter' && handleSearch()} />
              <Btn onClick={() => handleSearch()} disabled={searching || !searchQ.trim()}>{t ? '搜尋' : 'Search'}</Btn>
            </div>
            {!user && (
              <p style={{ margin: '7px 0 0', fontSize: 12, color: TOKEN.textMuted }}>
                {t
                  ? '段落搜尋免登入。想看 AI 整段統整？登入解鎖（30 次免費）'
                  : 'Segment search is free. Want AI-summarized answers? Log in to unlock (30 free).'}
              </p>
            )}
          </div>
          <div style={{ flex: 1, overflowY: 'auto', padding: '16px 24px' }}>
            {searching && <div style={{ color: TOKEN.textMuted, textAlign: 'center', padding: '40px 0' }}>{t ? '搜尋中...' : 'Searching...'}</div>}
            {searchResults && searchResults.error && (
              <div style={{ color: TOKEN.danger, textAlign: 'center', padding: '24px 0', fontSize: 13 }}>
                {t ? `搜尋失敗：${searchResults.error}` : `Search failed: ${searchResults.error}`}
              </div>
            )}
            {Array.isArray(searchResults) && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                <p style={{ color: TOKEN.textMuted, fontSize: 13, margin: '0 0 4px' }}>{t ? `找到 ${searchResults.length} 個相關片段` : `Found ${searchResults.length} segments`}</p>
                {searchResults.map((r, i) => (
                  <SearchResultCard key={i} result={r} lang={lang} query={searchQ} />
                ))}
              </div>
            )}
            {!searching && !searchResults && (
              <div style={{ color: TOKEN.textMuted, textAlign: 'center', padding: '60px 0' }}>
                <Icon name="search" size={36} color={TOKEN.textMuted} />
                <p style={{ marginTop: 12, fontSize: 14 }}>{t ? '輸入關鍵字開始搜尋' : 'Enter a keyword to search'}</p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );

  const rightContent = (() => {
    if (epError) return (
      <div style={{ color: TOKEN.danger, fontSize: 12, padding: '12px 4px' }}>
        {lang === 'zh' ? `載入失敗：${epError}` : `Load error: ${epError}`}
      </div>
    );
    if (episodes === null) return (
      <div style={{ color: TOKEN.textMuted, fontSize: 12, padding: '12px 4px' }}>
        {lang === 'zh' ? '載入中...' : 'Loading...'}
      </div>
    );
    return episodes.map(ep => (
      <EpisodeCard key={ep.id} ep={ep} lang={lang} selected={selectedEp === ep.id}
        onClick={() => ep.transcript_status === 'completed' && (setSelectedEp(ep.id), onOpenEpisode(ep, null))} />
    ));
  })();

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', background: TOKEN.bg }}>
      {/* Top bar */}
      <div style={{ padding: isMobile ? '0 12px' : '0 24px', height: 52, borderBottom: `1px solid ${TOKEN.surfaceBorder}`, display: 'flex', alignItems: 'center', gap: isMobile ? 8 : 14, background: TOKEN.surface, flexShrink: 0 }}>
        <Btn variant="ghost" size="sm" icon="arrowLeft" onClick={onBack}>{isMobile ? '' : (t ? '返回' : 'Back')}</Btn>
        {!isMobile && <div style={{ width: 1, height: 20, background: TOKEN.surfaceBorder }} />}
        <div style={{ width: 24, height: 24, borderRadius: 6, background: showColor + '22', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
          <Icon name="mic" size={13} color={showColor} />
        </div>
        <span style={{ color: TOKEN.text, fontWeight: 600, fontSize: 14, flex: isMobile ? 1 : 'none', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{showName}</span>
        {!isMobile && <Badge variant="default">{transcribedCount} {t ? '集已轉錄' : 'transcribed'}</Badge>}
        {isMobile && (
          <button onClick={() => setDrawerOpen(true)} aria-label={t ? '集數列表' : 'Episodes'}
            style={{ width: 44, height: 44, borderRadius: 8, background: TOKEN.surfaceRaised, border: `1px solid ${TOKEN.surfaceBorder}`, color: TOKEN.textSecondary, cursor: 'pointer', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', padding: 0, flexShrink: 0 }}>
            <Icon name="list" size={18} color="currentColor" />
          </button>
        )}
      </div>

      <ResizableLayout lang={lang} leftContent={leftContent} rightContent={rightContent} epCount={epCount} epTotal={show.episode_count || 0} drawerOpen={drawerOpen} setDrawerOpen={setDrawerOpen} />

      <QuotaApplyModal open={quotaModalOpen} lang={lang} onClose={() => setQuotaModalOpen(false)} />
    </div>
  );
};

// ── Sub-components ──
const ChatBubble = ({ msg, lang, user, onCitationClick, voted, onVote }) => {
  const t = lang === 'zh';
  const isUser = msg.role === 'user';
  const citations = msg.citations || [];
  const queryId = msg.query_id;
  const [showCommentBox, setShowCommentBox] = React.useState(false);
  const [commentText, setCommentText] = React.useState('');
  const [submitting, setSubmitting] = React.useState(false);

  const canVote = !!user && !!queryId;
  const upActive = voted === 'up';
  const downActive = voted === 'down';

  const handleUpClick = () => {
    if (!canVote) return;
    setShowCommentBox(false);
    onVote && onVote(queryId, 'up', null);
  };
  const handleDownClick = () => {
    if (!canVote) return;
    setShowCommentBox(true);
  };
  const handleSendComment = async () => {
    if (!canVote || submitting) return;
    setSubmitting(true);
    await (onVote && onVote(queryId, 'down', commentText.trim() || null));
    setSubmitting(false);
    setShowCommentBox(false);
    setCommentText('');
  };

  const thumbBtnStyle = (active, disabled) => ({
    display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
    width: 28, height: 28, borderRadius: 6,
    background: active ? TOKEN.accentDim : 'transparent',
    border: `1px solid ${active ? TOKEN.accent : TOKEN.surfaceBorder}`,
    color: active ? TOKEN.accent : (disabled ? TOKEN.textMuted : TOKEN.textSecondary),
    cursor: disabled ? 'not-allowed' : 'pointer',
    fontSize: 14, padding: 0,
    transition: 'all 0.12s',
  });

  return (
    <div style={{ display: 'flex', flexDirection: isUser ? 'row-reverse' : 'row', gap: 10, alignItems: 'flex-start' }}>
      <div style={{ width: 28, height: 28, borderRadius: '50%', background: isUser ? TOKEN.accentDim : TOKEN.surfaceRaised, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, fontSize: 11, fontWeight: 700, color: isUser ? TOKEN.accent : TOKEN.textSecondary }}>
        {isUser ? 'U' : 'AI'}
      </div>
      <div style={{ maxWidth: '80%', background: isUser ? TOKEN.accentDim : TOKEN.surfaceRaised, border: `1px solid ${isUser ? TOKEN.accent + '33' : TOKEN.surfaceBorder}`, borderRadius: isUser ? '14px 4px 14px 14px' : '4px 14px 14px 14px', padding: '10px 14px' }}>
        <pre style={{ margin: 0, color: TOKEN.text, fontSize: 13, lineHeight: 1.7, fontFamily: 'inherit', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{msg.text}</pre>
        {citations.length > 0 && (
          <div style={{ display: 'flex', gap: 6, marginTop: 10, flexWrap: 'wrap' }}>
            {citations.map((c, i) => (
              <span key={i} onClick={() => onCitationClick && onCitationClick(c, queryId, i)}
                style={{ display: 'inline-flex', alignItems: 'center', gap: 4, padding: '3px 8px', background: TOKEN.bg, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 6, color: TOKEN.accent, fontSize: 12, fontFamily: 'inherit', cursor: onCitationClick ? 'pointer' : 'default', transition: 'border-color 0.15s' }}
                onMouseEnter={e => onCitationClick && (e.currentTarget.style.borderColor = TOKEN.accent)}
                onMouseLeave={e => onCitationClick && (e.currentTarget.style.borderColor = TOKEN.surfaceBorder)}>
                <Icon name="fileText" size={11} color={TOKEN.accent} />
                {(c.episode_title || '').slice(0, 24) || (lang === 'zh' ? '片段' : 'Clip')} @ {formatTimestamp(c.start_time)}
              </span>
            ))}
          </div>
        )}
        {!isUser && queryId && (
          <div style={{ marginTop: 10, display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
            <button type="button" onClick={handleUpClick} disabled={!canVote}
              title={!canVote ? (t ? '登入後可投票' : 'Sign in to vote') : (t ? '有用' : 'Helpful')}
              style={thumbBtnStyle(upActive, !canVote)}>👍</button>
            <button type="button" onClick={handleDownClick} disabled={!canVote}
              title={!canVote ? (t ? '登入後可投票' : 'Sign in to vote') : (t ? '不太準' : 'Not quite right')}
              style={thumbBtnStyle(downActive, !canVote)}>👎</button>
            {voted && (
              <span style={{ fontSize: 11, color: TOKEN.textMuted, marginLeft: 4 }}>
                {t ? '已收到 ✓' : 'Recorded ✓'}
              </span>
            )}
          </div>
        )}
        {!isUser && queryId && showCommentBox && canVote && (
          <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
            <textarea
              value={commentText}
              onChange={e => setCommentText(e.target.value)}
              placeholder={t ? '想說什麼？(可空白)' : 'Anything to add? (optional)'}
              maxLength={2000}
              rows={2}
              style={{ resize: 'vertical', padding: '6px 8px', fontSize: 12, fontFamily: 'inherit', color: TOKEN.text, background: TOKEN.bg, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 6 }}
            />
            <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
              <Btn variant="ghost" size="sm" onClick={() => { setShowCommentBox(false); setCommentText(''); }} disabled={submitting}>
                {t ? '取消' : 'Cancel'}
              </Btn>
              <Btn variant="primary" size="sm" onClick={handleSendComment} disabled={submitting}>
                {t ? '送出' : 'Send'}
              </Btn>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

const TypingIndicator = () => (
  <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
    <div style={{ width: 28, height: 28, borderRadius: '50%', background: TOKEN.surfaceRaised, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11, fontWeight: 700, color: TOKEN.textSecondary }}>AI</div>
    <div style={{ background: TOKEN.surfaceRaised, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: '4px 14px 14px 14px', padding: '12px 16px', display: 'flex', gap: 5, alignItems: 'center' }}>
      {[0,1,2].map(i => <span key={i} style={{ width: 6, height: 6, borderRadius: '50%', background: TOKEN.textMuted, animation: `bounce 1s ${i * 0.2}s infinite` }} />)}
    </div>
  </div>
);

const SearchResultCard = ({ result, lang, query }) => {
  const hi = text => {
    if (!query) return text;
    const parts = text.split(new RegExp(`(${query})`, 'gi'));
    return parts.map((p, i) => p.toLowerCase() === query.toLowerCase()
      ? <mark key={i} style={{ background: TOKEN.accent + '44', color: TOKEN.accentHover, borderRadius: 2 }}>{p}</mark>
      : p);
  };
  return (
    <div style={{ background: TOKEN.surface, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 10, padding: '14px 16px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
        <span style={{ color: TOKEN.textSecondary, fontSize: 12, flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{result.epTitle}</span>
        <span style={{ color: TOKEN.textMuted, fontSize: 12, display: 'flex', alignItems: 'center', gap: 3, flexShrink: 0 }}>
          <Icon name="clock" size={11} /> {result.timestamp}
        </span>
      </div>
      <p style={{ margin: 0, color: TOKEN.text, fontSize: 13, lineHeight: 1.6 }}>{hi(result.text)}</p>
    </div>
  );
};

const EpisodeCard = ({ ep, lang, selected, onClick }) => {
  const t = lang === 'zh';
  const [hovered, setHovered] = React.useState(false);
  const done = ep.transcript_status === 'completed';
  const dateStr = ep.published_at ? ep.published_at.slice(0, 10) : '';
  const durStr = ep.duration_seconds != null ? formatTimestamp(ep.duration_seconds) : '--:--';
  return (
    <div onClick={onClick} onMouseEnter={() => setHovered(true)} onMouseLeave={() => setHovered(false)}
      style={{ background: selected ? TOKEN.accentDim : hovered && done ? TOKEN.surfaceRaised : 'transparent', border: `1px solid ${selected ? TOKEN.accent + '55' : hovered && done ? TOKEN.surfaceBorder : 'transparent'}`, borderRadius: 10, padding: '10px 12px', cursor: done ? 'pointer' : 'default', opacity: done ? 1 : 0.45, transition: 'all 0.12s', marginBottom: 6 }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <p style={{ margin: '0 0 4px', color: TOKEN.text, fontSize: 13, fontWeight: 500, lineHeight: 1.35 }}>
            {ep.title}
          </p>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <span style={{ color: TOKEN.textMuted, fontSize: 11 }}>{dateStr}</span>
            <span style={{ color: TOKEN.textMuted, fontSize: 11, display: 'flex', alignItems: 'center', gap: 2 }}><Icon name="clock" size={10} />{durStr}</span>
            {done ? <Badge variant="success">{t ? '已轉錄' : 'Done'}</Badge> : <Badge variant="muted">{t ? '待轉錄' : 'Pending'}</Badge>}
          </div>
          <EpisodeBlurb episode={ep} lang={lang} style={{ marginTop: 6, fontSize: 11, WebkitLineClamp: 2 }} />
        </div>
        {done && <Icon name="chevronRight" size={14} color={selected ? TOKEN.accent : TOKEN.textMuted} style={{ flexShrink: 0, marginTop: 3 }} />}
      </div>
    </div>
  );
};

Object.assign(window, { QueryPage, MOCK_EPISODES });
