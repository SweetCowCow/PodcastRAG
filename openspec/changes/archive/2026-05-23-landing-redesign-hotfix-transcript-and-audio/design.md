## Context

landing-and-mode-orchestration-redesign 在 2026-05-23 archive，commit `a0dc86b` 已 ship 到 prod。當天稍晚做 prod chrome-devtools smoke 抓到 4 個 visual / behavior regression（細節見 `proposal.md`）。

關鍵 evidence（2026-05-23 採集）：
- `https://podcastrag-api.zeabur.app/episodes/6bd0dbce-ad91-4264-bb55-025f527703e1/transcript` 回 `2512` 個 segment；前 2 個 segment 的 `start_time / end_time` 顯示 `end_time(prev) == start_time(next)`（gap 全 0），`speaker` 欄位 **2512 個全 null**。
- `src/utils/aggregateParagraphs.js` 的 split 條件是 `(gap >= gap_threshold_seconds) || (speakerChanged)`；前者全 0、後者雙 null 不算 change（line 59 條件 `cur.speaker != null && speaker != null`），結果整集 2512 個 segment 合成 **1 個 paragraph**。
- TranscriptPage 截圖顯示右側 scroller `scrollHeight=8626`、`scrollTop=7857`、內部只 1 個 `00:00` timestamp，跟上述推論一致。
- TranscriptPage top bar `<Btn icon="play">{從此處播放}</Btn>` 條件 `{audio && episode && episode.audio_url && ...}`（`src/TranscriptPage.jsx:135-147`），DOM 實測 button 不存在。同畫面 `useAudioPlayer` context 已 mount（`AudioPlayerProvider` 在 `src/App.jsx:315` wrap App），`audio_url` API 已驗回傳正常（曼報 EP127 = `https://m.cdn.firstory.me/track/...mp3`），所以是哪個條件 short-circuit 仍待 implementation 階段在 browser console log 出 `[audio, episode, episode?.audio_url]` 三值定案。
- HomePage 的 ShowCard 用 `window.ShowCard`（grep `src/` 找不到定義 — 舊版 PodcastSelect.jsx 已刪檔，prod build 應仍含舊 ShowCard 邏輯快取）；舊版 `show.description` 直接 `{show.description}` 渲染，沒 strip。

依賴的兩條 memory（決策不重複收錄）：
- `feedback_browser_verification.md` — UI 改動 ship 後必 chrome-devtools 全流程驗
- `feedback_migration_entrypoint_check.md` — 階段式變更要驗 entrypoint

## Goals / Non-Goals

**Goals:**

- 修 B1：無 speaker label + 連續 segment 的 ASR 輸出能合理切段（一集 80 分 podcast 至少切 ≥ 20 個 paragraph block，不再整集黏一段）。
- 修 B2：TranscriptPage「從此處播放」按鈕 100% render（只要 `episode.audio_url` 非空），點擊能成功啟動 audio playback + 浮出 StickyAudioBar。
- 修 B3：URL `?t=<sec>` deep link 進 TranscriptPage 後，畫面 scroll 到該 timestamp 對應 paragraph 並 highlight（行為跟 R2.1 既有 deep-link 規則一致 — ±5 秒 window 內才 highlight）。
- 修 B4：HomePage ShowCard description 顯示為純文字（`<br />` 換行、其他 tag 移除、HTML entity decode 為 visible char）。
- 4 個 fix 都附 chrome-devtools-mcp prod smoke 驗證 evidence。

**Non-Goals:**

- 不重新設計 paragraph 視覺樣式 / 不調整 paragraph block 內排版。
- 不動 backend transcript / episode API shape（不要求 server 補 paragraph hint 或 speaker diarization）。
- 不離線重跑既有 episode 的 ASR / diarization。
- 不修 ShowCard 整體版型 / 不改 description 折行 / 不調 EpisodeBlurb（後者已用 `WebkitLineClamp` 截斷，本 change 不動）。
- 不併 admin-quota-bypass-fix（獨立後續 change，本 hotfix 不依賴它）。
- 不動 audio player core 行為 — `StickyAudioBar`、`playFromTime`、speed control 等本身正常，只負責「能進入播放狀態」。
- 不開新 capability — 全部走 modified capability delta。

## Decisions

### D1 — aggregateParagraphs 改用四條件切段

加兩條 fallback 條件（任一成立即切新段）：

| Trigger | 條件 | Default 值 |
|---|---|---|
| (a) silence gap | `start(next) - end(prev) >= gap_threshold_seconds` | 1.5 |
| (b) speaker change | `prev.speaker != null && next.speaker != null && prev.speaker !== next.speaker` | — |
| (c) max duration | `cumulative_paragraph_duration >= max_paragraph_seconds` | 45 |
| (d) sentence end + min duration | `prev.text 結尾為 [。！？.!?] && cumulative_paragraph_duration >= min_paragraph_seconds` | 15 |

預設值 rationale：
- `max_paragraph_seconds=45` — 中文 podcast 一段話約 30-60 秒；45 秒上限避免 paragraph 過長難讀，又不會把同一話題切過碎。
- `min_paragraph_seconds=15` — 避免短句尾標點（譬如「對。」「嗯。」）馬上切段造成碎屑。
- (c) 是 hard ceiling 保證最壞情況下也會切；(d) 是 soft preference 讓自然句尾切點優於硬切。

對 80 分鐘 podcast（n=2512 segment）的預期：硬切上限 4800 / 45 ≈ 106 段；實際因 (d) 自然句尾介入會更多但每段 15-45 秒間。

切段條件評估順序：先 (a)，再 (b)，再 (c)，最後 (d)。前者命中就 short-circuit。

### D2 — 「從此處播放」button 改為「audio_url 在就一定 render」

當前條件 `{audio && episode && episode.audio_url && ...}` 三個 `&&`：
- `audio` 為 `(typeof useAudioPlayer === 'function') ? useAudioPlayer() : null`（`src/TranscriptPage.jsx:27`）
- `episode` 由 prop 傳入，TranscriptPage 渲染時已存在
- `episode.audio_url` API 已驗有值

實際 button 不 render 的可能 cause（implementation 階段先 instrument 確認）：
1. `audio` hook context 在初次 render timing 上 `undefined`（Provider 尚未掛載完成）
2. button 確實 render 但被 top bar `flexWrap: 'wrap'` 折到第二行 + 行高被裁
3. icon `play` 沒 register 在 `Icon` component → button 完全不 render（unlikely，Btn 應 graceful）

修法：
- 移除 `audio &&` 這個 guard — 改成 button **無條件 render**，內部 onClick handler 自己 fallback：若 `audio == null` 時 noop + console.warn（保證 button 視覺存在，使用者點才知狀態）
- onClick 仍維持「audio 為 null 就不做事」的 safe behavior，不會跳錯
- Implementation 階段在 `onClick` 進入時 log 一次 `[audio?, episode?, audio_url?]`，prod smoke 點按鈕後從 console 撈 evidence 確認 root cause

如果 root cause 是 timing race（hook 在 first render 拿到 undefined），副作用是 button 第一個 frame 就 render 但點不到 — 加 `disabled={!audio}` 視覺示意 + tooltip「載入中…」即可。

### D3 — B3 deep-link scroll 依賴 B1 修好的 paragraph anchor

既有 scroll-to-segment 邏輯在 `src/TranscriptPage.jsx:68-99`（`deepLinkSecondsRef`、最接近 segment、±5 秒 window）— 邏輯本身 OK。B1 修完 paragraph 切多段後，scroll target 自然有對齊點。

Implementation 階段 B1 修完先驗一次 `?t=3677.06` 是否自動跳對；若仍失敗才另開 task 加 paragraph-level scroll 對齊（依目前 deep-link logic 已對 segment 對齊，paragraph 是 segment 的 wrapper，理論上跟著走）。

### D4 — stripHtml plain-text sanitizer

新增 `src/utils/stripHtml.js` 一支 pure function：
- input: 任意字串（可能含 HTML tag、entity）
- transform: `<br>` `<br/>` `<br />`（不分大小寫）→ `\n`；其他 `<...>` tag 整段移除；HTML entity（`&amp; &lt; &gt; &quot; &#39; &nbsp;` 等常見 entity）decode 回字元
- output: plain text
- export 走 `window.stripHtml = stripHtml` + `module.exports = stripHtml` 兩種（跟 `aggregateParagraphs.js` 同樣 pattern，索引在 `index.html` 一支 `<script>` tag）

選擇 implement 一個小 util 而非引第三方 lib（DOMPurify 等）— 本 change 唯一用途是 description 顯示，沒 XSS 風險（已 strip tag），lib size 不划算。

ShowCard 內 description render 改用 `{stripHtml(show.description)}`（一行替換）。

### D5 — Test fixture：無 speaker + gap=0 input

新增 `src/utils/aggregateParagraphs.test.js`（Node smoke test，跟現有 `module.exports` 介面對齊）：
- Fixture A：5 segment、全 `speaker: null`、`end == start` 連續、總長 60 秒、第 3 段尾為「。」→ 預期 ≥ 2 paragraph
- Fixture B：3 segment、有 speaker change → 走既有 (b) 路徑、預期 3 paragraph
- Fixture C：30 segment、總長 200 秒、無 speaker、無 gap、無句尾標點 → (c) hard ceiling 預期 ≥ 4 paragraph（200/45 = 4.4）
- Fixture D：empty / null input → []

Test runner 用 `node src/utils/aggregateParagraphs.test.js` 直接跑（require + assert，不引 jest，跟現有專案無打包工具一致）。

### D6 — 驗證 SOP（chrome-devtools-mcp prod smoke）

Apply 完 ship 到 prod 後跑：

1. 開 `https://app.podcastrag.app/` → 看 ShowCard description 不含 raw `<p>` `<br />` 字串（B4 ✓）
2. 點 ShowCard → 進 QueryPage → 語意 tab → 搜任意 query → 點「跳到這段內容」附 `?t=N` 進 TranscriptPage
3. 右側 transcript scroller 數 paragraph block ≥ 20（B1 ✓）；timestamp 多於 1 個（用 `[...document.querySelectorAll('*')].filter(el => /^\d{2}:\d{2}$/.test(el.textContent?.trim()))` evaluate）
4. 畫面自動 scroll 到 `?t=N` 對應段並 highlight 或對齊 viewport（B3 ✓）
5. Top bar「從此處播放」button 可見（B2 ✓）；點按啟動播放，下方浮出 StickyAudioBar；切回 QueryPage 音訊不斷
6. Evidence 寫進 `docs/case-studies/landing-redesign-hotfix-2026-05-24.md`（per `feedback_case_studies_no_commit.md` 不進 git）

## Implementation Contract

**Behavior**：

- TranscriptPage 開啟任一集逐字稿：右側內容區渲染 **多個 paragraph block**，每段帶獨立 timestamp（hh:mm 或 mm:ss）。80 分鐘 podcast 預期 ≥ 20 段（典型 30-100 段間）。
- TranscriptPage top bar 永遠看得到「從此處播放」（中文）/「Play here」（英文）button — 只要 `episode.audio_url` 非空字串。Disabled 狀態用 visual hint（譬如灰階）+ `disabled={!audio}` 屬性。
- 點 button 後 `<audio>` 元素開始播放，畫面下方浮出 StickyAudioBar 顯示 currentTime、speed、pause 按鈕。
- 進入 TranscriptPage 時 URL 含 `?t=<seconds>`：頁面 scroll 到 segment.start_time 最接近 `t` 的 paragraph，若 |closest - t| ≤ 5 秒則 highlight 該段（沿用 R2.1 規則）。
- HomePage 收錄節目區的 ShowCard 顯示 description 時，沒有任何 `<` 或 `>` 字元、沒有 `&amp;` 等 entity 字串外漏；`<br />` 改成換行排版。

**Interface / data shape**：

```
// aggregateParagraphs(segments, opts) signature
opts = {
  gap_threshold_seconds?: number,    // default 1.5
  max_paragraph_seconds?: number,    // default 45  ← new
  min_paragraph_seconds?: number,    // default 15  ← new
}

// Output 維持既有 shape，不變：
{ paragraph_text: string, start_time: number, end_time: number,
  speaker: string|null, segment_ids: string[] }
```

```
// stripHtml(input) signature
stripHtml(input: string | null | undefined) => string
// null/undefined → '' ；保證不丟例外
```

```
// TranscriptPage 「從此處播放」 button
// 既有 (TranscriptPage.jsx:135)：
{audio && episode && episode.audio_url && <Btn ...>...</Btn>}
// 改為（移除 audio guard、加 disabled）：
{episode && episode.audio_url && (
  <Btn ... disabled={!audio} onClick={() => audio && audio.playFromTime(...)}>...</Btn>
)}
```

**Failure modes**：

- `aggregateParagraphs` 拿到 empty / null input：回 `[]`（既有行為，不變）
- `aggregateParagraphs` 拿到 segment 缺 `end_time`：fallback 用 `start_time`（既有行為，不變）
- `stripHtml` 拿到 null / undefined：回 `''`，不丟例外
- 「從此處播放」button 在 `audio` 為 null 時：button 仍 render 但 `disabled`，onClick 是 noop
- `?t=N` 找不到接近 segment（empty transcript）：scroll 至頂、不 highlight、不報錯（既有 R2.1 行為）

**Acceptance criteria**：

- `node src/utils/aggregateParagraphs.test.js` 通過所有 fixture（A/B/C/D 四個 assert 全 pass）
- prod chrome-devtools-mcp smoke 通過 D6 列的 6 個步驟（截圖 / DOM count evidence 附 case-study）
- TranscriptPage `?show_id=88702ed8-6fa0-49ec-bae4-34ac7c6d631c&episode_id=6bd0dbce-ad91-4264-bb55-025f527703e1&t=3677.06`：右側 paragraph block ≥ 20、scroll target 對齊 ±5 秒 window
- HomePage 三 ShowCard 都看不到 `<`、`>`、`&` 開頭的 raw 字串

**Scope boundaries**：

- **In scope**：`src/utils/aggregateParagraphs.js`、`src/utils/stripHtml.js`(new)、`src/TranscriptPage.jsx`、`src/HomePage.jsx`、ShowCard 內 description render 處（即便 ShowCard 真實檔位置仍待 implementation 階段確認 — 不論在哪個檔，touch point 限縮到 description 那一行）、`src/utils/aggregateParagraphs.test.js`(new)、`index.html`（加 stripHtml.js script tag）。
- **Out of scope**：backend 任何檔、`StickyAudioPlayer.jsx` 內部邏輯、ASR / diarization pipeline、其他 page（QueryPage / AdminPage / TranscriptPage 以外）、單元測試 framework 引入、CSS variable / TOKEN 調整、i18n 字串新增（既有 `從此處播放 / Play here` 不變）。

## Risks / Trade-offs

- **R1 — paragraph 切太細風險**：D1 預設 45 秒上限可能在某些慢速說話的集數切過細。緩解：先用預設值 ship，prod 上實測 3 集（曼報 / 壹加壹電台 / 這又沒有很屌）後看視覺效果，必要時 follow-up tune（不阻塞本 change archive）。
- **R2 — 移除 `audio &&` guard 後 audio context 真的是 null 的情況**：button 會 render 但點不到。Disabled state 至少視覺正確；root cause（context 為何 null）真要查得在 implementation 階段補 log 釐清。最壞情況用 disabled state 暫時 ship 並 follow-up 補修，不阻塞 hotfix。
- **R3 — stripHtml 不是 XSS-safe sanitizer**：本 util 設計目的純為「視覺乾淨」，不對抗 malicious payload。description 來源是 RSS feed 第三方資料 — 雖然顯示用，但若未來想 render 為 HTML（譬如保留 `<a>` 連結點擊）需另外引 DOMPurify。本 change 明確 plain-text only，標註在 util 註解。
- **R4 — Test 沒 framework**：`aggregateParagraphs.test.js` 用 node + assert 寫，無 watch mode / coverage report。本 change 認可此 trade-off（專案無打包工具，引 jest 不划算），test 跑法寫在註解第一行讓未來 contributor 知道。
- **R5 — `eval` 跟 `admin-quota-bypass-fix` 排序衝突**：本 hotfix 跟 eval / quota-bypass 各自獨立。本 change archive 後再 propose `admin-quota-bypass-fix`，然後重跑 token-truncate eval。**無依賴關係**，唯一風險是「先後排錯讓人覺得 eval 怎麼還沒跑」— release log 補一行說明 eval 等 quota-bypass 後再跑。
