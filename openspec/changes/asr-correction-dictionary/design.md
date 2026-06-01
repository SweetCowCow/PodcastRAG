## Context

PodcastRAG 逐字稿由 Whisper ASR 產生，固定誤聽專有名詞（滅火器→咪有企、世運→世韻、寰宇龍虎豹→寰宇龍虎報）。搜尋索引鏈為：`TranscriptSegment.text` →（`chunking.build_chunks` 串接）→ `transcript_chunks.text` + `embedding`/`embedding_v2` + `text_tsvector`。因此搜尋認的是 chunk 文字與向量，**只改顯示層不會讓搜尋生效**。`transcript_chunks` 有 `segment_ids` 陣列可由 segment 反查 chunk。既有 `tokenizer_custom_terms`（jieba 分詞詞庫）與 admin tab 是良好的實作範本，但用途正交（分詞 vs 替換）。embedding 走真實 OpenAI（AI Hub 不支援 embedding endpoint）。轉錄寫入在 `backend/app/workers/tasks.py` 的 `transcribe_episode` → `_run`；新增 admin tab 的慣例為「獨立 jsx 元件 + `index.html` 掛 script + `AdminPage.jsx` pages 物件 + `Shared.jsx` 後台 nav 入口」。

## Goals / Non-Goals

**Goals:**

- 提供 deterministic、可控、人工維護的錯字校正字典
- 修正一路打通到搜尋索引（chunk 文字 + 雙 embedding + tsvector），使搜正字命中
- 新轉錄自動套用、既有逐字稿可批次回填
- 成為 EQ2b（LLM 同音異義字後處理）的安全網與評估基準

**Non-Goals:**

- LLM／模糊／同音比對（屬 EQ2b）
- regex／萬用字元規則
- 自動偵測錯字（本 change 規則一律人工維護）
- episode-level scope（初版只有 global 與 show 兩級）
- 顯示層即時替換（一律源頭修正）
- 全量重 chunk／重 embedding（只重算受影響 chunk）

## Decisions

### 校正在 chunking 前於源頭一次套用

校正在 transcribe worker 拿到 Whisper 結果後、寫入 segment 與切塊之前套用，直接修正 `TranscriptSegment.text` 與 `transcript.content`。如此顯示與搜尋索引一次到位皆為正字。替代方案：顯示層即時替換（搜尋不生效，否決）；只改 `transcript.content`（chunk 來源是 segment 不是 content，否決）。

### 整詞精確 literal 比對與誤傷防護

比對為 `wrong` 完整字串的 literal substring 比對（Python 字串比對），不啟用 regex／萬用字元。中文無空格邊界，純 substring 對短詞有誤傷風險（例：短詞「世運」可能命中「創世運動」），靠三道防線控制：(1) admin UI 在儲存前顯示「目前命中 N 段」預覽；(2) 預設 show-scoped 縮小範圍；(3) 建議 `wrong` 使用夠長夠特殊的詞。替代方案：regex（誤傷高、難驗證、違背 deterministic，否決）；中文 word-boundary（中文無 word boundary，不適用）。

### 適用範圍 global 與 show-scoped 的 union 載入

每條規則帶 `scope`（`global` 或 `show`）；`scope=show` 時 `show_id` 必填。套用某節目時載入規則集 = 所有 `enabled` 的 global 規則 ∪ 該節目 `enabled` 的 show 規則。預設 show-scoped 防跨節目專有名詞（人名、團名）誤傷；通用錯字手動升 global。替代方案：全 global（人名誤傷，否決）；episode-level（過細、字典爆炸，未來再加，否決）。

### 批次回填只重算受影響的 chunk

回填流程（per transcript）：載入規則集 → 找出 `text` 含任一 `wrong` 的 segment 並更新 `segment.text` → **以更新後的 segments 重跑 `build_chunks`，逐 `chunk_index` 比對新舊 `text`，text 有變的即為受影響 chunk** → 對受影響 chunk 更新 `text`、重算 `embedding`/`embedding_v2`、用 tokenizer 重建 `text_tsvector`。

**為何用「重跑 build_chunks + text 差異」而非單純 segment_ids 反查**：`chunking._build` 的 chunk `text` 含前後各一個 overlap segment，但 `transcript_chunks.segment_ids` 只記 middle 段。因此改一個 segment 會同時影響「middle 含它的 chunk」與「把它當 overlap 的鄰接 chunk」；只用 `segment_ids` 反查會漏掉 overlap 鄰居。重跑 `build_chunks` 後比對 text 差異能精準涵蓋所有真正變動的 chunk，且與轉錄路徑共用同一套切塊邏輯（DRY、行為一致）。build_chunks 的邊界由時間/段數決定、與 text 內容無關，故 chunk 數與 `chunk_index` 對齊不變。

只重算受影響 chunk，成本 = 受影響 chunk 數 × embedding 單價。替代方案：全量重 chunk＋embed（成本爆且無必要，否決）；只改 segment 不動 chunk（搜尋不生效、違背「修到底」，否決）；單純 `segment_ids` 反查（漏 overlap 鄰接 chunk，否決）。

### 批次回填用可續跑的 Celery 背景任務

批次回填為長跑工作，不可用同步 endpoint（會 timeout，且容器為 ephemeral 隨時可能重啟）。設計為 Celery task：以 episode／chunk 分批 commit、進度落 DB 可查；重跑同一 chunk 結果一致（idempotent），容器重啟可從未處理 chunk 續跑。admin endpoint 只負責 enqueue 並回 task 識別。替代方案：同步 endpoint（timeout + 不可續，否決）；一次性 script（admin 無法操作、不可重複，否決）。

### 獨立 asr_correction_terms 表與 tokenizer 字典區隔

新增獨立表 `asr_correction_terms`，不與 `tokenizer_custom_terms` 共用。兩者語意正交：tokenizer 是 jieba 分詞（避免拆字），asr_correction 是錯字替換；套用時機、reload 機制、資料形狀皆不同。獨立表 + 獨立 service + 獨立 admin tab。替代方案：共用 tokenizer 表加 type 欄位（語意混淆、套用時機不同，否決）。

### 新轉錄鏈式套用點與 fail-open

`_run` 在取得 Whisper result 後，載入該 episode 所屬 show 的規則集，對每個 `seg.text` 與 `result.text` 套校正，再寫 `TranscriptSegment` 與 `transcript.content`，再 `build_chunks`。校正規則載入或套用失敗採 fail-open（記 log warning、不擋轉錄）——轉錄本身的價值高於校正，且校正可事後批次回填補救。

## Implementation Contract

**Behavior（操作者可觀察）：**

- admin 新增規則「咪有企→滅火器」綁定某節目並啟用後：該節目之後新轉錄的逐字稿顯示「滅火器」，且搜尋「滅火器」可命中該段
- admin 對該節目觸發批次回填後：該節目既有逐字稿的「咪有企」改為「滅火器」，受影響 chunk 的 `text`/`embedding`/`text_tsvector` 已更新，搜尋「滅火器」命中既有內容
- `global` 規則套用所有節目；`show` 規則只套用其綁定節目；`enabled=false` 規則不套用

**Interface / data shape：**

- 表 `asr_correction_terms`：`id` (uuid pk)、`wrong` (text)、`correct` (text)、`scope` (text, 'global'|'show')、`show_id` (uuid, nullable)、`enabled` (bool, default true)、`note` (text, nullable)、`created_by_user_id` (uuid, nullable)、`created_at`、`updated_at`；唯一約束 `(wrong, scope, show_id)`
- service（`backend/app/services/asr_correction.py`）：`load_rules(session, show_id) -> list[Rule]`（回 global ∪ 該 show 的 enabled 規則）、`apply_corrections(text: str, rules: list[Rule]) -> str`（整詞 literal 替換）
- admin API（`/admin/asr-corrections`）：`GET`（列表）、`POST`（新增）、`PATCH /{id}`（更新含啟用停用）、`DELETE /{id}`、`POST /admin/asr-corrections/backfill`（body 可帶 `scope`/`show_id`/`term_id` 範圍 + `dry_run` 旗標；`dry_run=true` 只回報「將重算 N 個 chunk + 預估成本」不執行，`dry_run=false` 才 enqueue 背景任務並回任務識別）
- 批次回填任務回報：受影響 segment 數、受影響 chunk 數、成功／失敗 chunk 清單

**Failure modes：**

- 新轉錄套校正失敗 → fail-open（log warning，不擋轉錄）
- 批次回填單一 chunk embedding 失敗 → 記錄並跳過該 chunk，不中斷整批，結束時回報失敗清單
- `scope=show` 但 `show_id` 缺 → API 回 422

**Acceptance criteria：**

- unit：`apply_corrections` 整詞替換正確、global+show union 正確、停用規則不套、短詞誤傷案例行為符合定義
- integration（真實 Postgres）：對一個 episode 批次回填後，受影響 chunk 的 `text`/`text_tsvector` 更新、未受影響 chunk 不變
- prod smoke：新增一條已知錯字規則 → 批次回填一個 show → 搜尋正字命中既有內容

**Scope boundaries：**

- In scope：規則表 + migration、CRUD admin API、admin tab、新轉錄鏈式 hook、批次回填 Celery 任務與受影響 chunk 重算
- Out of scope：LLM／模糊比對（EQ2b）、regex、自動偵測錯字、episode-level scope、顯示層即時替換、全量重 embed

## Risks / Trade-offs

- [短 `wrong` 字串的子字串誤傷] → admin UI 儲存前顯示命中數預覽 + 預設 show-scoped + 建議用夠長的詞
- [批次回填的 embedding 成本] → 只重算受影響 chunk；回填前回報「將重算 N 個 chunk」供 admin 判斷（精確金額估算細節留 apply）
- [批次回填中途容器重啟] → 分批 commit + idempotent + 可續跑
- [規則改動後既有逐字稿不自動同步] → 批次回填為手動觸發；admin UI 提示「新增規則後需手動回填既有逐字稿」
- [fail-open 使校正可能靜默失效] → 記 log 可觀測；轉錄優先、可事後回填補救

## Migration Plan

- alembic migration 建 `asr_correction_terms` 表（revision id 實作時依專案 12-char 慣例生成）
- 部署順序：migration 建表 → backend/worker/dispatcher/beat 四服務部署（新轉錄 hook + 批次回填任務）→ 前端
- rollback：新增表無破壞性；新轉錄 hook fail-open；停用所有規則即讓校正成 no-op；批次回填為 opt-in 不自動跑

## Open Questions

> 2026-06-01 由 Jacky 拍板定案：

- ✅ 批次回填**先 dry-run**：先回報「將重算 N 個 chunk + 預估成本」並等 admin 確認，確認後才真正執行（見 Implementation Contract 的 backfill API 的 `dry_run` 旗標）。
- ✅ 一條規則**初版綁單一節目**（單一 `show_id`）；多節目用多條規則或升 global。未來再評估 `show_id` 陣列。
