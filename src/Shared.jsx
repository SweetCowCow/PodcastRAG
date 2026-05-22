// Shared components: tokens, icons, Nav, Layout
// API_BASE is sourced from config.js (window.__API_BASE__) so each environment
// can point the frontend at its own backend without rebuilding the JSX.
const API_BASE = (typeof window !== 'undefined' && window.__API_BASE__) || 'http://localhost:8000';

// --- useViewport: shared hook returning { isMobile } ---
// isMobile === window.innerWidth < 768. Initial value taken synchronously
// from window.innerWidth to avoid first-render flash. Resize listener wraps
// state updates in requestAnimationFrame to coalesce within a frame, and
// only triggers setState when isMobile actually changes (so resizes within
// the same band cause no extra renders).
const useViewport = () => {
  const [isMobile, setIsMobile] = React.useState(() => (typeof window !== 'undefined' ? window.innerWidth < 768 : false));
  React.useEffect(() => {
    let rafId = 0;
    const onResize = () => {
      if (rafId) return;
      rafId = window.requestAnimationFrame(() => {
        rafId = 0;
        const next = window.innerWidth < 768;
        setIsMobile(prev => (prev === next ? prev : next));
      });
    };
    window.addEventListener('resize', onResize);
    return () => {
      window.removeEventListener('resize', onResize);
      if (rafId) window.cancelAnimationFrame(rafId);
    };
  }, []);
  return { isMobile };
};

const TOKEN = {
  bg: '#0b1120',
  surface: '#131c2e',
  surfaceRaised: '#1a2540',
  surfaceBorder: '#243050',
  accent: '#6366f1',
  accentHover: '#818cf8',
  accentDim: 'rgba(99,102,241,0.15)',
  text: '#e2e8f0',
  textSecondary: '#7c8fad',
  textMuted: '#4a5a78',
  success: '#22c55e',
  warning: '#f59e0b',
  danger: '#ef4444',
};

// --- Mini icon set (SVG) ---
const Icon = ({ name, size = 18, color = 'currentColor', style = {} }) => {
  const s = { width: size, height: size, display: 'inline-block', verticalAlign: 'middle', ...style };
  const paths = {
    mic: <svg viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={s}><rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10a7 7 0 0 0 14 0"/><line x1="12" y1="19" x2="12" y2="22"/><line x1="8" y1="22" x2="16" y2="22"/></svg>,
    search: <svg viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={s}><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>,
    rss: <svg viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={s}><path d="M4 11a9 9 0 0 1 9 9"/><path d="M4 4a16 16 0 0 1 16 16"/><circle cx="5" cy="19" r="1" fill={color}/></svg>,
    settings: <svg viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={s}><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>,
    key: <svg viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={s}><path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0 3 3L22 7l-3-3m-3.5 3.5L19 4"/></svg>,
    brain: <svg viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={s}><path d="M9.5 2A2.5 2.5 0 0 1 12 4.5v15a2.5 2.5 0 0 1-4.96-.46 2.5 2.5 0 0 1-2.96-3.08 3 3 0 0 1-.34-5.58 2.5 2.5 0 0 1 1.32-4.24 2.5 2.5 0 0 1 1.98-3A2.5 2.5 0 0 1 9.5 2Z"/><path d="M14.5 2A2.5 2.5 0 0 0 12 4.5v15a2.5 2.5 0 0 0 4.96-.46 2.5 2.5 0 0 0 2.96-3.08 3 3 0 0 0 .34-5.58 2.5 2.5 0 0 0-1.32-4.24 2.5 2.5 0 0 0-1.98-3A2.5 2.5 0 0 0 14.5 2Z"/></svg>,
    database: <svg viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={s}><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14c0 1.66 4.03 3 9 3s9-1.34 9-3V5"/><path d="M3 12c0 1.66 4.03 3 9 3s9-1.34 9-3"/></svg>,
    calendar: <svg viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={s}><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>,
    chevronRight: <svg viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={s}><polyline points="9 18 15 12 9 6"/></svg>,
    chevronLeft: <svg viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={s}><polyline points="15 18 9 12 15 6"/></svg>,
    play: <svg viewBox="0 0 24 24" fill={color} stroke="none" style={s}><polygon points="5 3 19 12 5 21"/></svg>,
    send: <svg viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={s}><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9"/></svg>,
    check: <svg viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" style={s}><polyline points="20 6 9 17 4 12"/></svg>,
    clock: <svg viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={s}><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>,
    refresh: <svg viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={s}><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>,
    eye: <svg viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={s}><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>,
    eyeOff: <svg viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={s}><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>,
    plus: <svg viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={s}><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>,
    edit: <svg viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={s}><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>,
    trash: <svg viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={s}><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4h6v2"/></svg>,
    globe: <svg viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={s}><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>,
    arrowLeft: <svg viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={s}><line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/></svg>,
    fileText: <svg viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={s}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>,
    zap: <svg viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={s}><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>,
    podcast: <svg viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={s}><circle cx="12" cy="11" r="1"/><path d="M11 17a1 1 0 0 1 2 0c0 .5-.34 3-.5 4.5a.5.5 0 0 1-1 0c-.16-1.5-.5-4-.5-4.5z"/><path d="M8 14a5 5 0 1 1 8 0"/><path d="M5 18a9 9 0 1 1 14 0"/></svg>,
    moreVertical: <svg viewBox="0 0 24 24" fill={color} stroke="none" style={s}><circle cx="12" cy="5" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="12" cy="19" r="2"/></svg>,
    list: <svg viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={s}><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>,
    menu: <svg viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={s}><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>,
    chevronUp: <svg viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={s}><polyline points="18 15 12 9 6 15"/></svg>,
    chevronDown: <svg viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={s}><polyline points="6 9 12 15 18 9"/></svg>,
    x: <svg viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={s}><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>,
    users: <svg viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={s}><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>,
  };
  return paths[name] || <svg viewBox="0 0 24 24" style={s}><circle cx="12" cy="12" r="10" stroke={color} strokeWidth="2" fill="none"/></svg>;
};

// --- Badge ---
const Badge = ({ children, variant = 'default' }) => {
  const colors = {
    default: { bg: TOKEN.accentDim, color: TOKEN.accentHover },
    success: { bg: 'rgba(34,197,94,0.12)', color: '#4ade80' },
    warning: { bg: 'rgba(245,158,11,0.12)', color: '#fbbf24' },
    danger: { bg: 'rgba(239,68,68,0.12)', color: '#f87171' },
    muted: { bg: TOKEN.surfaceBorder, color: TOKEN.textSecondary },
  };
  const c = colors[variant] || colors.default;
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, padding: '2px 8px', borderRadius: 99, fontSize: 11, fontWeight: 600, letterSpacing: '0.03em', background: c.bg, color: c.color }}>
      {children}
    </span>
  );
};

// --- Button ---
const Btn = ({ children, onClick, variant = 'primary', size = 'md', disabled, style: extraStyle = {}, icon }) => {
  const [hovered, setHovered] = React.useState(false);
  const { isMobile } = useViewport();
  const base = {
    display: 'inline-flex', alignItems: 'center', gap: 6, borderRadius: 8,
    cursor: disabled ? 'not-allowed' : 'pointer', border: 'none', fontWeight: 500,
    transition: 'all 0.15s', opacity: disabled ? 0.5 : 1, fontFamily: 'inherit',
    ...(isMobile && { minHeight: 44, minWidth: 44, justifyContent: 'center' }),
  };
  const sizes = { sm: { padding: '5px 12px', fontSize: 13 }, md: { padding: '8px 16px', fontSize: 14 }, lg: { padding: '11px 22px', fontSize: 15 } };
  const variants = {
    primary: { background: hovered ? TOKEN.accentHover : TOKEN.accent, color: '#fff' },
    secondary: { background: hovered ? TOKEN.surfaceRaised : TOKEN.surfaceBorder, color: TOKEN.text, border: `1px solid ${TOKEN.surfaceBorder}` },
    ghost: { background: hovered ? TOKEN.surfaceRaised : 'transparent', color: hovered ? TOKEN.text : TOKEN.textSecondary },
    danger: { background: hovered ? '#dc2626' : TOKEN.danger, color: '#fff' },
  };
  return (
    <button onClick={onClick} disabled={disabled} onMouseEnter={() => setHovered(true)} onMouseLeave={() => setHovered(false)}
      style={{ ...base, ...sizes[size], ...variants[variant], ...extraStyle }}>
      {icon && <Icon name={icon} size={size === 'sm' ? 14 : 16} color="currentColor" />}
      {children}
    </button>
  );
};

// --- Input ---
// `onSubmit` (optional) fires when the user presses Enter AND no IME composition
// is active. CJK input methods (注音 / 倉頡 / 拼音 etc.) use Enter to confirm
// candidate characters mid-composition — the guard (`e.isComposing` plus legacy
// `keyCode === 229` for Safari/iOS) prevents that keystroke from triggering
// submit. Any caller-supplied `onKeyDown` still fires *after* the submit logic
// so existing listeners keep working.
const Input = ({ value, onChange, onSubmit, onKeyDown, placeholder, type = 'text', icon, style: extraStyle = {}, ...rest }) => {
  const [focused, setFocused] = React.useState(false);
  const handleKey = (e) => {
    if (!(e.isComposing || e.keyCode === 229)) {
      if (e.key === 'Enter' && onSubmit) {
        e.preventDefault();
        onSubmit(e);
      }
    }
    if (onKeyDown) onKeyDown(e);
  };
  return (
    <div style={{ position: 'relative', width: '100%' }}>
      {icon && <span style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none', color: TOKEN.textMuted }}><Icon name={icon} size={16} /></span>}
      <input value={value} onChange={onChange} placeholder={placeholder} type={type}
        onFocus={() => setFocused(true)} onBlur={() => setFocused(false)}
        {...rest}
        onKeyDown={handleKey}
        style={{ width: '100%', boxSizing: 'border-box', background: TOKEN.surfaceRaised, border: `1px solid ${focused ? TOKEN.accent : TOKEN.surfaceBorder}`, borderRadius: 8, padding: icon ? '9px 12px 9px 36px' : '9px 12px', color: TOKEN.text, fontSize: 14, outline: 'none', fontFamily: 'inherit', transition: 'border 0.15s', ...extraStyle }} />
    </div>
  );
};

// --- Top Nav ---
const TopNav = ({ lang, page, setPage, onToggleLang, onAdminClick, user, onSignIn, onLogout }) => {
  const t = lang === 'zh';
  const isAdmin = page && page.startsWith('admin');
  const { isMobile } = useViewport();
  const [menuOpen, setMenuOpen] = React.useState(false);
  const [userMenuOpen, setUserMenuOpen] = React.useState(false);

  const mainItems = [
    { id: 'select', icon: 'podcast', label: t ? '節目選擇' : 'Shows' },
    { id: 'release-log', icon: 'fileText', label: t ? '更新日誌' : 'Change Log' },
    { id: 'admin', icon: 'settings', label: t ? '後台管理' : 'Admin' },
  ];
  const adminItems = [
    { id: 'admin-api', icon: 'key', label: t ? 'API 金鑰' : 'API Keys' },
    { id: 'admin-llm', icon: 'brain', label: t ? 'LLM 模型' : 'LLM Models' },
    { id: 'admin-rag', icon: 'database', label: t ? 'RAG 設定' : 'RAG Config' },
    { id: 'admin-schedule', icon: 'calendar', label: t ? '轉錄排程' : 'Transcription' },
    { id: 'admin-queue', icon: 'list', label: t ? '轉錄序列' : 'Queue' },
    { id: 'admin-users', icon: 'users', label: t ? '使用者' : 'Users' },
    { id: 'admin-quota-requests', icon: 'fileText', label: t ? 'Quota 申請' : 'Quota Requests' },
    { id: 'admin-guests', icon: 'mic', label: t ? '來賓管理' : 'Guests' },
    { id: 'admin-tokenizer', icon: 'wand', label: t ? '分詞詞典' : 'Tokenizer' },
    { id: 'admin-topic-seg-audit', icon: 'list', label: t ? '段落分類審核' : 'Topic Audit' },
    { id: 'admin-external-api', icon: 'globe', label: t ? '外部 API 狀態' : 'External API Status' },
    { id: 'admin-provider-usage', icon: 'zap', label: t ? '服務用量' : 'Service Usage' },
    { id: 'admin-service-status', icon: 'settings', label: t ? '服務狀態' : 'Service Status' },
  ];

  const onMainClick = (id) => {
    setMenuOpen(false);
    if (id === 'admin') onAdminClick();
    else setPage(id);
  };

  return (
    <div style={{ flexShrink: 0, borderBottom: `1px solid ${TOKEN.surfaceBorder}`, background: TOKEN.surface, position: 'relative' }}>
      {/* Primary bar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 0, padding: isMobile ? '0 14px' : '0 28px', height: 56 }}>
        {isMobile && (
          <button onClick={() => setMenuOpen(v => !v)} aria-label={t ? '主選單' : 'Main menu'}
            style={{ width: 44, height: 44, borderRadius: 8, background: menuOpen ? TOKEN.accentDim : 'transparent', border: 'none', color: TOKEN.text, cursor: 'pointer', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', padding: 0, marginRight: 8 }}>
            <Icon name="menu" size={20} color="currentColor" />
          </button>
        )}
        {/* Logo */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginRight: isMobile ? 0 : 32, flex: isMobile ? 1 : 'none' }}>
          <div style={{ width: 28, height: 28, borderRadius: 7, background: TOKEN.accentDim, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Icon name="zap" size={15} color={TOKEN.accent} />
          </div>
          <span style={{ color: TOKEN.text, fontWeight: 700, fontSize: 15 }}>PodcastRAG</span>
          {!isMobile && <span style={{ color: TOKEN.textMuted, fontSize: 11, marginLeft: -4 }}>beta</span>}
        </div>

        {/* Desktop: main nav items inline */}
        {!isMobile && (
          <nav style={{ display: 'flex', alignItems: 'stretch', gap: 2, flex: 1 }}>
            {mainItems.map(item => {
              const active = item.id === 'select'
                ? !isAdmin && (page === 'select' || page === 'query' || page === 'transcript')
                : item.id === 'release-log'
                ? page === 'release-log'
                : isAdmin;
              return (
                <TopNavItem key={item.id} icon={item.icon} label={item.label} active={active}
                  onClick={() => onMainClick(item.id)} />
              );
            })}
          </nav>
        )}

        {/* Right: lang toggle + user / sign-in (desktop only — mobile lang is in dropdown) */}
        {!isMobile && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <button onClick={onToggleLang}
              style={{ display: 'flex', alignItems: 'center', gap: 6, background: TOKEN.surfaceRaised, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 7, padding: '5px 11px', color: TOKEN.textSecondary, cursor: 'pointer', fontSize: 13, fontFamily: 'inherit' }}>
              <Icon name="globe" size={13} />
              {lang === 'zh' ? '中文' : 'EN'}
            </button>
            {user ? (
              <UserMenu user={user} lang={lang} open={userMenuOpen}
                setOpen={setUserMenuOpen} onLogout={onLogout} />
            ) : (
              <button onClick={onSignIn}
                style={{ display: 'flex', alignItems: 'center', gap: 6, background: TOKEN.accent, border: 'none', borderRadius: 7, padding: '6px 12px', color: '#fff', cursor: 'pointer', fontSize: 13, fontWeight: 600, fontFamily: 'inherit' }}>
                <Icon name="key" size={13} color="#fff" />
                {t ? '使用 Google 登入' : 'Sign in with Google'}
              </button>
            )}
          </div>
        )}
        {isMobile && user && (
          <UserMenu user={user} lang={lang} open={userMenuOpen}
            setOpen={setUserMenuOpen} onLogout={onLogout} compact />
        )}
        {isMobile && !user && (
          <button onClick={onSignIn}
            style={{ background: TOKEN.accent, border: 'none', borderRadius: 7, padding: '6px 10px', color: '#fff', cursor: 'pointer', fontSize: 12, fontWeight: 600, fontFamily: 'inherit', whiteSpace: 'nowrap' }}>
            {t ? '登入' : 'Sign in'}
          </button>
        )}
      </div>

      {/* Mobile hamburger dropdown */}
      {isMobile && menuOpen && (
        <React.Fragment>
          <div onClick={() => setMenuOpen(false)}
            style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)', zIndex: 998 }} />
          <div role="menu"
            style={{ position: 'absolute', top: '100%', left: 0, right: 0, background: TOKEN.surface, borderBottom: `1px solid ${TOKEN.surfaceBorder}`, padding: '8px 0', zIndex: 999, boxShadow: '0 8px 24px rgba(0,0,0,0.4)' }}>
            {mainItems.map(item => {
              const active = item.id === 'select'
                ? !isAdmin && (page === 'select' || page === 'query' || page === 'transcript')
                : item.id === 'release-log'
                ? page === 'release-log'
                : isAdmin;
              return (
                <button key={item.id} onClick={() => onMainClick(item.id)}
                  style={{ display: 'flex', alignItems: 'center', gap: 12, width: '100%', padding: '14px 20px', minHeight: 44, background: active ? TOKEN.accentDim : 'transparent', border: 'none', color: active ? TOKEN.accent : TOKEN.text, fontSize: 15, fontWeight: active ? 600 : 500, textAlign: 'left', cursor: 'pointer', fontFamily: 'inherit' }}>
                  <Icon name={item.icon} size={18} color="currentColor" />
                  {item.label}
                </button>
              );
            })}
            <div style={{ height: 1, background: TOKEN.surfaceBorder, margin: '6px 0' }} />
            <button onClick={() => { onToggleLang(); setMenuOpen(false); }}
              style={{ display: 'flex', alignItems: 'center', gap: 12, width: '100%', padding: '14px 20px', minHeight: 44, background: 'transparent', border: 'none', color: TOKEN.textSecondary, fontSize: 14, textAlign: 'left', cursor: 'pointer', fontFamily: 'inherit' }}>
              <Icon name="globe" size={16} color="currentColor" />
              {lang === 'zh' ? '切換為 English' : '切換為中文'}
            </button>
          </div>
        </React.Fragment>
      )}

      {/* Admin secondary bar — desktop: flex; mobile: horizontal scroll */}
      {isAdmin && (
        <div style={{ display: 'flex', alignItems: 'stretch', padding: isMobile ? '0 8px' : '0 28px', height: isMobile ? 48 : 42, borderTop: `1px solid ${TOKEN.surfaceBorder}`, background: TOKEN.bg, gap: 2, overflowX: isMobile ? 'auto' : 'visible', flexWrap: 'nowrap', whiteSpace: 'nowrap' }}>
          {adminItems.map(item => (
            <TopNavItem key={item.id} icon={item.icon} label={item.label} active={page === item.id}
              onClick={() => setPage(item.id)} secondary mobile={isMobile} />
          ))}
        </div>
      )}
    </div>
  );
};

const UserMenu = ({ user, lang, open, setOpen, onLogout, compact }) => {
  const t = lang === 'zh';
  const ref = React.useRef(null);
  const quotaLow = user.quota_remaining === 0;
  React.useEffect(() => {
    if (!open) return;
    const onClick = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, [open, setOpen]);
  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <button onClick={() => setOpen(v => !v)}
        title={user.email}
        style={{ display: 'flex', alignItems: 'center', gap: 8, background: TOKEN.surfaceRaised, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 99, padding: compact ? '3px 6px' : '4px 10px 4px 4px', color: TOKEN.text, cursor: 'pointer', fontSize: 12, fontFamily: 'inherit' }}>
        {user.avatar_url
          ? <img src={user.avatar_url} alt="" referrerPolicy="no-referrer" style={{ width: 26, height: 26, borderRadius: '50%' }} />
          : <div style={{ width: 26, height: 26, borderRadius: '50%', background: TOKEN.accentDim, display: 'flex', alignItems: 'center', justifyContent: 'center', color: TOKEN.accent, fontWeight: 700 }}>{(user.name || user.email || '?').slice(0,1).toUpperCase()}</div>}
        {!compact && (
          <span style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', lineHeight: 1.15 }}>
            <span style={{ fontSize: 12, fontWeight: 600 }}>{user.name || user.email.split('@')[0]}</span>
            <span style={{ fontSize: 10, color: quotaLow ? TOKEN.danger : TOKEN.textMuted }}>
              {t ? '剩餘' : 'Remaining'} {user.quota_remaining}
            </span>
          </span>
        )}
      </button>
      {open && (
        <div style={{ position: 'absolute', right: 0, top: 'calc(100% + 6px)', background: TOKEN.surface, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 10, padding: 12, minWidth: 220, zIndex: 600, boxShadow: '0 12px 40px rgba(0,0,0,0.5)' }}>
          <div style={{ color: TOKEN.text, fontSize: 13, fontWeight: 600 }}>{user.name || user.email.split('@')[0]}</div>
          <div style={{ color: TOKEN.textMuted, fontSize: 11, marginTop: 2 }}>{user.email}</div>
          <div style={{ height: 1, background: TOKEN.surfaceBorder, margin: '10px 0' }} />
          <div style={{ display: 'flex', justifyContent: 'space-between', color: TOKEN.textSecondary, fontSize: 12 }}>
            <span>{t ? '角色' : 'Role'}</span><span>{user.role}</span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', color: TOKEN.textSecondary, fontSize: 12, marginTop: 4 }}>
            <span>{t ? '剩餘額度' : 'Remaining quota'}</span>
            <span style={{ color: quotaLow ? TOKEN.danger : TOKEN.text, fontWeight: 600 }}>{user.quota_remaining}</span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', color: TOKEN.textSecondary, fontSize: 12, marginTop: 4 }}>
            <span>{t ? '累計查詢' : 'Total queries'}</span><span>{user.total_queries}</span>
          </div>
          <button onClick={() => { setOpen(false); onLogout && onLogout(); }}
            style={{ width: '100%', marginTop: 12, background: TOKEN.surfaceRaised, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 8, padding: '8px 10px', color: TOKEN.danger, cursor: 'pointer', fontSize: 13, fontFamily: 'inherit' }}>
            {t ? '登出' : 'Sign out'}
          </button>
        </div>
      )}
    </div>
  );
};

const TopNavItem = ({ icon, label, active, onClick, secondary, mobile }) => {
  const [hovered, setHovered] = React.useState(false);
  return (
    <button onClick={onClick} onMouseEnter={() => setHovered(true)} onMouseLeave={() => setHovered(false)}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 6,
        padding: secondary ? '0 14px' : '0 16px',
        height: '100%', minHeight: mobile ? 44 : undefined,
        flexShrink: 0,
        background: 'none', border: 'none',
        borderBottom: `2px solid ${active ? TOKEN.accent : 'transparent'}`,
        color: active ? TOKEN.accent : hovered ? TOKEN.text : TOKEN.textSecondary,
        cursor: 'pointer', fontSize: secondary ? 13 : 14,
        fontWeight: active ? 600 : 400, fontFamily: 'inherit',
        transition: 'all 0.12s', whiteSpace: 'nowrap',
      }}>
      <Icon name={icon} size={secondary ? 14 : 15} color="currentColor" />
      {label}
    </button>
  );
};

// --- Confirm Modal (for destructive actions) ---
const ConfirmModal = ({ open, title, message, confirmLabel = 'Confirm', cancelLabel = 'Cancel', danger = false, loading = false, onConfirm, onCancel }) => {
  const { isMobile } = useViewport();
  if (!open) return null;
  return (
    <div onClick={loading ? undefined : onCancel}
      style={{ position: 'fixed', inset: 0, background: 'rgba(4,8,20,0.72)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000, padding: isMobile ? 12 : 0 }}>
      <div onClick={e => e.stopPropagation()}
        style={{ background: TOKEN.surface, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 14, padding: isMobile ? '18px 18px' : '22px 26px', width: 'min(95vw, 520px)', boxShadow: '0 20px 60px rgba(0,0,0,0.5)' }}>
        <div style={{ color: TOKEN.text, fontWeight: 700, fontSize: 16, marginBottom: 10 }}>{title}</div>
        <div style={{ color: TOKEN.textSecondary, fontSize: 14, lineHeight: 1.6, marginBottom: 20, whiteSpace: 'pre-line' }}>{message}</div>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <Btn variant="ghost" onClick={onCancel} disabled={loading}>{cancelLabel}</Btn>
          <Btn variant={danger ? 'danger' : 'primary'} onClick={onConfirm} disabled={loading}>{confirmLabel}</Btn>
        </div>
      </div>
    </div>
  );
};

// --- Form Modal (for non-destructive form submissions) ---
const FormModal = ({ open, title, children, confirmLabel = 'Confirm', cancelLabel = 'Cancel', onConfirm, onCancel, submitDisabled = false }) => {
  const { isMobile } = useViewport();
  if (!open) return null;
  return (
    <div onClick={onCancel}
      style={{ position: 'fixed', inset: 0, background: 'rgba(4,8,20,0.72)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000, padding: isMobile ? 12 : 0 }}>
      <div onClick={e => e.stopPropagation()}
        style={{ background: TOKEN.surface, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 14, padding: isMobile ? '18px 18px' : '22px 26px', width: 'min(95vw, 520px)', maxHeight: isMobile ? '90vh' : 'none', overflowY: isMobile ? 'auto' : 'visible', boxShadow: '0 20px 60px rgba(0,0,0,0.5)' }}>
        <div style={{ color: TOKEN.text, fontWeight: 700, fontSize: 16, marginBottom: 14 }}>{title}</div>
        <div style={{ minHeight: 60, marginBottom: 20 }}>{children}</div>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <Btn variant="ghost" onClick={onCancel}>{cancelLabel}</Btn>
          <Btn variant="primary" onClick={onConfirm} disabled={submitDisabled}>{confirmLabel}</Btn>
        </div>
      </div>
    </div>
  );
};

// --- OverflowMenu ---
// items: [{ label, icon?, onClick, disabled?, danger? }]
// Renders a "⋯" trigger button; menu opens on click, closes on backdrop click or ESC.
const OverflowMenu = ({ items, ariaLabel = 'More actions' }) => {
  const [open, setOpen] = React.useState(false);
  const { isMobile } = useViewport();
  React.useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => { if (e.key === 'Escape') setOpen(false); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open]);
  return (
    <div style={{ position: 'relative', display: 'inline-block' }}>
      <button type="button" aria-label={ariaLabel} onClick={(e) => { e.stopPropagation(); setOpen(v => !v); }}
        style={{ width: isMobile ? 44 : 30, height: isMobile ? 44 : 30, borderRadius: 8, border: `1px solid ${TOKEN.surfaceBorder}`, background: open ? TOKEN.accentDim : TOKEN.surfaceRaised, color: TOKEN.textSecondary, cursor: 'pointer', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', padding: 0 }}>
        <Icon name="moreVertical" size={isMobile ? 18 : 16} color="currentColor" />
      </button>
      {open && (
        <React.Fragment>
          <div onClick={() => setOpen(false)} style={{ position: 'fixed', inset: 0, zIndex: 50, background: 'transparent' }} />
          <div role="menu" style={{ position: 'absolute', right: 0, top: 'calc(100% + 4px)', minWidth: 180, background: TOKEN.surface, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 10, boxShadow: '0 8px 28px rgba(0,0,0,0.45)', padding: 6, zIndex: 51 }}>
            {items.map((it, idx) => (
              <button key={idx} type="button" role="menuitem" disabled={it.disabled}
                onClick={() => { if (it.disabled) return; setOpen(false); it.onClick && it.onClick(); }}
                style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px', borderRadius: 6, border: 'none', background: 'transparent', color: it.danger ? '#f87171' : TOKEN.text, fontSize: 13, fontFamily: 'inherit', textAlign: 'left', cursor: it.disabled ? 'not-allowed' : 'pointer', opacity: it.disabled ? 0.45 : 1 }}
                onMouseEnter={(e) => { if (!it.disabled) e.currentTarget.style.background = TOKEN.surfaceRaised; }}
                onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}>
                {it.icon && <Icon name={it.icon} size={14} color="currentColor" />}
                <span>{it.label}</span>
              </button>
            ))}
          </div>
        </React.Fragment>
      )}
    </div>
  );
};

// --- ProgressCounts (transcription status row) ---
const ProgressCounts = ({ counts, lang }) => {
  const t = lang === 'zh';
  const labels = t
    ? { pending: '待處理', processing: '處理中', completed: '完成', failed: '失敗' }
    : { pending: 'Pending', processing: 'Processing', completed: 'Completed', failed: 'Failed' };
  const colors = {
    pending: TOKEN.textSecondary,
    processing: TOKEN.accent,
    completed: TOKEN.success,
    failed: TOKEN.danger,
  };
  return (
    <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
      {['pending', 'processing', 'completed', 'failed'].map(k => (
        <div key={k} style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
          <span style={{ color: colors[k], fontSize: 18, fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>{counts?.[k] ?? 0}</span>
          <span style={{ color: TOKEN.textMuted, fontSize: 12 }}>{labels[k]}</span>
        </div>
      ))}
    </div>
  );
};

// --- categoryToBadge: map api_health error_category to {variant, label} ---
// Single source of truth for category→colour mapping shared by ScheduleTab
// and ExternalApiStatusTab so one category yields one consistent colour.
const categoryToBadge = (category, lang) => {
  const t = lang === 'zh';
  const map = {
    quota_exceeded: { variant: 'danger', label: t ? '額度不足' : 'Quota Exceeded' },
    auth_error: { variant: 'danger', label: t ? '認證錯誤' : 'Auth Error' },
    rate_limited: { variant: 'warning', label: t ? '速率受限' : 'Rate Limited' },
    server_error: { variant: 'warning', label: t ? '伺服器錯誤' : 'Server Error' },
    network_error: { variant: 'warning', label: t ? '網路錯誤' : 'Network Error' },
    unknown: { variant: 'muted', label: t ? '未知錯誤' : 'Unknown Error' },
  };
  return map[category] || map.unknown;
};

// --- formatRelativeTime: ts_ms epoch → "2 分鐘前" / "2 minutes ago" ---
const formatRelativeTime = (tsMs, lang) => {
  if (!tsMs) return '';
  const t = lang === 'zh';
  const diffSec = Math.max(0, Math.floor((Date.now() - tsMs) / 1000));
  if (diffSec < 60) return t ? '剛剛' : 'just now';
  const m = Math.floor(diffSec / 60);
  if (m < 60) return t ? `${m} 分鐘前` : `${m} minute${m === 1 ? '' : 's'} ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return t ? `${h} 小時前` : `${h} hour${h === 1 ? '' : 's'} ago`;
  const d = Math.floor(h / 24);
  return t ? `${d} 天前` : `${d} day${d === 1 ? '' : 's'} ago`;
};

// Episode blurb — AI summary preferred, fallback to RSS description.
// Failure (`pending` / `running` / `failed`) is invisible to users — they
// just see the original RSS description (D3 in episode-ai-summary design).
const EpisodeBlurb = ({ episode, lang, style }) => {
  if (!episode) return null;
  const useAi = episode.ai_summary_status === 'done' && episode.ai_summary;
  const text = useAi ? episode.ai_summary : (episode.description || '');
  if (!text) return null;
  const baseStyle = {
    color: TOKEN.textSecondary,
    fontSize: 12,
    lineHeight: 1.55,
    margin: 0,
    overflow: 'hidden',
    display: '-webkit-box',
    WebkitBoxOrient: 'vertical',
    WebkitLineClamp: 3,
    ...(style || {}),
  };
  // RSS description often contains HTML; AI summary is plain text.
  if (useAi) {
    return <p style={baseStyle}>{text}</p>;
  }
  return <p style={baseStyle} dangerouslySetInnerHTML={{ __html: text }} />;
};

// ─────────────────────────────────────────────────────────────────────────────
// SourceCard (R2.1 section 5)
//
// Renders a single retrieval source / citation entry. Backend now ships four
// extra fields on every ChunkHit (`before_text`, `after_text`, `highlights`,
// `ai_summary_excerpt`); this card renders them with sensible fallbacks for
// older cached responses or description-source hits that may lack them.
//
// Security: `highlights` is server-rendered HTML with `<mark>` wrappers around
// matched terms (ts_headline output). We do NOT trust the backend blindly —
// `sanitiseMarkOnly` strips every tag other than `<mark>` / `</mark>` before
// dangerouslySetInnerHTML touches it.
// ─────────────────────────────────────────────────────────────────────────────

// Strict whitelist sanitiser: keep only <mark> and </mark> (no attrs allowed).
// Everything else — <script>, <img>, <a href=...>, <mark onclick=...> etc —
// gets HTML-escaped so it renders as inert text.
const _MARK_TAG_RE = /<\/?mark>/gi;
const _MARK_PLACEHOLDER_OPEN = ' MARKOPEN ';
const _MARK_PLACEHOLDER_CLOSE = ' MARKCLOSE ';
const sanitiseMarkOnly = (html) => {
  if (typeof html !== 'string' || !html) return '';
  // 1) Stash <mark> / </mark> behind placeholders that survive escaping.
  const stashed = html
    .replace(/<mark>/gi, _MARK_PLACEHOLDER_OPEN)
    .replace(/<\/mark>/gi, _MARK_PLACEHOLDER_CLOSE);
  // 2) Escape every remaining HTML special so any `<...>` becomes text.
  const escaped = stashed
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
  // 3) Restore the placeholders as the only allowed real tags.
  return escaped
    .split(_MARK_PLACEHOLDER_OPEN).join('<mark>')
    .split(_MARK_PLACEHOLDER_CLOSE).join('</mark>');
};

const _formatTs = (sec) => {
  if (typeof sec !== 'number' || !Number.isFinite(sec)) return '--:--';
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
};

const SourceCard = ({ source, lang, onJump, position }) => {
  const t = lang === 'zh';
  const [expanded, setExpanded] = React.useState(false);
  if (!source) return null;
  const before = source.before_text || '';
  const after = source.after_text || '';
  const highlights = source.highlights || '';
  const aiSummary = source.ai_summary_excerpt || '';
  const mainText = source.text || '';
  const epTitle = source.episode_title || (t ? '片段' : 'Clip');
  const ts = source.start_time;
  const handleJump = () => {
    if (typeof onJump !== 'function') return;
    onJump(source, position);
  };
  return (
    <div className="source-card" style={{
      background: TOKEN.surface,
      border: `1px solid ${TOKEN.surfaceBorder}`,
      borderRadius: 10,
      padding: '14px 16px',
      display: 'flex',
      flexDirection: 'column',
      gap: 8,
    }}>
      {/* App.jsx sets `mark { background: transparent }` globally; restore the
          highlight inside SourceCard so server-rendered <mark> wrappers visibly
          mark matched terms. */}
      <style>{`.source-card mark { background: ${TOKEN.accent}33; color: ${TOKEN.accentHover || TOKEN.accent}; border-radius: 2px; padding: 0 2px; font-weight: 600; border-bottom: 1px solid ${TOKEN.accent}; }`}</style>
      {/* Header: episode title + timestamp */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        {typeof position === 'number' && (
          <span style={{
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            minWidth: 22, height: 22, padding: '0 6px',
            background: TOKEN.accentDim, color: TOKEN.accent,
            border: `1px solid ${TOKEN.accent}55`, borderRadius: 6,
            fontSize: 11, fontWeight: 700,
          }}>{position + 1}</span>
        )}
        <span style={{ color: TOKEN.textSecondary, fontSize: 12, flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{epTitle}</span>
        {typeof ts === 'number' && (
          <span style={{ color: TOKEN.textMuted, fontSize: 12, display: 'flex', alignItems: 'center', gap: 3, flexShrink: 0 }}>
            <Icon name="clock" size={11} /> {_formatTs(ts)}
          </span>
        )}
      </div>

      {/* Main excerpt with optional before/after context */}
      <p style={{ margin: 0, color: TOKEN.text, fontSize: 13, lineHeight: 1.65 }}>
        {before && (
          <span style={{ color: TOKEN.textMuted }}>{before.endsWith(' ') || /[　-鿿]/.test(before.slice(-1)) ? before : before + ' '}</span>
        )}
        {highlights ? (
          <span dangerouslySetInnerHTML={{ __html: sanitiseMarkOnly(highlights) }} />
        ) : (
          <span>{mainText}</span>
        )}
        {after && (
          <span style={{ color: TOKEN.textMuted }}>{after.startsWith(' ') || /[　-鿿]/.test(after.slice(0, 1)) ? after : ' ' + after}</span>
        )}
      </p>

      {/* AI summary excerpt with show-more toggle */}
      {aiSummary && (() => {
        const aiFull = source.ai_summary_full || '';
        const hasMore = aiFull && aiFull.length > aiSummary.replace(/…$/, '').length;
        const display = expanded && hasMore ? aiFull : aiSummary;
        return (
          <div style={{ fontSize: 12, color: TOKEN.textSecondary, lineHeight: 1.55 }}>
            <span style={{ color: TOKEN.textMuted, marginRight: 6, fontWeight: 600 }}>{t ? '本集摘要' : 'Summary'}:</span>
            <span>{display}</span>
            {hasMore && (
              <button type="button" onClick={() => setExpanded(v => !v)} style={{
                background: 'none', border: 'none', padding: 0, marginLeft: 6,
                color: TOKEN.accent, fontSize: 12, cursor: 'pointer', fontFamily: 'inherit',
              }}>
                {expanded ? (t ? '收合' : 'Show less') : (t ? '展開' : 'Show more')}
              </button>
            )}
          </div>
        );
      })()}

      {/* Jump button — label depends on source kind. Description hits don't
          have a meaningful timestamp (start_time=0), so we say "open episode"
          instead of "jump to segment" to set the right expectation. */}
      {typeof onJump === 'function' && typeof ts === 'number' && (() => {
        const isDescription = source.source === 'description';
        const label = isDescription
          ? (t ? '打開該集' : 'Open episode')
          : (t ? '跳到這段內容' : 'Jump to transcript');
        return (
          <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
            <button type="button" onClick={handleJump} style={{
              display: 'inline-flex', alignItems: 'center', gap: 4,
              padding: '4px 10px', background: TOKEN.bg,
              border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 6,
              color: TOKEN.accent, fontSize: 12, cursor: 'pointer',
              fontFamily: 'inherit',
            }}
              onMouseEnter={e => (e.currentTarget.style.borderColor = TOKEN.accent)}
              onMouseLeave={e => (e.currentTarget.style.borderColor = TOKEN.surfaceBorder)}>
              <Icon name={isDescription ? 'fileText' : 'play'} size={11} color={TOKEN.accent} />
              {label}
            </button>
          </div>
        );
      })()}
    </div>
  );
};

// ─── LockCardLegacy ───
// Three-state lock card used by QueryPage + landing flows:
//   state = 'anonymous'  → 🔒 + sign-in CTA
//   state = 'quota'      → 🔋 + request-quota CTA (existing flow keeps inline copy)
//   state = 'disabled'   → 🚫 + appeal CTA (disabled-user-appeal-flow)
// For 'disabled' state, when appealEnabled=false the CTA is hidden and the
// card shows contact-admin guidance instead.
const LockCardLegacy = ({ lang, state = 'anonymous', appealEnabled = true, onPrimaryClick, primaryLabel, message, subtext }) => {
  const t = lang === 'zh';
  const presets = {
    anonymous: {
      icon: '🔒',
      title: t ? '想看 AI 整段統整？' : 'Want the AI summary?',
      subtext: t ? '不用一段段拼湊。' : 'Skip stitching segments together.',
      primary: t ? '以 Google 登入解鎖' : 'Sign in with Google to unlock',
      footnote: t ? '30 次免費' : '30 free uses',
    },
    quota: {
      icon: '🔋',
      title: t ? '免費額度用完了' : 'Free quota exhausted',
      subtext: t ? '可以申請更多額度繼續使用。' : 'Request more quota to continue.',
      primary: t ? '申請更多額度' : 'Request more quota',
      footnote: null,
    },
    disabled: {
      icon: '🚫',
      title: t ? '帳號目前無法使用' : 'Account currently disabled',
      subtext: t
        ? '你的帳號目前無法使用，如果這是誤判可以提出申訴'
        : 'Your account is currently disabled. If this is a mistake, you can submit an appeal.',
      primary: t ? '提出申訴' : 'Submit Appeal',
      footnote: appealEnabled
        ? null
        : (t ? '請透過 email 聯絡管理員' : 'Please contact the admin via email'),
    },
  };
  const p = presets[state] || presets.anonymous;
  const showButton = state !== 'disabled' || appealEnabled;
  return (
    <div style={{
      maxWidth: 480,
      width: '100%',
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
      <div style={{ fontSize: 24 }}>{p.icon}</div>
      <h3 style={{ margin: 0, color: TOKEN.text, fontSize: 16, fontWeight: 700 }}>
        {p.title}
      </h3>
      <p style={{ margin: 0, color: TOKEN.textSecondary, fontSize: 13, lineHeight: 1.55 }}>
        {subtext || p.subtext}
      </p>
      {showButton && (
        <div style={{ marginTop: 6 }}>
          <Btn variant="primary" size="sm" onClick={onPrimaryClick}>
            {primaryLabel || p.primary}
          </Btn>
        </div>
      )}
      {p.footnote && (
        <div style={{ fontSize: 11, color: TOKEN.textMuted }}>{p.footnote}</div>
      )}
    </div>
  );
};

// ─── ShowCard + deriveColor (moved from PodcastSelect.jsx during
//     landing-and-mode-orchestration-redesign — PodcastSelect retired,
//     HomePage now owns the show grid). Both stay shared so any future
//     show-list surface (e.g. admin previews) can reuse them. ───
const _COLOR_PALETTE = ['#6366f1', '#22d3ee', '#f59e0b', '#22c55e', '#ec4899'];
const deriveColor = (id) => {
  if (!id) return _COLOR_PALETTE[0];
  let hash = 2166136261;
  for (let i = 0; i < id.length; i++) {
    hash ^= id.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return _COLOR_PALETTE[Math.abs(hash) % _COLOR_PALETTE.length];
};

const ShowCard = ({ show, lang, hovered, onMouseEnter, onMouseLeave, onClick }) => {
  const t = lang === 'zh';
  const episodeCount = show.episode_count || 0;
  const transcribedCount = show.transcribed_count || 0;
  const pct = episodeCount > 0 ? Math.round((transcribedCount / episodeCount) * 100) : 0;
  const color = deriveColor(show.id);

  return (
    <div onClick={onClick} onMouseEnter={onMouseEnter} onMouseLeave={onMouseLeave}
      style={{ background: TOKEN.surface, border: `1px solid ${hovered ? color + '55' : TOKEN.surfaceBorder}`, borderRadius: 14, padding: 24, cursor: 'pointer', transition: 'all 0.18s', transform: hovered ? 'translateY(-2px)' : 'none', boxShadow: hovered ? `0 8px 30px rgba(0,0,0,0.3), 0 0 0 1px ${color}33` : 'none', display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', gap: 14, alignItems: 'flex-start' }}>
        <div style={{ width: 64, height: 64, borderRadius: 12, background: color + '22', border: `1px solid ${color}44`, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, overflow: 'hidden' }}>
          {show.image_url ? (
            <img src={show.image_url} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
          ) : (
            <Icon name="mic" size={28} color={color} />
          )}
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ color: TOKEN.text, fontWeight: 700, fontSize: 16, lineHeight: 1.3, marginBottom: 4 }}>
            {show.title}
          </div>
          {show.language && (
            <div style={{ color: TOKEN.textSecondary, fontSize: 12 }}>{show.language}</div>
          )}
        </div>
      </div>
      {show.description && (
        <p style={{ color: TOKEN.textSecondary, fontSize: 13, lineHeight: 1.6, margin: 0,
          display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
          {show.description}
        </p>
      )}
      <div style={{ display: 'flex', gap: 16, fontSize: 13 }}>
        <div style={{ color: TOKEN.textSecondary }}>
          <span style={{ color: TOKEN.text, fontWeight: 600 }}>{episodeCount}</span> {t ? '集' : 'eps'}
        </div>
        <div style={{ color: TOKEN.textSecondary }}>
          <span style={{ color: '#4ade80', fontWeight: 600 }}>{transcribedCount}</span> {t ? '已轉錄' : 'transcribed'}
        </div>
      </div>
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: TOKEN.textMuted, marginBottom: 5 }}>
          <span>{t ? '轉錄進度' : 'Transcription'}</span>
          <span style={{ color: pct === 100 ? '#4ade80' : TOKEN.textSecondary, fontWeight: 600 }}>{pct}%</span>
        </div>
        <div style={{ height: 4, background: TOKEN.surfaceBorder, borderRadius: 99, overflow: 'hidden' }}>
          <div style={{ height: '100%', width: `${pct}%`, background: pct === 100 ? '#22c55e' : color, borderRadius: 99, transition: 'width 0.4s' }} />
        </div>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, color: TOKEN.textMuted, minWidth: 0, overflow: 'hidden' }}>
          <Icon name="rss" size={13} color={TOKEN.textMuted} />
          <span style={{ fontFamily: 'monospace', fontSize: 11, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {show.rss_url}
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 4, color: hovered ? color : TOKEN.textMuted, fontSize: 13, fontWeight: 500, transition: 'color 0.15s', flexShrink: 0, marginLeft: 8 }}>
          {t ? '進入節目' : 'Open Show'} <Icon name="chevronRight" size={16} color="currentColor" />
        </div>
      </div>
    </div>
  );
};

Object.assign(window, { API_BASE, TOKEN, Icon, Badge, Btn, Input, TopNav, ConfirmModal, FormModal, OverflowMenu, ProgressCounts, categoryToBadge, formatRelativeTime, useViewport, EpisodeBlurb, SourceCard, sanitiseMarkOnly, LockCardLegacy, ShowCard, deriveColor });
