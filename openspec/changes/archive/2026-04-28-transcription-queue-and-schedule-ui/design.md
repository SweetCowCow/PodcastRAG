## Context

兩個後端 change archive 後留下的 admin UI 工作：當前 `AdminPage.jsx` 5 個 tab（API/LLM/RAG/Schedule/ExternalAPI）沒有 queue rows 列表、無 force-cancel 按鈕、無 max_concurrent input；排程 modal 缺 `max_episodes_per_run` 欄位、缺 `last_refresh_*` 顯示、刪 show 沒 cascade-aware confirm。

技術約束：
- 前端用 React 18 via CDN + Babel Standalone（無 build pipeline，純瀏覽器 JSX）— 不能引入 npm 套件如 dnd-kit / react-dnd
- 樣式全部 inline style，token 在 `src/Shared.jsx` 的 `TOKEN`
- 雙語（zh / en）by `lang === 'zh'`
- 現有 polling pattern 在 ScheduleTab：useEffect 內 setInterval 5000ms

## Goals / Non-Goals

**Goals**
- 提供完整 admin queue 操作面（觀察 + 取消 + 強制取消 + 忽略 + 重試 + 拖動排序）
- 即時調整並行上限（debounce 500ms 後 PUT settings）
- 刪 show 顯示 cascade 影響數
- 排程 modal 補完欄位顯示
- 不破壞現行 admin tab 框架與雙語切換

**Non-Goals**
- 不引入第三方套件（保持 CDN 部署）
- 不重設計現有 ScheduleTab 整體（僅補欄位 + confirm）
- 不做拖動跨 status 區、不做 bulk 操作、不做 search / filter
- 不改 polling 為 WS / SSE

## Decisions

### 拖動排序：手刻 HTML5 native draggable + onDragOver / onDrop

選擇：用 React 原生支援的 `draggable` / `onDragStart` / `onDragOver` / `onDrop` props，不引入函式庫。

**為什麼不用 mouseEvent 手刻**：HTML5 drag-and-drop 原生 API 已支援拖移視覺回饋（瀏覽器自動畫拖影），減少自實作工作量；對 PC 使用情境足夠（admin tab，不需 mobile touch 支援）。

**為什麼不用 dnd-kit / react-dnd**：CDN-only React 環境引入 ESM module 不便（需 import map 或自行 wrap）；admin queue 拖動是低頻操作，不需要套件提供的鍵盤 a11y / 動畫。

**前端流程**：
1. `pending` row 設 `draggable={true}`，拖開時 `onDragStart` 把 row id 存 `dataTransfer`
2. 每個 pending row 設 `onDragOver={e => e.preventDefault()}` 接受 drop
3. `onDrop` 取出 source row id 與 target row id（drop target），計算 target row 的 position 給後端
4. 樂觀 UI：直接重排前端陣列；同時呼叫 `PATCH /admin/queue/{source}/position` body `{"position": <target.position>}`
5. 失敗（4xx / 5xx）revert 前端陣列回原順序，顯示 toast 錯誤

### 後端 position recompute：先位移再賦值

新 endpoint `PATCH /admin/queue/{id}/position` body `{"position": int}`：

1. 從 DB 讀 row（必須 status=pending，否則 409）
2. 新 position = clamp 到 `[min(pending.position), max(pending.position)]`（避免越界）
3. 在一個 SQL transaction 內：
   - 若 new_pos < old_pos（往前移）：把 `[new_pos, old_pos)` 區間內所有 pending rows 的 position +1
   - 若 new_pos > old_pos（往後移）：把 `(old_pos, new_pos]` 區間內所有 pending rows 的 position -1
   - 把 target row 的 position 設為 new_pos
4. commit + 回 `QueueRowOut`

**為什麼不用 fractional / sparse position**：當前 dispatcher 與 spec 已假設 position 是 monotonic int，改 sparse 動模型 + dispatcher 邏輯。位移成本低（通常 < 50 pending rows），單 transaction 可承受。

**為什麼不用拖動 between two rows 的「插入點」概念**：API design 簡化為「target row 的 absolute position」；前端負責計算（drop 在哪個 row 上 → 取那個 row 的 position）。

### 5s polling 而非 WS

沿用現有 ScheduleTab pattern。轉錄序列頁打開時 5s 抓一次 `GET /admin/queue` + `GET /admin/settings`，離開 tab 清 interval。**為什麼不 WS**：admin 頁面同時訪問人少，5s 延遲可接受，WS 部署層成本（Zeabur sticky session、心跳、reconnect）不值得。

### Max concurrent input：debounce 500ms

數字輸入框 onChange 直接更新 local state（即時顯示），同時 debounce 500ms 後呼叫 `PUT /admin/settings` body `{"max_concurrent_transcriptions": value}`。Helper text 在 value > 3 時顯示警告色。後端已限 1–3，超過會 422 — UI 顯示後端錯誤訊息。

**為什麼不用 save 按鈕**：admin 設定的 API 設計就是即時生效（60s TTL cache），加按鈕反而多一步。

### 刪 show confirm：先抓 cascade 數

點「刪除節目」按鈕後：
1. UI disable 按鈕、show loading
2. 呼叫 `GET /admin/queue`，過濾 `show_id === target_show.id` 計算 `pending_count` + `running_count`
3. 顯示 confirm dialog：「確定要刪除『<show 名>』嗎？將同時取消 N 筆排隊中、M 筆執行中的轉錄任務。」
4. confirm 後呼叫 `DELETE /shows/{id}`，後端 cascade 已實作

**為什麼不在後端 endpoint 加 dry-run**：前端有 GET queue 資料即可算，不增加後端 API 表面。

### 排程 modal `max_episodes_per_run` 為必填數字（match 後端 schema）

後端 `ShowScheduleIn` 已要求 `max_episodes_per_run: int = Field(..., ge=1)`。modal 加數字輸入框，預設值 = current schedule value（編輯時）or 5（新建時，匹配後端 default）。

### `last_refresh_*` 顯示：色彩依 status

- `success` → 綠色 + ✓ icon + relative time（如「3 分鐘前刷新」）
- `failed` → 紅色 + ✗ icon + 訊息（hover 顯示完整 message）
- `pending` / null → 灰色「尚未刷新」
- 顯示位置：卡片 footer + modal 內專屬區塊

## Risks / Trade-offs

- **Drag reorder 樂觀 UI race**：使用者連續拖兩次，第一個 PATCH 還沒回，第二個就觸發 → 後端按收到順序處理，前端最後狀態以最後一次 PATCH response 為準。Mitigation: 拖動期間 disable 整個 pending list 接受新拖動 until response 回。
- **5s polling 在大量 cancelled/completed rows 時 payload 變大**：當前 `GET /admin/queue` 回所有 status 全列。短期可接受（我們流量小），長期需分頁。Mitigation: 文件記錄，等使用者抱怨慢再優化。
- **HTML5 drag API 在某些瀏覽器拖影視覺差**：Safari 對 drag image 控制不佳。Mitigation: PC Chrome / Firefox 為主要使用情境，admin 受眾小，可接受。
- **Position recompute 與 dispatcher 競態**：dispatcher 1s poll 取 `MIN(position) WHERE status=pending`，PATCH 改 position 時若同秒被 dispatcher 拿走 → 不影響正確性（dispatcher 會把 row 改 status=running，PATCH 看到 status≠pending 會 409）。
- **刪 show cascade 計數可能不即時**：`GET /admin/queue` 是 5s polling，使用者點刪除瞬間 cascade 數字可能略過時。Mitigation: 點刪除按鈕當下重抓 queue（不靠 polling 快取）。

## Migration Plan

1. 部署後端（含 PATCH position endpoint + schema CancelQueueRowOut 已存在）
2. 部署前端（含 QueueTab + ScheduleTab modifications）
3. 測試：開 admin 切到「轉錄序列」tab，enqueue 5 集，觀察列表 + 拖動 + force-cancel
4. 排程 tab：開 modal 確認 `max_episodes_per_run` + `last_refresh_*` 顯示

**Rollback**: PATCH position endpoint 可保留（unused 不影響）；前端可 revert commit。

## Open Questions

無未決事項。所有需求點已對齊（drag reorder = 做、schedule 增補 = 做、不引入第三方套件、polling 5s）。
