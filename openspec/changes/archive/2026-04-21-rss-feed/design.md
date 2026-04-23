## Context

`backend-api` change 已完成後端骨架，`shows`、`episodes` 資料表可用，但尚無方式匯入真實資料。本 change 讓管理者以 RSS URL 新增節目並同步集數，作為後續 Whisper 轉錄與 RAG 查詢的資料來源。

## Goals / Non-Goals

**Goals:**
- 解析標準 Podcast RSS 2.0 feed（支援 `itunes:` 延伸欄位取音訊時長、封面圖）
- 以 `episodes.guid` 做跨次同步去重，重複呼叫 sync 不會造成重複集數
- 所有 endpoints 以 async 實作，RSS HTTP 拉取不阻塞其他請求
- 對不合法 RSS URL（404、解析失敗、無 channel 節點）回傳 400 並給出清楚錯誤訊息

**Non-Goals:**
- 不做背景排程同步（之後由另一個 change 處理）
- 不處理 RSS 認證或 OPML 批次匯入
- 不做快取（每次 sync 直接重新拉 feed；未來如遇頻率限制再加）

## Decisions

### 使用 feedparser 解析 RSS

選擇 `feedparser` 套件作為 RSS 解析器。

- **為何 feedparser**：Python 生態系最成熟的 feed 解析工具，支援 RSS 2.0、Atom、及 `itunes:` 延伸欄位。對格式容錯度高，已處理大量邊緣案例。
- **替代方案**：`xml.etree` 自行解析 — 棄用，需自行處理各家 Podcast 發行平台的欄位差異。

### 使用 httpx 非阻塞下載 RSS

使用 `httpx.AsyncClient` 在 event loop 中下載 feed，再把 bytes 交給 `feedparser.parse()`（同步 CPU 操作，以 `asyncio.to_thread` 放到 thread pool）。

- **為何不直接用 feedparser 的 URL 輸入**：`feedparser` 內部使用同步 `urllib`，會阻塞 event loop。
- **為何放 to_thread**：parse 是 CPU-bound，放在主 loop 會卡住其他請求。

### 以 `guid` 作為集數去重鍵

`episodes` 表的 `(show_id, guid)` 複合唯一鍵已在 `db-schema` 定義。sync 時使用 upsert 策略：
- RSS 裡每筆 item 查 `(show_id, guid)` → 存在則 `UPDATE`，不存在則 `INSERT`
- 若 RSS item 缺 `guid`，fallback 用 `enclosure.url` 當 guid（feedparser 會自動正規化）

### POST /shows 同步執行 RSS 解析

新增節目時同步解析 RSS、寫入 `shows` 表、並一併同步集數，全部在同一個 request 裡完成（可能耗時數秒）。

- **為何同步而非背景**：MVP 階段避免引入背景任務框架（Celery、ARQ）增加複雜度；同步回傳讓前端立即看到集數清單。
- **權衡**：若 feed 有上千集，request 可能超過 30 秒。→ 緩解：解析時只取 RSS 最新的 N 集（預設 200），後續 `POST /sync` 可逐步同步更多歷史集數。
- **未來升級路徑**：若需處理大型 feed，改為 202 Accepted + 背景任務。

## Risks / Trade-offs

- **RSS 解析阻塞 request**：大型 feed（>500 集）同步時間可能長。→ 緩解：首次匯入限制 200 集，並加上 30 秒 HTTP timeout。
- **guid 不穩定**：少數 Podcast 發行平台會在集數小幅修改後產生新 guid。→ 緩解：暫不處理，出現再補 `audio_url` fallback。
- **HTML entities / 特殊字元**：某些 feed 描述會含原始 HTML。→ 緩解：`description` 欄位原樣儲存（`Text`），前端顯示時再做 sanitize。
