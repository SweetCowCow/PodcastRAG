// HomePage — landing-and-mode-orchestration-redesign decision 1.
//
// Single component that replaces the old LandingPage + PodcastSelect pair.
// Hero swaps based on auth state:
//   user === null  → marketing hero + Google login CTA
//   user           → personalized greeting + remaining quota badge
//
// Middle band:                  ModeTrioIntro
// Bottom band:                  Show grid (always rendered; not auth-gated)
// On each show card:            TrendingQueriesChips (silent if empty)
//
// Anonymous visitors who pick a show land on QueryPage with `index` tab
// pre-selected (decision 2). The HomePage itself stays agnostic — it only
// hands the show + an optional pre-fill query to the parent.

// Reuse the ShowCard exported from PodcastSelect (window.ShowCard) so we
// don't duplicate the card visual — keeps consistency until that file is
// retired. PodcastSelect.jsx still ships ShowCard via window.

const HomePage = ({
  lang,
  user,
  userLoading,
  onSelectShow,
  onSearchPrefill,   // (query) — stash for QueryPage initial value
  onSignIn,
  onOpenApplyQuota,
}) => {
  const t = lang === 'zh';
  const { isMobile } = useViewport();
  const [shows, setShows] = React.useState(null);
  const [showsError, setShowsError] = React.useState(null);
  const [searchInput, setSearchInput] = React.useState('');
  const [hovered, setHovered] = React.useState(null);
  const showsRef = React.useRef(null);

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await apiFetch('/shows');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (!cancelled) setShows(data);
      } catch (err) {
        if (!cancelled) setShowsError(err.message);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const handleSearchSubmit = (e) => {
    if (e && e.preventDefault) e.preventDefault();
    onSearchPrefill && onSearchPrefill(searchInput.trim());
    if (showsRef.current) {
      showsRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  };

  const totalEpisodes = (shows || []).reduce((acc, s) => acc + (s.episode_count || 0), 0);
  const totalTranscribed = (shows || []).reduce((acc, s) => acc + (s.transcribed_count || 0), 0);

  // ─── Loading guard ───
  // Wait for /me to resolve so the hero doesn't flash from「marketing」→
  //「personalized」on hard refresh.
  if (userLoading) {
    return (
      <div style={{
        flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
        color: TOKEN.textMuted, fontSize: 14,
      }}>
        ⏳ {t ? '載入中…' : 'Loading…'}
      </div>
    );
  }

  return (
    <div
      data-testid="home-page"
      data-auth={user ? 'signed-in' : 'anon'}
      style={{
        flex: 1,
        overflowY: 'auto',
        background: TOKEN.bg,
        color: TOKEN.text,
      }}
    >
      {/* ─── Hero (auth-state swap) ─── */}
      {user ? (
        <HomeHeroSignedIn lang={lang} user={user} isMobile={isMobile} onOpenApplyQuota={onOpenApplyQuota} />
      ) : (
        <HomeHeroAnon
          lang={lang}
          isMobile={isMobile}
          searchInput={searchInput}
          setSearchInput={setSearchInput}
          onSubmit={handleSearchSubmit}
          onSignIn={onSignIn}
          showsCount={shows ? shows.length : 0}
          totalEpisodes={totalEpisodes}
          totalTranscribed={totalTranscribed}
        />
      )}

      {/* ─── Mode trio educational band ─── */}
      <ModeTrioIntro lang={lang} />

      {/* ─── Collected shows ─── */}
      <section ref={showsRef} style={{
        padding: isMobile ? '24px 16px 56px' : '32px 24px 80px',
        maxWidth: 1100,
        margin: '0 auto',
      }}>
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 12,
          marginBottom: 24,
        }}>
          <div style={{ flex: 1, height: 1, background: TOKEN.surfaceBorder, maxWidth: 80 }} />
          <span style={{
            fontSize: 12,
            color: TOKEN.textSecondary,
            letterSpacing: '0.1em',
            textTransform: 'uppercase',
            fontWeight: 600,
          }}>
            {t ? '收錄節目' : 'Collected Shows'}
          </span>
          <div style={{ flex: 1, height: 1, background: TOKEN.surfaceBorder, maxWidth: 80 }} />
        </div>

        {showsError && (
          <p style={{ color: TOKEN.textSecondary, textAlign: 'center' }}>
            {t ? '載入節目失敗：' : 'Failed to load shows: '}{showsError}
          </p>
        )}
        {!shows && !showsError && (
          <p style={{ color: TOKEN.textMuted, textAlign: 'center' }}>{t ? '載入中…' : 'Loading…'}</p>
        )}
        {shows && shows.length === 0 && (
          <p style={{ color: TOKEN.textSecondary, textAlign: 'center' }}>
            {t ? '目前還沒有可瀏覽的節目' : 'No shows available yet'}
          </p>
        )}

        {shows && shows.length > 0 && (
          <div style={{
            display: 'grid',
            gridTemplateColumns: isMobile ? '1fr' : 'repeat(auto-fill, minmax(320px, 1fr))',
            gap: 20,
          }}>
            {shows.map(show => (
              <div key={show.id} style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <ShowCard
                  show={show}
                  lang={lang}
                  hovered={hovered === show.id}
                  onMouseEnter={() => setHovered(show.id)}
                  onMouseLeave={() => setHovered(null)}
                  onClick={() => onSelectShow && onSelectShow(show)}
                />
                <TrendingQueriesChips
                  showId={show.id}
                  lang={lang}
                  onSelect={(q) => {
                    onSearchPrefill && onSearchPrefill(q);
                    onSelectShow && onSelectShow(show);
                  }}
                />
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
};

// ─── Hero (anonymous) ────────────────────────────────────────────────
const HomeHeroAnon = ({
  lang, isMobile, searchInput, setSearchInput, onSubmit, onSignIn,
  showsCount, totalEpisodes, totalTranscribed,
}) => {
  const t = lang === 'zh';
  return (
    <section
      data-testid="home-hero-anon"
      style={{
        padding: isMobile ? '40px 20px 32px' : '80px 40px 56px',
        maxWidth: 960,
        margin: '0 auto',
        textAlign: 'center',
      }}
    >
      <h1 style={{
        fontSize: isMobile ? 26 : 42,
        fontWeight: 800,
        lineHeight: 1.25,
        margin: '0 0 18px',
        letterSpacing: '-0.02em',
      }}>
        {t
          ? <>「那個來賓說過什麼？」<br />別再瘋狂快轉了。</>
          : <>"What did that guest say?"<br />Stop fast-forwarding through podcasts.</>}
      </h1>
      <p style={{
        fontSize: isMobile ? 14 : 17,
        color: TOKEN.textSecondary,
        margin: '0 0 28px',
        lineHeight: 1.6,
      }}>
        {t
          ? '忘記在哪一集沒關係。直接問，從節目片段中找回那道遺忘的靈光一閃。'
          : 'Forgotten which episode? Just ask — find the moment of insight instantly.'}
      </p>
      <form onSubmit={onSubmit} style={{
        display: 'flex',
        flexDirection: isMobile ? 'column' : 'row',
        gap: 10,
        maxWidth: 720,
        margin: '0 auto 16px',
      }}>
        <input
          type="text"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          placeholder={t ? '直接輸入想找的關鍵字或問題…' : 'Type a keyword or question…'}
          style={{
            flex: 1,
            padding: '12px 16px',
            fontSize: 14,
            borderRadius: 10,
            border: `1px solid ${TOKEN.surfaceBorder}`,
            background: TOKEN.surfaceRaised,
            color: TOKEN.text,
          }}
        />
        <Btn variant="secondary" size="lg" onClick={onSubmit}>
          {t ? '挑一個節目找找看' : 'Pick a show'}
        </Btn>
      </form>
      <div style={{ display: 'flex', justifyContent: 'center', gap: 10, flexWrap: 'wrap' }}>
        <Btn variant="primary" size="md" onClick={onSignIn} data-testid="home-hero-anon-login">
          {t ? '以 Google 登入解鎖對話模式' : 'Sign in with Google to unlock chat'}
        </Btn>
      </div>
      {showsCount > 0 && (
        <p style={{ marginTop: 18, fontSize: 12, color: TOKEN.textMuted }}>
          {t
            ? `已索引 ${showsCount} 個節目、${totalEpisodes} 集、${totalTranscribed} 集已轉錄`
            : `${showsCount} shows · ${totalEpisodes} episodes · ${totalTranscribed} transcribed`}
        </p>
      )}
    </section>
  );
};

// ─── Hero (signed in) ────────────────────────────────────────────────
const HomeHeroSignedIn = ({ lang, user, isMobile, onOpenApplyQuota }) => {
  const t = lang === 'zh';
  const name = (user && (user.display_name || user.name || user.email)) || '';
  const remaining = (user && typeof user.quota_remaining === 'number') ? user.quota_remaining : null;
  return (
    <section
      data-testid="home-hero-signed-in"
      style={{
        padding: isMobile ? '32px 20px 24px' : '56px 40px 40px',
        maxWidth: 1100,
        margin: '0 auto',
        display: 'flex',
        gap: 16,
        flexDirection: isMobile ? 'column' : 'row',
        alignItems: isMobile ? 'flex-start' : 'center',
      }}
    >
      <div style={{ flex: 1 }}>
        <p style={{
          margin: 0, fontSize: 12, color: TOKEN.textMuted, letterSpacing: '0.05em',
          textTransform: 'uppercase', fontWeight: 600,
        }}>
          {t ? '歡迎回來' : 'Welcome back'}
        </p>
        <h1 style={{
          margin: '6px 0 8px', fontSize: isMobile ? 22 : 28, fontWeight: 700, color: TOKEN.text,
        }}>
          {t ? `嗨，${name}` : `Hi, ${name}`}
        </h1>
        <p style={{ margin: 0, color: TOKEN.textSecondary, fontSize: 14, lineHeight: 1.6 }}>
          {t ? '挑一個節目開始查詢，或直接點熱搜 chip 試試。' : 'Pick a show below to start, or try a trending chip.'}
        </p>
      </div>
      <div style={{
        background: TOKEN.surface,
        border: `1px solid ${TOKEN.surfaceBorder}`,
        borderRadius: 12,
        padding: '14px 18px',
        minWidth: 200,
        display: 'flex',
        flexDirection: 'column',
        gap: 6,
      }}>
        <span style={{ fontSize: 11, color: TOKEN.textMuted, letterSpacing: '0.04em' }}>
          {t ? '對話模式剩餘額度' : 'Chat quota remaining'}
        </span>
        <span style={{ fontSize: 22, fontWeight: 700, color: remaining === 0 ? TOKEN.danger || '#f87171' : TOKEN.text }}>
          {remaining == null ? '—' : remaining}
        </span>
        {remaining === 0 && (
          <Btn variant="secondary" size="sm" onClick={onOpenApplyQuota}>
            {t ? '申請更多次數' : 'Request more'}
          </Btn>
        )}
      </div>
    </section>
  );
};

Object.assign(window, { HomePage });
