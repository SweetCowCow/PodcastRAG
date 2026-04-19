// Shared components: tokens, icons, Nav, Layout
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
    trash: <svg viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={s}><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4h6v2"/></svg>,
    globe: <svg viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={s}><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>,
    arrowLeft: <svg viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={s}><line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/></svg>,
    fileText: <svg viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={s}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>,
    zap: <svg viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={s}><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>,
    podcast: <svg viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={s}><circle cx="12" cy="11" r="1"/><path d="M11 17a1 1 0 0 1 2 0c0 .5-.34 3-.5 4.5a.5.5 0 0 1-1 0c-.16-1.5-.5-4-.5-4.5z"/><path d="M8 14a5 5 0 1 1 8 0"/><path d="M5 18a9 9 0 1 1 14 0"/></svg>,
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
  const base = {
    display: 'inline-flex', alignItems: 'center', gap: 6, borderRadius: 8,
    cursor: disabled ? 'not-allowed' : 'pointer', border: 'none', fontWeight: 500,
    transition: 'all 0.15s', opacity: disabled ? 0.5 : 1, fontFamily: 'inherit',
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
const Input = ({ value, onChange, placeholder, type = 'text', icon, style: extraStyle = {} }) => {
  const [focused, setFocused] = React.useState(false);
  return (
    <div style={{ position: 'relative', width: '100%' }}>
      {icon && <span style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none', color: TOKEN.textMuted }}><Icon name={icon} size={16} /></span>}
      <input value={value} onChange={onChange} placeholder={placeholder} type={type}
        onFocus={() => setFocused(true)} onBlur={() => setFocused(false)}
        style={{ width: '100%', boxSizing: 'border-box', background: TOKEN.surfaceRaised, border: `1px solid ${focused ? TOKEN.accent : TOKEN.surfaceBorder}`, borderRadius: 8, padding: icon ? '9px 12px 9px 36px' : '9px 12px', color: TOKEN.text, fontSize: 14, outline: 'none', fontFamily: 'inherit', transition: 'border 0.15s', ...extraStyle }} />
    </div>
  );
};

// --- Top Nav ---
const TopNav = ({ lang, page, setPage, onToggleLang, onAdminClick }) => {
  const t = lang === 'zh';
  const isAdmin = page && page.startsWith('admin');

  const mainItems = [
    { id: 'select', icon: 'podcast', label: t ? '節目選擇' : 'Shows' },
    { id: 'admin', icon: 'settings', label: t ? '後台管理' : 'Admin' },
  ];
  const adminItems = [
    { id: 'admin-api', icon: 'key', label: t ? 'API 金鑰' : 'API Keys' },
    { id: 'admin-llm', icon: 'brain', label: t ? 'LLM 模型' : 'LLM Models' },
    { id: 'admin-rag', icon: 'database', label: t ? 'RAG 設定' : 'RAG Config' },
    { id: 'admin-schedule', icon: 'calendar', label: t ? '轉錄排程' : 'Transcription' },
  ];

  return (
    <div style={{ flexShrink: 0, borderBottom: `1px solid ${TOKEN.surfaceBorder}`, background: TOKEN.surface }}>
      {/* Primary bar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 0, padding: '0 28px', height: 56 }}>
        {/* Logo */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginRight: 32 }}>
          <div style={{ width: 28, height: 28, borderRadius: 7, background: TOKEN.accentDim, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Icon name="zap" size={15} color={TOKEN.accent} />
          </div>
          <span style={{ color: TOKEN.text, fontWeight: 700, fontSize: 15 }}>PodcastRAG</span>
          <span style={{ color: TOKEN.textMuted, fontSize: 11, marginLeft: -4 }}>beta</span>
        </div>

        {/* Main nav items */}
        <nav style={{ display: 'flex', alignItems: 'stretch', gap: 2, flex: 1 }}>
          {mainItems.map(item => {
            const active = item.id === 'select' ? !isAdmin && (page === 'select' || page === 'query' || page === 'transcript') : isAdmin;
            return (
              <TopNavItem key={item.id} icon={item.icon} label={item.label} active={active}
                onClick={() => item.id === 'admin' ? onAdminClick() : setPage(item.id)} />
            );
          })}
        </nav>

        {/* Right: lang toggle */}
        <button onClick={onToggleLang}
          style={{ display: 'flex', alignItems: 'center', gap: 6, background: TOKEN.surfaceRaised, border: `1px solid ${TOKEN.surfaceBorder}`, borderRadius: 7, padding: '5px 11px', color: TOKEN.textSecondary, cursor: 'pointer', fontSize: 13, fontFamily: 'inherit' }}>
          <Icon name="globe" size={13} />
          {lang === 'zh' ? '中文' : 'EN'}
        </button>
      </div>

      {/* Admin secondary bar */}
      {isAdmin && (
        <div style={{ display: 'flex', alignItems: 'stretch', padding: '0 28px', height: 42, borderTop: `1px solid ${TOKEN.surfaceBorder}`, background: TOKEN.bg, gap: 2 }}>
          {adminItems.map(item => (
            <TopNavItem key={item.id} icon={item.icon} label={item.label} active={page === item.id}
              onClick={() => setPage(item.id)} secondary />
          ))}
        </div>
      )}
    </div>
  );
};

const TopNavItem = ({ icon, label, active, onClick, secondary }) => {
  const [hovered, setHovered] = React.useState(false);
  return (
    <button onClick={onClick} onMouseEnter={() => setHovered(true)} onMouseLeave={() => setHovered(false)}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 6,
        padding: secondary ? '0 14px' : '0 16px',
        height: '100%', background: 'none', border: 'none',
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

Object.assign(window, { TOKEN, Icon, Badge, Btn, Input, TopNav });
