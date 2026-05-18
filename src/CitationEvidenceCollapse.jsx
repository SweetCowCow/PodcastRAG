// CitationEvidenceCollapse: 在列舉佈局（enumeration_episodes 非空）下，
// 包住 chunk-level citation chips 的可摺疊容器。預設 collapsed，使用者
// 點 summary 才會展開 chip list。
//
// 設計理由（見 openspec/changes/citation-display-unify）：
// - 列舉題時 EnumerationSection 是主視覺（episode-level 整集卡），chunk
//   evidence 是輔（為什麼這幾集被選 = grounding）。並列會造成資訊重複，
//   隱藏又會丟 evidence，所以預設摺疊 + 可展開回查。
// - 沿用既有 TOKEN（surfaceRaised 背景 + textSecondary 文字），不引入
//   新 design token。
//
// Props:
//   count    -- citations.length（用於 summary 中括號計數）
//   lang     -- 'zh' | 'en'
//   children -- 既有 citation chip list（由 ChatBubble 傳入）
const CitationEvidenceCollapse = ({ count, lang, children }) => {
  const t = lang === 'zh';
  const summaryText = t
    ? `為什麼這幾集被選 (${count} 個段落)`
    : `Why these episodes (${count} excerpts)`;

  // 預設 collapsed：<details> 不帶 open 屬性
  return (
    <details
      style={{
        marginTop: 10,
        background: TOKEN.surfaceRaised,
        border: `1px solid ${TOKEN.surfaceBorder}`,
        borderRadius: 8,
        padding: '8px 10px',
      }}
    >
      <summary
        style={{
          cursor: 'pointer',
          fontSize: 12,
          color: TOKEN.textSecondary,
          fontWeight: 500,
          userSelect: 'none',
          listStyle: 'revert',
          outline: 'none',
        }}
      >
        {summaryText}
      </summary>
      <div style={{ marginTop: 8 }}>{children}</div>
    </details>
  );
};

Object.assign(window, { CitationEvidenceCollapse });
