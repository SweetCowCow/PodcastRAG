// Main App — top nav layout + admin login gate
const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "queryMode": 0,
  "defaultLang": "zh",
  "accentColor": "#6366f1"
}/*EDITMODE-END*/;

// ── Admin Login Gate ──
const AdminLogin = ({ lang, onSuccess, onCancel }) => {
  const t = lang === 'zh';
  const [user, setUser] = React.useState('');
  const [pass, setPass] = React.useState('');
  const [showPass, setShowPass] = React.useState(false);
  const [error, setError] = React.useState('');
  const [loading, setLoading] = React.useState(false);

  const handleLogin = () => {
    if (!user || !pass) { setError(t ? '請填寫帳號與密碼' : 'Please enter credentials'); return; }
    setLoading(true);
    setError('');
    setTimeout(() => {
      if (user === 'admin' && pass === '***REDACTED***') {
        onSuccess();
      } else {
        setError(t ? '帳號或密碼錯誤' : 'Invalid credentials');
        setLoading(false);
      }
    }, 800);
  };

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 500, backdropFilter: 'blur(4px)' }}>
      <div style={{ background: TOKEN.surface, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 16, padding: 36, width: 380, boxShadow: '0 24px 80px rgba(0,0,0,0.6)' }}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 28 }}>
          <div style={{ width: 40, height: 40, borderRadius: 10, background: TOKEN.accentDim, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Icon name="settings" size={20} color={TOKEN.accent} />
          </div>
          <div>
            <div style={{ color: TOKEN.text, fontWeight: 700, fontSize: 17 }}>{t ? '後台管理登入' : 'Admin Login'}</div>
            <div style={{ color: TOKEN.textMuted, fontSize: 12, marginTop: 2 }}>{t ? '請輸入管理員帳號與密碼' : 'Enter admin credentials to continue'}</div>
          </div>
        </div>

        {/* Form */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div>
            <label style={{ display: 'block', color: TOKEN.textMuted, fontSize: 12, marginBottom: 6 }}>{t ? '帳號' : 'Username'}</label>
            <Input value={user} onChange={e => setUser(e.target.value)} placeholder={t ? '輸入管理員帳號' : 'Enter username'} icon="key"
              onKeyDown={e => e.key === 'Enter' && handleLogin()} />
          </div>
          <div>
            <label style={{ display: 'block', color: TOKEN.textMuted, fontSize: 12, marginBottom: 6 }}>{t ? '密碼' : 'Password'}</label>
            <div style={{ position: 'relative' }}>
              <input value={pass} onChange={e => setPass(e.target.value)} type={showPass ? 'text' : 'password'}
                placeholder={t ? '輸入密碼' : 'Enter password'}
                onKeyDown={e => e.key === 'Enter' && handleLogin()}
                style={{ width: '100%', background: TOKEN.surfaceRaised, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 8, padding: '9px 40px 9px 12px', color: TOKEN.text, fontSize: 14, outline: 'none', fontFamily: 'inherit' }} />
              <button onClick={() => setShowPass(v => !v)}
                style={{ position: 'absolute', right: 10, top: '50%', transform: 'translateY(-50%)', background: 'none', border: 'none', cursor: 'pointer', color: TOKEN.textMuted, display: 'flex', alignItems: 'center' }}>
                <Icon name={showPass ? 'eyeOff' : 'eye'} size={16} />
              </button>
            </div>
          </div>

          {error && (
            <div style={{ background: 'rgba(239,68,68,0.12)', border: '1px solid rgba(239,68,68,0.3)', borderRadius: 8, padding: '9px 13px', color: '#f87171', fontSize: 13 }}>
              {error}
            </div>
          )}

          <div style={{ display: 'flex', gap: 10, marginTop: 4 }}>
            <Btn onClick={handleLogin} disabled={loading} style={{ flex: 1 }}>
              {loading ? (t ? '驗證中...' : 'Verifying...') : (t ? '登入後台' : 'Login')}
            </Btn>
            <Btn variant="ghost" onClick={onCancel}>{t ? '取消' : 'Cancel'}</Btn>
          </div>

          <p style={{ color: TOKEN.textMuted, fontSize: 11, textAlign: 'center', margin: 0 }}>
            {t ? '示範帳號：admin / ***REDACTED***' : 'Demo: admin / ***REDACTED***'}
          </p>
        </div>
      </div>
    </div>
  );
};

// ── Main App ──
const App = () => {
  const [lang, setLang] = React.useState(TWEAK_DEFAULTS.defaultLang || 'zh');
  const [page, setPage] = React.useState('select');
  const [selectedShow, setSelectedShow] = React.useState(null);
  const [selectedEpisode, setSelectedEpisode] = React.useState(null);
  const [initSearch, setInitSearch] = React.useState('');
  const [tweaksVisible, setTweaksVisible] = React.useState(false);
  const [tweaks, setTweaks] = React.useState(TWEAK_DEFAULTS);
  const [adminAuth, setAdminAuth] = React.useState(false);
  const [showAdminLogin, setShowAdminLogin] = React.useState(false);

  React.useEffect(() => {
    const handler = (e) => {
      if (e.data?.type === '__activate_edit_mode') setTweaksVisible(true);
      if (e.data?.type === '__deactivate_edit_mode') setTweaksVisible(false);
    };
    window.addEventListener('message', handler);
    window.parent.postMessage({ type: '__edit_mode_available' }, '*');
    return () => window.removeEventListener('message', handler);
  }, []);

  const applyTweak = (key, val) => {
    setTweaks(t => ({ ...t, [key]: val }));
    window.parent.postMessage({ type: '__edit_mode_set_keys', edits: { [key]: val } }, '*');
  };

  const handleAdminClick = () => {
    if (adminAuth) {
      setPage('admin-api');
    } else {
      setShowAdminLogin(true);
    }
  };

  const handleAdminSuccess = () => {
    setAdminAuth(true);
    setShowAdminLogin(false);
    setPage('admin-api');
  };

  const handleSetPage = (p) => {
    if (p === 'select') { setSelectedShow(null); setSelectedEpisode(null); }
    setPage(p);
  };

  const t = lang === 'zh';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', fontFamily: "'Inter', 'Helvetica Neue', Arial, sans-serif", background: TOKEN.bg, overflow: 'hidden' }}>
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

      <TopNav lang={lang} page={page} setPage={handleSetPage}
        onToggleLang={() => setLang(l => l === 'zh' ? 'en' : 'zh')}
        onAdminClick={handleAdminClick} />

      {/* Main content */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        {page === 'select' && <PodcastSelect lang={lang} onSelect={(show) => { setSelectedShow(show); setPage('query'); }} />}
        {page === 'query' && selectedShow && (
          <QueryPage lang={lang} show={selectedShow} queryMode={tweaks.queryMode}
            onBack={() => setPage('select')}
            onOpenEpisode={(ep, search) => { setSelectedEpisode(ep); setInitSearch(search || ''); setPage('transcript'); }} />
        )}
        {page === 'transcript' && selectedEpisode && selectedShow && (
          <TranscriptPage lang={lang} show={selectedShow} episode={selectedEpisode}
            initSearch={initSearch} onBack={() => setPage('query')} />
        )}
        {page.startsWith('admin') && <AdminPage lang={lang} activePage={page} />}
      </div>

      {/* Admin login modal */}
      {showAdminLogin && (
        <AdminLogin lang={lang} onSuccess={handleAdminSuccess} onCancel={() => setShowAdminLogin(false)} />
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
root.render(<App />);
