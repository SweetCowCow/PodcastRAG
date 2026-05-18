## 1. 新元件 CitationEvidenceCollapse

- [x] 1.1 新建 `src/CitationEvidenceCollapse.jsx`：含 `<details>` + `<summary>` 結構；props = `{ count, lang, children }`；summary 文案：zh `為什麼這幾集被選 (${count} 個段落)`、en `Why these episodes (${count} excerpts)`；預設 collapsed (`<details>` 不帶 `open`)；視覺對齊既有 TOKEN（surfaceRaised 背景 + textSecondary 文字）。完成標準：手動瀏覽器 toggle props 看 collapsed/expanded 兩態樣式正確；HTML 入口 `PodcastRAG.html` 需 `<script type="text/babel" src="src/CitationEvidenceCollapse.jsx">` 引入

## 2. ChatBubble 條件渲染

- [x] 2.1 修改 `src/QueryPage.jsx` 的 ChatBubble component：把現有「EnumerationSection + citations chip list」並列佈局拆兩支：
  - 列舉佈局：`enumerationEpisodes?.length > 0` 時 → EnumerationSection 上、`<CitationEvidenceCollapse count={citations.length} lang={lang}>` 包住既有 citation chip + SourceCard 渲染、放在 EnumerationSection 下方
  - 內容佈局：`!enumerationEpisodes?.length` 時 → 既有 chip 渲染不動（完全無 EnumerationSection、無 collapse）
  完成標準：grep `enumerationEpisodes?.length > 0` `src/QueryPage.jsx` 至少 1 處；本機開瀏覽器驗證三題 sample（馬世芳 enum 非空 / EP143 content 題 / 歌單 topic-trigger）三種佈局正確
- [x] 2.2 確保 `citation_click` event 在 collapsed→expanded 後點 chip 仍正確發送（不因 `<details>` 包住跳過 event handler）。完成標準：手動展開 collapse、點 chip、看 Network panel 確認 `POST /events` 含 `citation_click` + chunk_id

## 3. 視覺驗證

- [x] 3.1 prod-like 環境瀏覽器驗證三題：
  - Q1「馬世芳上過哪幾集」→ 上方 EnumerationSection 兩張 card、下方折疊 summary「為什麼這幾集被選 (2 個段落)」、展開後看到 chip
  - Q2「EP143 講了什麼」→ 無 EnumerationSection、chip 直接 inline 渲染（無折疊）
  - Q3「歌單」→ 上方 EnumerationSection（topic-trigger 觸發）、下方折疊；展開後 chunk evidence 完整
  完成標準：三題各截一張 screenshot 留 `/tmp/citation-unify-{q1,q2,q3}.png`、user 目視確認
- [x] 3.2 [P] 中英雙語切換驗證：折疊 summary 文案在 zh / en 兩種 lang 下分別顯示正確中文 / 英文。完成標準：lang=zh `為什麼這幾集被選 (N 個段落)` / lang=en `Why these episodes (N excerpts)` 兩者各一張 screenshot

## 4. 部署

- [x] 4.1 commit + push → Zeabur frontend service 自動 rebuild。完成標準：`zeabur deployment list --service-id 69eb27320da29f05f49a5260 --json | jq '.[0].status'` 回 RUNNING + commit SHA 是新的
- [x] 4.2 prod 用三題 sample 跑同樣的視覺驗證；user 2026-05-18 驗證：「歌單」題 EnumerationSection 列 23 集正確、collapse 預設收起；「EP143 講了什麼」內容佈局正確（無 EnumerationSection、chips inline）。視覺渲染 100% 通過。

## 5. 收尾

- [x] 5.1 Release log 起草：補 `src/releaseLog.jsx` entry（單一 source of truth）
- [x] 5.2 [P] 更新 memory `project_pending_followups.md` 把第 2 點 `citation-display-unify` 標 `✅ 已完成 2026-05-18`
