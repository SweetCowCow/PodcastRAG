// LandingPage — public-facing root for unauthenticated visitors. Once /me
// resolves to a user the App swaps in PodcastSelect; this component never
// renders for logged-in users.
const LandingPage = ({ lang, onSearch, onSelectShow }) => {
  const t = lang === 'zh';
  const { isMobile } = useViewport();
  const [shows, setShows] = React.useState(null);
  const [showsError, setShowsError] = React.useState(null);
  const [query, setQuery] = React.useState('');
  const [hovered, setHovered] = React.useState(null);

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await apiFetch(`/shows`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (!cancelled) setShows(data);
      } catch (err) {
        if (!cancelled) setShowsError(err.message);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const showsRef = React.useRef(null);

  const handleSubmit = (e) => {
    if (e && e.preventDefault) e.preventDefault();
    onSearch && onSearch(query.trim());
    // Scroll to the show cards so anonymous visitors can pick a show to
    // search inside. Per LandingPage spec the typed query is preserved
    // (stashed in App state) for QueryPage pre-fill.
    if (showsRef.current) {
      showsRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  };

  const totalEpisodes = (shows || []).reduce(
    (acc, s) => acc + (s.episode_count || 0), 0,
  );
  const totalTranscribed = (shows || []).reduce(
    (acc, s) => acc + (s.transcribed_count || 0), 0,
  );

  return (
    <div style={{
      flex: 1,
      overflowY: 'auto',
      background: TOKEN.bg,
      color: TOKEN.text,
    }}>
      {/* ─── Hero ─── */}
      <section style={{
        padding: isMobile ? '48px 20px 56px' : '96px 40px 80px',
        maxWidth: 960,
        margin: '0 auto',
        textAlign: 'center',
      }}>
        <h1 style={{
          fontSize: isMobile ? 28 : 44,
          fontWeight: 800,
          lineHeight: 1.25,
          margin: '0 0 20px',
          letterSpacing: '-0.02em',
        }}>
          {t
            ? <>「那個來賓說過什麼？」<br />別再瘋狂快轉了。</>
            : <>"What did that guest say?"<br />Stop fast-forwarding through podcasts.</>}
        </h1>
        <p style={{
          fontSize: isMobile ? 15 : 18,
          color: TOKEN.textSecondary,
          margin: '0 0 32px',
          lineHeight: 1.6,
        }}>
          {t
            ? '忘記在哪一集沒關係。直接問，從節目片段中找回那道遺忘的靈光一閃，瞬間解開你的疑惑。'
            : 'Forgotten which episode it was in? Just ask. Find the moment of insight you remember, instantly.'}
        </p>

        <form onSubmit={handleSubmit} style={{
          display: 'flex',
          flexDirection: isMobile ? 'column' : 'row',
          gap: 12,
          maxWidth: 720,
          margin: '0 auto',
        }}>
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t
              ? '例如：在 這又沒有很屌 查詢「歌單」'
              : 'Example: search "playlist" in 這又沒有很屌'}
            style={{
              flex: 1,
              padding: '14px 18px',
              fontSize: 15,
              borderRadius: 10,
              border: `1px solid ${TOKEN.surfaceBorder}`,
              background: TOKEN.surfaceRaised,
              color: TOKEN.text,
            }}
          />
          <Btn variant="primary" size="lg" onClick={handleSubmit}>
            {t ? '找回靈光一閃' : 'Bring back the insight'}
          </Btn>
        </form>

        {shows && shows.length > 0 && (
          <p style={{
            marginTop: 20,
            fontSize: 13,
            color: TOKEN.textMuted,
          }}>
            {t
              ? `已索引 ${shows.length} 個節目、${totalEpisodes} 集、${totalTranscribed} 集已轉錄`
              : `${shows.length} shows indexed · ${totalEpisodes} episodes · ${totalTranscribed} transcribed`}
          </p>
        )}
      </section>

      {/* ─── Collected Shows ─── */}
      <section ref={showsRef} style={{
        padding: isMobile ? '32px 20px' : '40px 40px',
        maxWidth: 1100,
        margin: '0 auto',
      }}>
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 12,
          marginBottom: 28,
        }}>
          <div style={{ flex: 1, height: 1, background: TOKEN.surfaceBorder, maxWidth: 80 }} />
          <span style={{
            fontSize: 13,
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
              <ShowCard key={show.id} show={show} lang={lang} hovered={hovered === show.id}
                onMouseEnter={() => setHovered(show.id)}
                onMouseLeave={() => setHovered(null)}
                onClick={() => onSelectShow && onSelectShow(show)} />
            ))}
          </div>
        )}
      </section>

      {/* ─── Paywall band ─── */}
      <section style={{
        padding: isMobile ? '32px 20px 56px' : '64px 40px 96px',
      }}>
        <div style={{
          maxWidth: 720,
          margin: '0 auto',
          background: TOKEN.surface,
          border: `1px solid ${TOKEN.surfaceBorder}`,
          borderRadius: 16,
          padding: isMobile ? '32px 24px' : '40px 48px',
          textAlign: 'center',
          width: isMobile ? '90%' : 'auto',
        }}>
          <div style={{ fontSize: 36, marginBottom: 12 }}>💎</div>
          <h2 style={{
            fontSize: isMobile ? 18 : 22,
            fontWeight: 700,
            margin: '0 0 16px',
            color: TOKEN.text,
            lineHeight: 1.4,
          }}>
            {t
              ? '登入解鎖：30 次 AI 統整回答'
              : 'Log in to unlock: 30 free AI summary answers'}
          </h2>
          <p style={{
            fontSize: 14,
            color: TOKEN.textSecondary,
            lineHeight: 1.6,
            margin: '0 0 28px',
          }}>
            {t
              ? '瀏覽逐字稿、看相關段落都不用登入。只有「請 AI 統整回答」需要登入使用額度。'
              : 'Browsing transcripts and matched segments needs no login. Only "Ask AI to summarize" requires login and uses your quota.'}
          </p>
          <Btn variant="primary" size="lg" onClick={() => { window.location.href = googleLoginUrl(); }}>
            {t ? '以 Google 登入 →' : 'Sign in with Google →'}
          </Btn>
        </div>
      </section>
    </div>
  );
};

Object.assign(window, { LandingPage });
