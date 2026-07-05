## Context

2026-07-05 mobile audit(docs/research/eq12-mobile-audit/audit-report.md)確認手機版六個 RWD 缺陷。全站為 React 18 CDN + Babel Standalone、全 inline styles、共用斷點 hook `useViewport()`(`isMobile = innerWidth < 768`,規範見 spec `frontend-responsive-layout`)。無打包器,任何修改直接生效於 prod 靜態檔。

關鍵前置事實(已於 audit 對源碼驗證):

- 節目卡 grid 位於 src/HomePage.jsx 的 shows grid(`gridTemplateColumns: isMobile ? '1fr' : 'repeat(auto-fill, minmax(320px, 1fr))'`);`'1fr'` 等價 `minmax(auto, 1fr)`,min-content 被 ShowCard 內不換行 RSS URL 撐至 1176px。
- `ShowCard` 存在兩份定義:src/HomePage.jsx 的 inline 版(實際渲染)與 src/Shared.jsx 的 window export 版(現無任何引用點,屬遺留)。
- Btn base style(src/Shared.jsx)已有 `isMobile && { minHeight: 44, minWidth: 44 }` 但無 `whiteSpace` 設定。
- ASR 校正 tab 有兩個 `<table>`(規則列表與候選列表),外層皆無 `overflowX` 容器;對照組:使用者管理 tab 的 table 有捲動容器且手機可用。
- 對話頁底部固定區 = TrendingQueriesChips 範例區 + 輸入列(src/QueryPage.jsx),實測佔 375×667 畫面約 40% 高。

## Goals / Non-Goals

**Goals**

- 手機(<768px)上:首頁節目卡完整可見可點、對話 citation 卡引文與操作列可讀、全站按鈕文字不直排、對話輸入區不吃掉近半螢幕、ASR 校正表格內容可達、admin active tab 可見。
- 修正皆為 layout 層,不改任何資料流、API 呼叫與business 邏輯。

**Non-Goals**

- AI 氣泡縮排優化、使用者管理 table 卡片化、逐字稿時間欄壓縮、金鑰列 icon 位置(audit P2-7/P3)。
- `?show_id=` deep link routing 修正。
- 平板與 landscape 斷點、三模式整合。
- 移除 Shared.jsx 的遺留 ShowCard(清理另案;本次僅同步防護)。

## Decisions

1. **grid 防護採 `minmax(0, 1fr)` 而非只修 URL**:URL ellipsis 治標,`minmax(0, …)` 治本(未來任何不換行內容都不會再撐爆欄寬)。兩者都做。桌機分支 `repeat(auto-fill, minmax(320px, 1fr))` 同步改為 `repeat(auto-fill, minmax(min(320px, 100%), 1fr))` 等效防護,避免 <352px 視窗(320px 卡 + gap)溢出。
2. **ShowCard 雙定義:兩份同步修、不刪**。實際渲染走 HomePage inline 版(該檔頂部註解記載 B4 hotfix 刻意 inline);Shared.jsx 版雖無引用點仍在 window export 名單,刪除屬清理範疇、風險不對稱,本次僅同步加相同防護以免未來誤用時復發。
3. **Btn 直排修在 base style 而非個案**:Btn base 加 `whiteSpace: 'nowrap'`。風險:既有窄容器內的長 label(尤其英文)從換行變溢出。緩解:實作後以中英兩語系掃描主要頁面(home/query/admin 前三 tab)確認無按鈕溢出其容器;個別超長 label 若溢出,該處以縮短 label 或允許該顆 override 處理,不回退全域 nowrap。
4. **範例 chips 收合邏輯放 QueryPage 層**:以「對話串是否已有訊息」為收合條件(messages.length > 0 時預設收合),收合後保留一列可點的「範例」開關(重新展開);不動 TrendingQueriesChips 內部資料邏輯,只包一層收合容器。桌機維持現狀(僅 isMobile 分支收合)。
5. **citation 卡減層以「調 isMobile padding」為主、不重構元件樹**:ConversationSourcePanel 與 SegmentCitationCard 各層在 isMobile 時縮減水平 padding/margin(目標:內容有效寬 ≥ 85% 氣泡寬);操作列按鈕靠 Decision 3 的 nowrap 恢復單行。若 nowrap 後操作列兩鈕同行放不下,允許兩鈕縱向堆疊(各自完整單行),不允許字元直排。
6. **admin tab bar 用 scrollIntoView 不改 dropdown**:active tab 變更時 `scrollIntoView({ inline: 'nearest', behavior: 'smooth' })`(初次 mount 用 `auto` 避免載入動畫);改 dropdown 影響操作習慣且工大,tab 數再增長時另議。
7. **ASR 表格捲動容器比照使用者管理 tab 既有做法**:兩個 table 各包一層 `overflowX: 'auto'` 容器,table 設 `minWidth` 保持欄位可讀,不做欄位裁剪或卡片化。

## Implementation Contract

修正完成後,以下皆可觀察驗證(mobile emulation 375×667、DPR2、touch;方法同 audit 的 overflow offender 掃描):

1. home(登入前後)無任何「自身寬 > viewport+4px 且父層不超寬」的元素;每張節目卡的「進入節目」按鈕與 RSS 行皆在 viewport 內可點/可見(RSS 以 ellipsis 截斷)。
2. 對話跑一題後:citation 卡引文區有效寬 ≥ 85% 氣泡寬;「播放此段」「跳到逐字稿」文字單行呈現。
3. home「挑一個節目找找看」、query「送出」「搜尋」、admin「新增金鑰」按鈕文字單行(中英兩語系)。
4. 對話串有訊息時,底部固定區(收合後)高度 ≤ 25% viewport 高;點「範例」開關可重新展開 chips。
5. ASR 校正 tab 兩個 table 可水平捲動至最右欄,無被切死內容。
6. admin 切到「服務用量」等後段 tab 時,該 tab 於 tab bar 可視範圍內。
7. 桌機(≥768px)上述區域 layout 與現狀一致(以 1280px viewport 抽掃 home/query/admin 三頁無新增 offender、無視覺回歸)。

## Risks / Trade-offs

- **Btn 全域 nowrap 的溢出風險**:見 Decision 3 緩解;驗收含中英掃描。
- **桌機回歸**:所有修改包在 isMobile 分支或等效不變式(`minmax(0,1fr)` 在桌機 auto-fill 下行為不變);Implementation Contract 第 7 點把桌機抽掃列為必驗。
- **Babel Standalone 無編譯期檢查**:純 style 物件修改,靠 prod smoke + emulation 掃描把關(本專案既有慣例)。
