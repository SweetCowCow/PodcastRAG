// ModeTrioIntro — landing-and-mode-orchestration-redesign decision 9.
//
// Educational, NON-CLICKABLE three-card row on HomePage middle band. Each
// card shows: title, what-it's-for description, ONE fixed example query,
// and a quota badge. On viewport < 768 px the cards stack vertically.
//
// Cards intentionally have no cursor:pointer / hover navigation — per
// design decision 9 they only set user expectations before they enter
// QueryPage.

const ModeTrioIntro = ({ lang }) => {
  const t = lang === 'zh';
  const { isMobile } = useViewport();
  const cards = [
    {
      key: 'index',
      icon: '🔎',
      titleKey: 'mode_card_index_title',
      descKey: 'mode_card_index_desc',
      exampleKey: 'mode_card_index_example',
      quotaKey: 'mode_card_index_quota',
      quotaVariant: 'success',
    },
    {
      key: 'semantic',
      icon: '🧭',
      titleKey: 'mode_card_semantic_title',
      descKey: 'mode_card_semantic_desc',
      exampleKey: 'mode_card_semantic_example',
      quotaKey: 'mode_card_semantic_quota',
      quotaVariant: 'success',
    },
    {
      key: 'chat',
      icon: '💬',
      titleKey: 'mode_card_chat_title',
      descKey: 'mode_card_chat_desc',
      exampleKey: 'mode_card_chat_example',
      quotaKey: 'mode_card_chat_quota',
      quotaVariant: 'warning',
    },
  ];
  return (
    <section
      data-testid="mode-trio-intro"
      style={{
        padding: isMobile ? '24px 16px' : '48px 24px',
        maxWidth: 1100,
        margin: '0 auto',
        width: '100%',
      }}
    >
      <div style={{ textAlign: 'center', marginBottom: 24 }}>
        <h2 style={{
          margin: 0, color: TOKEN.text, fontSize: isMobile ? 18 : 22, fontWeight: 700,
        }}>
          {t ? '三種找答案的方式' : 'Three ways to find answers'}
        </h2>
        <p style={{
          margin: '8px 0 0', color: TOKEN.textSecondary, fontSize: 13, lineHeight: 1.6,
        }}>
          {t
            ? '依問題類型挑模式，搭配使用效率最高。'
            : 'Pick the mode that fits your question — they compose well.'}
        </p>
      </div>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: isMobile ? '1fr' : 'repeat(3, minmax(0, 1fr))',
          gap: 16,
        }}
      >
        {cards.map(c => (
          <div
            key={c.key}
            data-testid={`mode-trio-card-${c.key}`}
            // Intentionally NO cursor:pointer / onClick — purely educational.
            style={{
              background: TOKEN.surface,
              border: `1px solid ${TOKEN.surfaceBorder}`,
              borderRadius: 12,
              padding: '18px 18px 16px',
              display: 'flex',
              flexDirection: 'column',
              gap: 10,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ fontSize: 22 }}>{c.icon}</span>
              <span style={{ color: TOKEN.text, fontSize: 16, fontWeight: 700 }}>
                {uiString(c.titleKey, lang)}
              </span>
              <span style={{ flex: 1 }} />
              <Badge variant={c.quotaVariant}>{uiString(c.quotaKey, lang)}</Badge>
            </div>
            <p style={{ margin: 0, color: TOKEN.textSecondary, fontSize: 13, lineHeight: 1.6 }}>
              {uiString(c.descKey, lang)}
            </p>
            <div
              style={{
                marginTop: 4,
                padding: '8px 10px',
                background: TOKEN.bg,
                border: `1px dashed ${TOKEN.surfaceBorder}`,
                borderRadius: 8,
                color: TOKEN.textMuted,
                fontSize: 12,
                lineHeight: 1.55,
              }}
            >
              {uiString(c.exampleKey, lang)}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
};

Object.assign(window, { ModeTrioIntro });
