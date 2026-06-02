// Main App — top nav layout + Google SSO auth gate
const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "queryMode": 0,
  "defaultLang": "zh",
  "accentColor": "#6366f1"
}/*EDITMODE-END*/;

// ── Main App ──
const App = () => {
  const [lang, setLang] = React.useState(TWEAK_DEFAULTS.defaultLang || 'zh');
  const [page, setPage] = React.useState('select');
  const [selectedShow, setSelectedShow] = React.useState(null);
  const [selectedEpisode, setSelectedEpisode] = React.useState(null);
  const [initSearch, setInitSearch] = React.useState('');
  const [highlightTime, setHighlightTime] = React.useState(null);
  const [tweaksVisible, setTweaksVisible] = React.useState(false);
  const [tweaks, setTweaks] = React.useState(TWEAK_DEFAULTS);
  const [landingQuery, setLandingQuery] = React.useState('');
  const { user, loading: userLoading, refresh: refreshUser, logout: doLogout } = useCurrentUser();
  const isAdmin = user && user.role === 'admin' && user.status === 'active';

  // ── disabled-user-appeal-flow: detect OAuth-callback redirect with auth_error ──
  // Backend (auth.py) redirects disabled users to frontend with
  // ?auth_error=account_disabled&appeal_enabled=1&email=... — we render the
  // Lock card disabled state + open AppealModal on click.
  const [disabledAuth, setDisabledAuth] = React.useState(null); // { email, appealEnabled }
  const [appealOpen, setAppealOpen] = React.useState(false);
  React.useEffect(() => {
    try {
      const params = new URL(window.location.href).searchParams;
      if (params.get('auth_error') === 'account_disabled') {
        const email = params.get('email') || '';
        const appealEnabled = params.get('appeal_enabled') !== '0';
        setDisabledAuth({ email, appealEnabled });
        // Strip params so reload doesn't re-trigger.
        const url = new URL(window.location.href);
        url.searchParams.delete('auth_error');
        url.searchParams.delete('appeal_enabled');
        url.searchParams.delete('email');
        window.history.replaceState({}, '', url.toString());
      }
    } catch (_) { /* ignore */ }
  }, []);

  React.useEffect(() => {
    const handler = (e) => {
      if (e.data?.type === '__activate_edit_mode') setTweaksVisible(true);
      if (e.data?.type === '__deactivate_edit_mode') setTweaksVisible(false);
    };
    window.addEventListener('message', handler);
    window.parent.postMessage({ type: '__edit_mode_available' }, '*');
    return () => window.removeEventListener('message', handler);
  }, []);

  // Presentation routing via URL hash. `#presentation` shows fullscreen deck;
  // clearing the hash exits back to the previous page (state preserved).
  const [prevPage, setPrevPage] = React.useState('select');
  React.useEffect(() => {
    const sync = () => {
      if (window.location.hash === '#presentation') {
        setPage(p => {
          if (p !== 'presentation') setPrevPage(p);
          return 'presentation';
        });
      } else {
        setPage(p => (p === 'presentation' ? prevPage : p));
      }
    };
    sync();
    window.addEventListener('hashchange', sync);
    return () => window.removeEventListener('hashchange', sync);
  }, [prevPage]);

  // R2.1-followup section 3: Deep-link receiver. On first load, if URL has
  // ?show_id=&episode_id= (with optional &t=), reconstruct selectedShow +
  // selectedEpisode + highlightTime and route directly to the transcript
  // page. Failure modes (404, network) → toast + clear params + fallback home.
  const [deepLinkLoaded, setDeepLinkLoaded] = React.useState(false);
  React.useEffect(() => {
    if (deepLinkLoaded) return;
    setDeepLinkLoaded(true);  // run exactly once
    let params;
    try {
      params = new URL(window.location.href).searchParams;
    } catch (_) {
      return;
    }
    const showId = params.get('show_id');
    const episodeId = params.get('episode_id');
    const tRaw = params.get('t');
    if (!showId || !episodeId) return;
    const tSec = tRaw != null && !Number.isNaN(parseFloat(tRaw)) ? parseFloat(tRaw) : null;
    (async () => {
      try {
        // Fetch show metadata
        const showsResp = await fetch(`${API_BASE}/shows`);
        if (!showsResp.ok) throw new Error(`shows fetch ${showsResp.status}`);
        const shows = await showsResp.json();
        const show = shows.find(s => s.id === showId);
        if (!show) throw new Error('show not found');
        // Fetch episodes for that show
        const epsResp = await fetch(`${API_BASE}/shows/${showId}/episodes`);
        if (!epsResp.ok) throw new Error(`episodes fetch ${epsResp.status}`);
        const eps = await epsResp.json();
        const ep = eps.find(e => e.id === episodeId);
        if (!ep) throw new Error('episode not found');
        setSelectedShow(show);
        setSelectedEpisode(ep);
        setHighlightTime(tSec);
        setPage('transcript');
      } catch (err) {
        // Silent fallback: clear stale params, route to home. No popup —
        // URL deep-link is meant for share/bookmark, not for manual editing.
        // Malformed URLs just quietly land on landing page.
        try {
          const url = new URL(window.location.href);
          url.searchParams.delete('t');
          url.searchParams.delete('episode_id');
          url.searchParams.delete('show_id');
          window.history.replaceState({}, '', url.toString());
        } catch (_) { /* ignore */ }
        // (Optional dev hint:) console.warn('deep-link load failed:', err);
      }
    })();
  }, [deepLinkLoaded]);

  const applyTweak = (key, val) => {
    setTweaks(t => ({ ...t, [key]: val }));
    window.parent.postMessage({ type: '__edit_mode_set_keys', edits: { [key]: val } }, '*');
  };

  const t = lang === 'zh';

  const handleAdminClick = () => {
    if (!user) { window.location.href = googleLoginUrl(); return; }
    if (!isAdmin) {
      window.alert(t ? '此頁面僅限管理員使用' : 'Admin role required');
      return;
    }
    setPage('admin-api');
  };

  const handleSignIn = () => { window.location.href = googleLoginUrl(); };

  const handleSetPage = (p) => {
    if (p === 'select') { setSelectedShow(null); setSelectedEpisode(null); }
    if (p && p.startsWith('admin') && !isAdmin) {
      // Guard direct hash navigation to admin pages
      if (!user) { window.location.href = googleLoginUrl(); return; }
      window.alert(t ? '此頁面僅限管理員使用' : 'Admin role required');
      return;
    }
    setPage(p);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100dvh', fontFamily: "'Inter', 'Helvetica Neue', Arial, sans-serif", background: TOKEN.bg, overflow: 'hidden' }}>
      <style>{`
        * { box-sizing: border-box; }
        ::-webkit-scrollbar { width: 6px; height: 6px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: ${TOKEN.surfaceBorder}; border-radius: 99px; }
        ::-webkit-scrollbar-thumb:hover { background: ${TOKEN.textMuted}; }
        @keyframes bounce { 0%,80%,100%{transform:scale(0.6);opacity:0.4} 40%{transform:scale(1);opacity:1} }
        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }
        @keyframes shimmer { 0%{opacity:1}50%{opacity:0.7}100%{opacity:1} }
        input[type=range] { -webkit-appearance: none; height: 4px; border-radius: 99px; outline: none; background: ${TOKEN.surfaceBorder}; }
        input[type=range]::-webkit-slider-thumb { -webkit-appearance: none; width: 16px; height: 16px; border-radius: 50%; background: ${TOKEN.accent}; cursor: pointer; }
        select option { background: ${TOKEN.surfaceRaised}; color: ${TOKEN.text}; }
        mark { background: transparent; }
        button:focus { outline: none; }
        input:focus { outline: none; }
      `}</style>

      {page !== 'presentation' && (
        <TopNav lang={lang} page={page} setPage={handleSetPage}
          onToggleLang={() => setLang(l => l === 'zh' ? 'en' : 'zh')}
          onAdminClick={handleAdminClick}
          user={user}
          onSignIn={handleSignIn}
          onLogout={async () => { await doLogout(); setPage('select'); }} />
      )}

      {/* Main content */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        {/* Landing for unauthenticated visitors at root. Avoid flash on hard
            refresh while logged in by waiting for /me to resolve. */}
        {/* landing-and-mode-orchestration-redesign: HomePage replaces the old
            LandingPage / PodcastSelect pair. Single component covers both
            auth states via hero swap, plus mode-trio educational band and
            show grid with trending-query chips. */}
        {page === 'select' && !userLoading && !user && disabledAuth && (
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
            <LockCardLegacy
              lang={lang}
              state="disabled"
              appealEnabled={disabledAuth.appealEnabled}
              onPrimaryClick={() => setAppealOpen(true)}
            />
          </div>
        )}
        {page === 'select' && !(!userLoading && !user && disabledAuth) && (
          <HomePage
            lang={lang}
            user={user}
            userLoading={userLoading}
            onSelectShow={(show) => { setSelectedShow(show); setPage('query'); }}
            onSearchPrefill={(q) => setLandingQuery(q)}
            onSignIn={handleSignIn}
            onOpenApplyQuota={() => { /* QueryPage handles its own modal; quick-pass for hero CTA */
              setLandingQuery('');
              if (user) {
                // Send the user into the show grid; QuotaApply modal lives
                // inside QueryPage today. Future iteration may extract it
                // to App-level for cross-page reuse.
              }
            }}
          />
        )}
        {selectedShow && (page === 'query' || page === 'transcript') && (
          <div style={{ display: page === 'query' ? 'flex' : 'none', flex: 1, overflow: 'hidden' }}>
            <QueryPage lang={lang} show={selectedShow} queryMode={tweaks.queryMode}
              user={user} onUserChange={refreshUser}
              initialQuery={landingQuery}
              onBack={() => { setLandingQuery(''); setPage('select'); }}
              onOpenEpisode={(ep, ht) => {
                setSelectedEpisode(ep);
                setInitSearch('');
                const seconds = typeof ht === 'number' ? ht : null;
                setHighlightTime(seconds);
                // R2.1-followup section 3: URL needs show_id + episode_id + t so
                // a reload / shared link can re-build state without React memory.
                try {
                  const url = new URL(window.location.href);
                  if (selectedShow?.id) url.searchParams.set('show_id', selectedShow.id);
                  if (ep?.id) url.searchParams.set('episode_id', ep.id);
                  if (seconds != null) url.searchParams.set('t', String(seconds.toFixed(2)));
                  else url.searchParams.delete('t');
                  window.history.replaceState({}, '', url.toString());
                } catch (_) { /* harmless; deep-link is best-effort */ }
                setPage('transcript');
              }} />
          </div>
        )}
        {page === 'transcript' && selectedEpisode && selectedShow && (
          <TranscriptPage lang={lang} show={selectedShow} episode={selectedEpisode}
            isAdmin={isAdmin}
            initSearch={initSearch} highlightTime={highlightTime}
            onBack={() => {
              // Clear all deep-link params so a subsequent unrelated navigation
              // doesn't carry stale show_id/episode_id/t.
              try {
                const url = new URL(window.location.href);
                url.searchParams.delete('t');
                url.searchParams.delete('episode_id');
                url.searchParams.delete('show_id');
                window.history.replaceState({}, '', url.toString());
              } catch (_) { /* best-effort */ }
              setPage('query');
            }} />
        )}
        {page === 'release-log' && <ReleaseLogPage lang={lang} />}
        {page === 'presentation' && <PresentationPage />}
        {page.startsWith('admin') && isAdmin && (
          <AdminPage lang={lang} activePage={page} currentUser={user} onUserChange={refreshUser} />
        )}
      </div>

      {/* disabled-user-appeal-flow: AppealModal */}
      {disabledAuth && (
        <AppealModal
          open={appealOpen}
          lang={lang}
          email={disabledAuth.email}
          onClose={() => setAppealOpen(false)}
        />
      )}

      {/* Tweaks panel */}
      {tweaksVisible && (
        <div style={{ position: 'fixed', bottom: 24, right: 24, width: 280, background: TOKEN.surface, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 14, padding: 20, zIndex: 1000, boxShadow: '0 20px 60px rgba(0,0,0,0.5)' }}>
          <p style={{ color: TOKEN.text, fontWeight: 700, fontSize: 14, margin: '0 0 16px', display: 'flex', alignItems: 'center', gap: 8 }}>
            <Icon name="settings" size={15} color={TOKEN.accent} /> Tweaks
          </p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <div>
              <label style={{ display: 'block', color: TOKEN.textMuted, fontSize: 12, marginBottom: 8 }}>{t ? '查詢介面模式' : 'Query Mode'}</label>
              {[[0, t ? '兩種都顯示' : 'Both'], [1, t ? '只顯示對話' : 'Chat only'], [2, t ? '只顯示搜尋' : 'Search only']].map(([v, label]) => (
                <label key={v} style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', marginBottom: 6, fontSize: 13, color: tweaks.queryMode === v ? TOKEN.text : TOKEN.textSecondary }}>
                  <input type="radio" name="queryMode" checked={tweaks.queryMode === v} onChange={() => applyTweak('queryMode', v)} style={{ accentColor: TOKEN.accent }} />
                  {label}
                </label>
              ))}
            </div>
            <div>
              <label style={{ display: 'block', color: TOKEN.textMuted, fontSize: 12, marginBottom: 8 }}>{t ? '主題色' : 'Accent Color'}</label>
              <div style={{ display: 'flex', gap: 8 }}>
                {['#6366f1', '#22d3ee', '#f59e0b', '#22c55e', '#ec4899'].map(c => (
                  <div key={c} onClick={() => applyTweak('accentColor', c)}
                    style={{ width: 26, height: 26, borderRadius: '50%', background: c, cursor: 'pointer', border: `2px solid ${tweaks.accentColor === c ? '#fff' : 'transparent'}`, transition: 'border 0.12s' }} />
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

const root = ReactDOM.createRoot(document.getElementById('root'));
// AudioPlayerProvider mounts a single <audio> element outside the page
// router so playback survives QueryPage ↔ TranscriptPage navigation
// (landing-and-mode-orchestration-redesign decision 6).
root.render(
  <AudioPlayerProvider>
    <App />
  </AudioPlayerProvider>
);
