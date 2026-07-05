## Summary

依 2026-07-05 mobile audit(docs/research/eq12-mobile-audit/audit-report.md)修復手機版六個 RWD 缺陷:首頁節目卡爆寬(P0)、對話 citation 卡壓扁與全站按鈕文字直排(P1)、對話頁底部固定區過高、ASR 校正表格溢出不可捲、admin tab bar 不跟隨 active tab(P2)。

## Motivation

2026-07-05 以 Chrome DevTools mobile emulation(375×667 主掃 + 320×568 抽驗)對 prod 全站 audit,發現:

1. **P0**:home「收錄節目」每張卡實寬 1176px,手機只見左側一小塊,「進入節目」按鈕在三個螢幕寬外 — 手機使用者實質無法從首頁進入節目。根因已對源碼驗證:節目卡 grid 的手機分支用 `gridTemplateColumns: '1fr'`,`1fr` 的 min 是 min-content,被 ShowCard 內不換行的長 RSS URL 撐爆(320/375px 下皆恆為 1176px,證明與 viewport 無關)。
2. **P1**:對話回應的 citation 來源卡多層巢狀 padding 疊加,內容區僅剩約 1/3 螢幕寬,引文一行 8–9 字、「播放此段」「跳到逐字稿」按鈕一字一行直排。
3. **P1**:Shared.jsx 的 Btn 未設 `whiteSpace: 'nowrap'`,窄容器下「送出」「搜尋」「新增金鑰」全變直排,全站受影響。
4. **P2**:對話頁底部固定區(範例 chips + 輸入框)佔約 40% 螢幕高,對話開始後 chips 不收合。
5. **P2**:ASR 校正 tab 的 table(414px)外層無橫向捲動容器,右緣內容被切死。
6. **P2**:admin tab bar 14 個 tab 可橫捲,但切換後不自動捲到 active tab,active tab 常在畫面外。

## Proposed Solution

依 audit 報告建議順序,六個問題各一刀:

1. **節目卡 grid**:手機分支 `'1fr'` 改 `'minmax(0, 1fr)'`,桌機分支 `repeat(auto-fill, minmax(320px, 1fr))` 同步加 `minmax(0, …)` 防護;ShowCard 內 RSS URL 行加 `minWidth: 0` + 單行 ellipsis。注意 ShowCard 目前有兩份定義(src/HomePage.jsx 與 src/Shared.jsx),需確認實際渲染來源,消除或同步另一份,避免修了沒生效。
2. **citation 卡減層**:ConversationSourcePanel 與 SegmentCitationCard 在 `isMobile` 時縮減外層 padding/margin 疊層,目標內容區有效寬度 ≥ 85% 氣泡寬;卡內操作列(播放此段/跳到逐字稿)維持單行不直排。
3. **Btn nowrap**:Shared.jsx Btn base style 加 `whiteSpace: 'nowrap'`,並檢查中英兩語系下既有頁面無按鈕溢出(特別是英文較長 label)。
4. **對話頁底部區**:對話串有訊息後收合範例 chips 區(保留可再展開的入口),底部固定區高度以不超過 25% 螢幕高為目標。
5. **ASR 校正表格**:兩處 table 外層加 `overflowX: 'auto'` 捲動容器(比照使用者管理 tab 的既有做法)。
6. **admin tab bar**:tab 切換時對 active tab 執行 `scrollIntoView`(水平方向、平滑捲動),初次進入 admin 亦然。

修正完成後以 mobile emulation 對 prod 重掃驗證(overflow offender 掃描歸零 + 逐項截圖比對),再真機 Safari 抽驗 P0 與對話頁。

## Non-Goals

- P2-7(AI 氣泡縮排利用率)與 P3 各項(使用者管理 table 卡片化、逐字稿時間欄寬、admin 金鑰列 icon 貼邊)— 小磨損,順手才做,不入本 change 驗收。
- `?show_id=` 單獨 deep link 落回 home 的 routing 問題 — 非 RWD 範疇,另案處理。
- 平板(768–1024)與 landscape 斷點調整 — 本次僅處理 <768 手機斷點。
- 三查詢模式整合等產品層調整(Backlog 既有項目,不混入)。

## Alternatives Considered

- **只修 URL ellipsis 不動 grid**:URL 修了仍可能被未來其他不換行內容(長英文標題等)再次撐爆;`minmax(0, 1fr)` 是結構性防護,兩者都做。
- **admin tab bar 改手機 dropdown**:改動面大且影響操作習慣,先用 scrollIntoView 低成本解;若日後 tab 持續增加再評估。

## Impact

- Affected specs: `frontend-responsive-layout`(modified:新增 grid min-width 防護、Btn nowrap、admin tab bar 跟隨、對話底部區高度規範)、`home-page`(modified:節目卡手機版單欄不溢出)、`conversation-source-panel`(modified:手機版內容寬度保障)、`admin-asr-correction-ui`(modified:table 橫捲容器)
- Affected code:
  - Modified:
    - src/HomePage.jsx
    - src/Shared.jsx
    - src/ConversationSourcePanel.jsx
    - src/SegmentCitationCard.jsx
    - src/QueryPage.jsx
    - src/TrendingQueriesChips.jsx
    - src/AdminAsrCorrectionTab.jsx
    - src/AdminPage.jsx
  - New: (none)
  - Removed: (none)
