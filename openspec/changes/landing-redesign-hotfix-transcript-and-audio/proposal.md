## Why

landing-and-mode-orchestration-redesign（2026-05-23 archive）重構後 prod smoke 抓到 4 個 visual regression，其中兩個直接讓核心功能廢掉：

- **B1（高）**：TranscriptPage 右側逐字稿整集只渲染 **1 個 `00:00` paragraph block**，整集 80 分鐘文字黏成一大塊牆。左側 timeline 用 sample-by-index 切 40 段所以正常。
- **B2（高）**：TranscriptPage top bar「從此處播放」按鈕沒 render（DOM 不存在），導致 `StickyAudioBar` 永遠不浮、整個站沒有音訊播放入口。
- **B3（中）**：TranscriptPage `?t=<sec>` URL param scroll-to-timestamp 行為失效（右側 scroller scrollTop 跳到接近底部而不是 t 對應位置）。推測跟 B1 同根 — 沒 paragraph anchor 可以對齊。
- **B4（中）**：HomePage 收錄節目區的 ShowCard description 直接把 RSS feed 原始 HTML（`<p>`、`<br />`、`<a>`）以字串形式顯示出來，沒 strip 或 sanitize。

B1 已驗的 root cause：ASR 給的 Whisper word-level segments `speaker` 全為 `null`、`start_time(next) == end_time(prev)`（gap 全 0），導致 `src/utils/aggregateParagraphs.js` 的兩個切段條件（gap ≥ 1.5s OR speaker change）**永不成立**，整集合成一段。原邏輯只應對「有 speaker label」或「有真實 silence gap」的 ASR 輸出，跟現網 Whisper 輸出形態不匹配。

B2 root cause：button 條件 `{audio && episode && episode.audio_url && ...}` 不成立。API 已驗回 `audio_url`，hook 拿到的 audio context 也應該非 null（AudioPlayerProvider 正確 mount 在 App.jsx），需 design 階段 trace 是哪個條件 short-circuit。

修這個 hotfix 前對話 / 語意 / 索引模式都堪用，但**整個站沒有任何方式播放音訊**，逐字稿閱讀體驗也降回「整段不可讀」。優先級高於下一輪 eval 與 admin-quota-bypass-fix。

## What Changes

- **`src/utils/aggregateParagraphs.js`**：擴充切段條件，使「無 speaker、無 silence gap」的 ASR 輸出也能合理切段。新增 fallback 觸發條件（任一成立即切新段）：
  - (a) 既有：gap ≥ `gap_threshold_seconds`（保留）
  - (b) 既有：speaker change（保留）
  - (c) 新增：cumulative paragraph duration ≥ `max_paragraph_seconds`（預設 45 秒）
  - (d) 新增：當前文字尾端落在句末標點（`。！？!?`）且 cumulative duration ≥ `min_paragraph_seconds`（預設 15 秒）
- **TranscriptPage 「從此處播放」入口修復**：找出 `{audio && episode && episode.audio_url}` 為何不成立並修；若 root cause 是 timing race（audio context 還沒 ready），改成 deferred render 或加 loading state；確保 button DOM 一定 render（episode.audio_url 已有則 button 必出現）。
- **TranscriptPage `?t=N` deep-link scroll**：B1 修完後，paragraph anchor 重新建立，再驗一次 scroll-to-timestamp 是否自動修復；若仍失效則修 scroll target 計算。
- **ShowCard description HTML 處理**：description 在 render 前用 plain-text sanitizer（strip tags、`<br>` → `\n`、HTML entity decode），避免 raw 標籤外漏。

## Non-Goals

- **不**重新設計 paragraph 切段視覺風格（沿用現行 paragraph block 樣式）。
- **不**動 backend transcript API shape（segment 欄位維持 `start_time / end_time / speaker / text`，不要求 backend 補 paragraph break hint）。
- **不**改 ShowCard 整體版型（只改 description plain-text 顯示）。
- **不**回填 ASR 既有資料加 speaker label（離線重跑 diarization 不在本 scope）。
- **不**改 audio player core 行為（StickyAudioBar 本身正常，本 change 只負責「能進入播放狀態」）。
- **不**併 admin-quota-bypass-fix 或其他 follow-up — 本 change 純 visual / UX regression 修復。

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `paragraph-aggregation`: 切段條件擴充為四條（gap、speaker change、cumulative duration、句末標點 + min duration），保證無 speaker 標籤的 Whisper word-level 輸出仍能合理切段。
- `sticky-audio-player`: 強化 TranscriptPage 「從此處播放」入口的 render 保證 — 只要 `episode.audio_url` 存在，button 一定 render 並能成功觸發播放，不被 audio context timing race 等情境 short-circuit。
- `home-page`: ShowCard description 必須以 plain-text 形式顯示，HTML 標籤一律 strip 或轉換（`<br>` → 換行、tag 移除、HTML entity decode）。

## Impact

- Affected specs: paragraph-aggregation, sticky-audio-player, home-page
- Affected code:
  - Modified:
    - src/utils/aggregateParagraphs.js
    - src/TranscriptPage.jsx
    - src/HomePage.jsx
  - New:
    - src/utils/stripHtml.js（plain-text sanitizer 工具）
    - src/utils/aggregateParagraphs.test.js（fixture：無 speaker + gap=0 input → 多段輸出）
  - Removed:
    - (none)
