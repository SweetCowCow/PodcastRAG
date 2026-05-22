// LockCard v2 — landing-and-mode-orchestration-redesign decision 3.
//
// Covers the Chat tab answer area in two states:
//   variant = 'anonymous'        → 🔒 + Google login CTA + 「先用語意搜尋」secondary link
//   variant = 'quota_exhausted'  → ⏳ + Apply-for-quota CTA + 「先用語意搜尋」secondary link
//
// Copy is sourced from i18n.jsx UI_STRINGS (lockcard_anon_* / lockcard_quota_*)
// and is the definitive 定版 — must NOT contain「免費」「N 次」「重置」「自動恢復」
// or any concrete reset-time language (design.md non-goal §3).
//
// Props:
//   variant : 'anonymous' | 'quota_exhausted'   (unknown → renders fallback)
//   lang    : 'zh' | 'en'
//   onLogin       : called when anon CTA clicked
//   onApplyQuota  : called when quota_exhausted CTA clicked (opens QuotaApplyModal)
//   onTrySemantic : called when「先用語意搜尋」secondary link clicked
//
// Test ids (per task 5.4):
//   data-testid="lockcard"               (root)
//   data-testid="lockcard-cta-primary"   (main button)
//   data-testid="lockcard-cta-semantic"  (secondary link)

const LockCard = ({ variant, lang, onLogin, onApplyQuota, onTrySemantic }) => {
  const t = lang === 'zh';
  if (variant !== 'anonymous' && variant !== 'quota_exhausted') {
    // Defensive fallback per design Failure Modes — render minimal「請登入」
    return (
      <div data-testid="lockcard" data-variant="fallback" style={{
        maxWidth: 480, width: '100%',
        background: TOKEN.surface, border: `1px solid ${TOKEN.surfaceBorder}`,
        borderRadius: 12, padding: '20px 24px', textAlign: 'center',
        color: TOKEN.textSecondary, fontSize: 13,
      }}>
        {t ? '請登入後繼續使用對話模式。' : 'Please sign in to use chat mode.'}
      </div>
    );
  }

  const isAnon = variant === 'anonymous';
  const emoji = uiString(isAnon ? 'lockcard_anon_emoji' : 'lockcard_quota_emoji', lang);
  const title = uiString(isAnon ? 'lockcard_anon_title' : 'lockcard_quota_title', lang);
  const body = uiString(isAnon ? 'lockcard_anon_body' : 'lockcard_quota_body', lang);
  const ctaLabel = uiString(isAnon ? 'lockcard_anon_cta' : 'lockcard_quota_cta', lang);
  const secPrefix = uiString('lockcard_anon_secondary_prefix', lang);
  const secLink = uiString('lockcard_anon_secondary_link', lang);
  const secSuffix = uiString('lockcard_anon_secondary_suffix', lang);

  const handlePrimary = () => {
    if (isAnon) { onLogin && onLogin(); }
    else { onApplyQuota && onApplyQuota(); }
  };

  return (
    <div
      data-testid="lockcard"
      data-variant={variant}
      style={{
        maxWidth: 520,
        width: '100%',
        background: TOKEN.surface,
        border: `1px solid ${TOKEN.surfaceBorder}`,
        borderRadius: 14,
        padding: '28px 28px 24px',
        textAlign: 'center',
        display: 'flex',
        flexDirection: 'column',
        gap: 12,
      }}
    >
      <div style={{ fontSize: 34, lineHeight: 1 }}>{emoji}</div>
      <h3 style={{ margin: 0, color: TOKEN.text, fontSize: 18, fontWeight: 700, lineHeight: 1.35 }}>
        {title}
      </h3>
      <p style={{ margin: 0, color: TOKEN.textSecondary, fontSize: 14, lineHeight: 1.65 }}>
        {body}
      </p>
      <div style={{ marginTop: 4 }}>
        <Btn
          variant="primary"
          size="md"
          onClick={handlePrimary}
          data-testid="lockcard-cta-primary"
        >
          {ctaLabel}
        </Btn>
      </div>
      <div style={{ fontSize: 12, color: TOKEN.textMuted, lineHeight: 1.6 }}>
        {secPrefix}
        <button
          type="button"
          onClick={() => onTrySemantic && onTrySemantic()}
          data-testid="lockcard-cta-semantic"
          style={{
            background: 'transparent', border: 'none', padding: 0,
            color: TOKEN.accent, cursor: 'pointer', fontFamily: 'inherit', fontSize: 12,
            textDecoration: 'underline',
          }}
        >
          {secLink}
        </button>
        {secSuffix}
      </div>
    </div>
  );
};

Object.assign(window, { LockCard });
