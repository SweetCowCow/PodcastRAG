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
  const { user, loading: userLoading, refresh: refreshUser, logout: doLogout } = useCurrentUser();
  const isAdmin = user && user.role === 'admin' && user.status === 'active';

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
        {page === 'select' && <PodcastSelect lang={lang} user={user} setPage={handleSetPage} onSelect={(show) => { setSelectedShow(show); setPage('query'); }} />}
        {selectedShow && (page === 'query' || page === 'transcript') && (
          <div style={{ display: page === 'query' ? 'flex' : 'none', flex: 1, overflow: 'hidden' }}>
            <QueryPage lang={lang} show={selectedShow} queryMode={tweaks.queryMode}
              user={user} onUserChange={refreshUser}
              onBack={() => setPage('select')}
              onOpenEpisode={(ep, ht) => { setSelectedEpisode(ep); setInitSearch(''); setHighlightTime(typeof ht === 'number' ? ht : null); setPage('transcript'); }} />
          </div>
        )}
        {page === 'transcript' && selectedEpisode && selectedShow && (
          <TranscriptPage lang={lang} show={selectedShow} episode={selectedEpisode}
            initSearch={initSearch} highlightTime={highlightTime} onBack={() => setPage('query')} />
        )}
        {page === 'release-log' && <ReleaseLogPage lang={lang} />}
        {page === 'presentation' && <PresentationPage />}
        {page.startsWith('admin') && isAdmin && (
          <AdminPage lang={lang} activePage={page} currentUser={user} onUserChange={refreshUser} />
        )}
      </div>

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
root.render(<App />);
