// QuotaMeter — visual remaining-quota indicator + "Request more" CTA.
// Renders only for authenticated users; anonymous callers see no meter.
const QuotaMeter = ({ user, lang, onApply }) => {
  if (!user) return null;
  const t = lang === 'zh';
  const initial = user.quota_initial || 0;
  const remaining = user.quota_remaining || 0;
  const used = Math.max(0, initial - remaining);
  const ratio = initial > 0 ? Math.min(1, used / initial) : 0;
  const lowQuota = remaining <= 5;

  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      gap: 12,
      padding: '8px 16px',
      background: TOKEN.surface,
      borderBottom: `1px solid ${TOKEN.surfaceBorder}`,
      fontSize: 13,
      color: TOKEN.textSecondary,
      flexShrink: 0,
    }}>
      <span style={{ fontSize: 14 }}>🪙</span>
      <span>{t ? 'AI 額度' : 'AI quota'}</span>
      <div style={{
        flex: 1,
        height: 8,
        borderRadius: 99,
        background: TOKEN.surfaceBorder,
        overflow: 'hidden',
        maxWidth: 240,
      }}>
        <div style={{
          height: '100%',
          width: `${ratio * 100}%`,
          background: lowQuota ? '#f59e0b' : TOKEN.accent,
          transition: 'width 200ms',
        }} />
      </div>
      <span style={{
        whiteSpace: 'nowrap',
        color: lowQuota ? '#f59e0b' : TOKEN.text,
        fontVariantNumeric: 'tabular-nums',
      }}>
        {used} / {initial} {t ? '已用' : 'used'}
      </span>
      <Btn size="sm" variant="ghost" onClick={onApply}>
        {t ? '申請更多額度 →' : 'Request more →'}
      </Btn>
    </div>
  );
};

Object.assign(window, { QuotaMeter });
