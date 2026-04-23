## 1. 相依套件與 Pydantic schemas

- [x] 1.1 在 `backend/requirements.txt` 加入 `feedparser` 和 `httpx`，重建 Docker image（配合「使用 feedparser 解析 RSS」與「使用 httpx 非阻塞下載 RSS」決策）
- [x] 1.2 建立 `backend/app/schemas/__init__.py` 與 `backend/app/schemas/show.py`：定義 `ShowCreate`（`rss_url`）、`ShowResponse`（含 `episode_count`）、`ShowListItem` 等 Pydantic models
- [x] 1.3 建立 `backend/app/schemas/episode.py`：定義 `EpisodeResponse`（id、title、audio_url、duration_seconds、published_at、guid 等欄位）
- [x] 1.4 建立 `backend/app/schemas/sync.py`：定義 `SyncResponse`（`added`、`updated`、`total` 三個整數欄位）

## 2. RSS feed parser 實作

- [x] 2.1 建立 RSS feed parser：`backend/app/services/__init__.py` 與 `backend/app/services/rss_parser.py`：實作 `async def fetch_and_parse(url: str) -> ParsedFeed` 使用 httpx 非同步下載、`asyncio.to_thread` 包 `feedparser.parse`
- [x] 2.2 在 rss_parser.py 定義 `ParsedShow` 與 `ParsedEpisode` dataclass，並實作把 feedparser 結果對應到 dataclass 的轉換邏輯（處理 iTunes 欄位 fallback、`published_parsed` 時間轉 datetime、`itunes:duration` 字串轉秒數）
- [x] 2.3 在 rss_parser.py 定義 `RssParseError` 例外類別，並在 HTTP 404、非 XML 內容、無 channel 節點等情況拋出帶有描述訊息的例外

## 3. 節目管理 Endpoints（Create / List / Get / Delete show）

- [x] 3.1 建立 `backend/app/api/shows.py`：掛載 `APIRouter(prefix="/shows")`，並在 `backend/app/main.py` 加入此 router
- [x] 3.2 實作 `POST /shows`（Create show endpoint）：呼叫 parser，限制首次匯入最多 200 集（配合「POST /shows 同步執行 RSS 解析」決策），寫入 shows 表並 bulk insert episodes；重複 rss_url 回 409、parser 失敗回 400
- [x] 3.3 實作 `GET /shows`（List shows endpoint）：查詢 shows 表以 created_at DESC，join 計算 episode_count
- [x] 3.4 實作 `GET /shows/{show_id}`（Get show by id endpoint）：查詢單一節目，找不到回 404
- [x] 3.5 實作 `DELETE /shows/{show_id}`（Delete show endpoint）：cascade 刪除節目（episodes/transcripts 由 FK ondelete=CASCADE 自動處理）

## 4. 集數同步與列表 Endpoints

- [x] 4.1 實作 `POST /shows/{show_id}/sync`（Sync show episodes endpoint）：重新呼叫 parser，以 `(show_id, guid)` 做 upsert（使用「以 `guid` 作為集數去重鍵」策略），回傳 `{added, updated, total}` 統計
- [x] 4.2 建立 `backend/app/api/episodes.py`：實作 `GET /shows/{show_id}/episodes`（List episodes endpoint），支援 `limit`（預設 50，上限 200）與 `offset`（預設 0）query params，依 published_at DESC 排序
- [x] 4.3 在 `backend/app/main.py` 掛載 episodes router

## 5. 本地驗證

- [x] 5.1 使用 `docker compose up -d --build` 重建並啟動後端，以真實 Podcast RSS（例如 https://feeds.simplecast.com/54nAGcIl）呼叫 `POST /shows`，驗證 shows 與 episodes 皆寫入資料庫
- [x] 5.2 呼叫 `POST /shows/{show_id}/sync` 兩次，第二次 `added` 與 `updated` 皆為 0，驗證 idempotency
- [x] 5.3 呼叫 `GET /shows/{show_id}/episodes?limit=10`，驗證回傳 10 筆且按發佈時間排序
