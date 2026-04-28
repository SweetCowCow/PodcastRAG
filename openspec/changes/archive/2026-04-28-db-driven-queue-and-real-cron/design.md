## Context

PodcastRAG 後端目前的轉錄流程：

```
使用者點「立刻轉錄」/「同步所有」
  → API 呼叫 dispatch.enqueue_transcription(episode_id)
  → celery_app.send_task("transcribe_episode", episode_id)
  → Celery broker (Redis) FIFO queue
  → worker pool（concurrency=1 in prod，=2 in local docker-compose）
  → transcribe_episode task 內部用 Redis 全域 slot + per-show lock 控並行
  → 寫 Transcript / TranscriptChunk / TranscriptSegment
```

問題：
1. **排程不會自動跑**：`show_schedules.frequency` / `run_time` 欄位無 cron 元件讀取
2. **Queue 不可觀測也不可操作**：Celery broker 內的 task 無法被使用者拖動排序、cancel、或標記「忽略」。task 一旦 send 出去，只能等它跑完或 worker 重啟
3. **並行控制只能改環境變數**：`max_concurrent_transcriptions` 是 `Settings` 類別欄位，要改值需要重 deploy

本 change 重做這層，讓 queue 由 DB 主導、排程由 Celery Beat tick 觸發、並行由 DB 表動態調整。完整需求脈絡見 `docs/case-studies/transcription-queue-discussion.md`。

## Goals / Non-Goals

### Goals

- 任何進入轉錄流程的 episode 都必須先有 `transcription_queue` row；無 row 就無轉錄
- Queue row 的 status 變化是唯一 source of truth，可被 API 讀寫
- 排程到時間自動跑：refresh + 入列一氣呵成
- 並行上限可在不重啟 worker 的情況下調整（讀 DB 設定，TTL ≤ 60 秒）
- 既有的 `transcribe_episode` task 邏輯（throttle / retry / Whisper 呼叫）幾乎不動，只在 entry 與 exit 加 queue row 同步

### Non-Goals

- **不做 UI**：所有 admin UI（轉錄序列頁、刪 show 確認視窗、設定面板新欄位）留給後續 change
- **不做 monthly cost cap 執行**：`monthly_cost_cap_usd` 欄位存在但本 change 不消費
- **不改 priority / round-robin 排序**：純 FIFO + 由未來 UI 拖動 `position` 數值
- **不處理 cron tick 漏跑補發**：部署期間錯過的 run_time 直接放棄、等下一次
- **不調整 Celery worker `--concurrency` 啟動參數**：worker pool 大小與 App 層 `max_concurrent_transcriptions` 解耦，後者透過 Redis slot 二次節流
- **不對 `task-queue` capability 做 spec 變動**：本 change 在其前面新增一層 dispatcher，但 task 內部執行模型不變

## Decisions

### Use Celery Beat for cron tick scheduling

選 Celery Beat 而非 Zeabur native cron job、external cron（GitHub Actions）、或自寫 daemon。

| 選項 | Pro | Con |
|---|---|---|
| **Celery Beat**（採用） | 跟既有 Celery 共用 broker / worker / monitoring；Python in-process schedule 可動態（雖然本 change 用靜態 1 分鐘 tick）；無新依賴 | 需要新增 beat container/process |
| Zeabur scheduled job | 不用維護 daemon | 最低粒度 1 分鐘 OK，但 cron tick 邏輯要寫成 standalone HTTP endpoint 被 cron 呼叫，多一層；環境耦合 Zeabur，本機 docker-compose 跑不了 |
| GitHub Actions cron | 完全 free | 需要 public webhook、安全性差、排程精度不保證 |
| 自寫 asyncio daemon | 完全控制 | 跟 Celery 重複造輪子；需要新管理 entrypoint |

決議：Beat 額外加 1 個 process，在 Zeabur 加一個 service、在 docker-compose 加一個 service，成本可控。

### Use a single 1-minute tick instead of per-schedule beat entries

Celery Beat 支援動態 schedule（`celerybeat-schedule` DB-backed）但需要 `django-celery-beat` 之類擴充。為了避免引新依賴：採用「1 分鐘固定 tick」+「tick 內部讀 `show_schedules` 表決定哪些要跑」。

實作上 `cron_tick` 是 Beat schedule 上唯一的條目：

```python
celery_app.conf.beat_schedule = {
    "cron-tick": {
        "task": "app.workers.cron_tick.cron_tick",
        "schedule": crontab(minute="*"),
    },
}
```

`cron_tick` task 內部負責決策「現在是不是某 show 的 run_time」。判斷邏輯：每分鐘執行時，比對 `(current UTC HH:MM)` 是否等於 `schedule.run_time`、且 `frequency=daily` 或（`frequency=weekly` 且當天為週一）。

trade-off：精度只到分鐘（OK）；漏跑（部署期間）不補發（OK，使用者下次排程仍會跑到）。

### Dispatcher: poll-based, not pubsub

Worker 從 DB pop 任務有兩種模式：
- **Poll**（採用）：worker 起一個 loop，每秒檢查 `transcription_queue` 是否有 pending row 且未達並行上限。
- **Pubsub**：用 Redis pub/sub 通知 worker「有新 row」，worker 醒來去 DB 讀。

採 Poll：
- 程式單純，沒額外 channel 要管
- 輪詢 1 秒 × 1 worker → DB load 可忽略
- 跨多 worker 仍然安全（DB 用 `SELECT ... FOR UPDATE SKIP LOCKED` 確保同一 row 不會被兩個 worker pop）

dispatcher 實作為一個常駐 Celery task（`app.workers.dispatcher.run_dispatcher`），由 Beat 每分鐘觸發一次（如果發現自己已在跑就退出）。或者更簡單：dispatcher 是獨立的 worker process（透過 entrypoint 啟動），跟轉錄 worker 分開。

決議：**dispatcher 是獨立 standalone process**（新 Dockerfile entrypoint flag），不走 Celery task 機制，避免「dispatcher task 自己卡在 queue 裡」的循環依賴。

### atomically pop queue row with SELECT ... FOR UPDATE SKIP LOCKED

從 `transcription_queue` 取下一個 pending row，必須避免兩個 dispatcher process race condition：

```sql
BEGIN;
SELECT * FROM transcription_queue
WHERE status='pending' AND ignored=false
ORDER BY position ASC
LIMIT 1
FOR UPDATE SKIP LOCKED;
-- if found:
UPDATE transcription_queue SET status='running', started_at=now WHERE id=?;
COMMIT;
```

PostgreSQL 原生支援 `FOR UPDATE SKIP LOCKED`。並行上限由 dispatcher 自己在 pop 之前查 `COUNT(*) WHERE status='running'` 強制。

### Position assignment uses MAX(position) + 1, not gaps

新 row 的 `position = (SELECT COALESCE(MAX(position), 0) FROM transcription_queue) + 1`。

trade-off：
- 簡單、UI 顯示順序穩定
- 拖動排序時要重編號（UI 把目標 row 的 position 設成 (前一筆 + 後一筆) / 2，整數會碰撞），需要週期性 renumber 或改用 fractional position（float / decimal）

決議：本 change 用 integer `position` + `MAX + 1` 入列。**拖動排序的 renumber 邏輯不在本 change**，留給 UI change（會在 UI change 增補一條 API：`POST /admin/queue/reorder` 接受新順序的 id 列表，後端整批重編號）。

### show 刪除時的 queue cleanup 順序

`DELETE /shows/{show_id}` 內部順序必須是：

1. `UPDATE transcription_queue SET status='cancelled' WHERE show_id=? AND status IN ('pending', 'running')`
2. `DELETE FROM shows WHERE id=?`（CASCADE 會把 episodes、transcripts、queue rows 全部 cascade delete）

`status='cancelled'` 的瞬間，正在跑的 `transcribe_episode` task 不會被中斷（OpenAI 已在算），但它在結束時會檢查自己 row 的 status，若已是 `cancelled` 就不寫 transcript / chunk。Whisper API 的錢已經花了，但避免把孤兒 transcript 寫進已刪 show 的歷史。

### Settings 表設計

`app_settings` 是 singleton（一行）。應用層強制：每次寫入用 `INSERT ... ON CONFLICT DO UPDATE` 或在 model 層擋第二筆。讀取用 60 秒 in-process cache（`functools.lru_cache + TTL` 或 `cachetools.TTLCache`），避免每個 dispatcher tick 都打 DB。

`max_concurrent_transcriptions` 範圍 1–3 在 Pydantic schema validate；DB 沒寫 CHECK constraint（避免 migration 太複雜，application-layer validate 已足夠）。

## Risks / Trade-offs

[Risk] **Cron tick 與既有手動觸發的 race condition**
→ Mitigation: 入列邏輯統一走 dispatcher 的 enqueue path（DB UNIQUE on `episode_id`），即使 cron 與手動同時試圖入列同一集，第二者會 conflict、改成 update 既有 row。

[Risk] **dispatcher process 掛掉，queue 停擺**
→ Mitigation: 跟 worker 一樣用 Zeabur 的 health check 自動重啟。dispatcher 邏輯 idempotent（pop 用 transaction、寫 status 用 UPDATE），重啟不會搞壞 queue。

[Risk] **Beat process 漏跑導致排程失準**
→ Mitigation: 漏跑就漏跑（design 已決定不補發），但 Beat 與 dispatcher 一樣靠 Zeabur health check 重啟。後續若需要補發，可以在 cron_tick 加一個「補跑窗口」邏輯（檢查上次 last_refresh_at 距今超過某閾值就強制跑），但本 change 不做。

[Risk] **dispatcher 輪詢造成 DB 壓力**
→ Mitigation: 1 秒 × 1 dispatcher process × 1 SELECT = 60 QPS，PostgreSQL 完全無感。若未來規模變大可改 NOTIFY/LISTEN。

[Risk] **既有透過 `dispatch.enqueue_transcription` 的所有呼叫點全部改流程，可能漏改**
→ Mitigation: 把 `enqueue_transcription` 函式簽名保留、實作改為「插 queue row」，所有舊呼叫點不用動程式碼即可走新流程。Tasks artifact 會列出 grep 確認所有呼叫點都通過。

[Risk] **既有 `max_episodes` 欄位移除影響舊資料**
→ Mitigation: Migration 把舊 `max_episodes` 值搬到新 `max_episodes_per_run`（`max_episodes = 0` 的特例直接寫成 5 作為合理預設，並在 migration log 提示），然後 drop 舊欄位。

## Migration Plan

1. **Migration 1**：新增 `transcription_queue` 表（含 indexes on `status`, `position`, `show_id`, UNIQUE on `episode_id`）
2. **Migration 2**：擴充 `show_schedules` — 新增 `last_refresh_at`, `last_refresh_status`, `last_refresh_message`, `max_episodes_per_run`；資料搬遷 `max_episodes` → `max_episodes_per_run`（0 → 5）；drop `max_episodes`
3. **Migration 3**：新增 `app_settings` 表，並 insert 一筆 default row `(max_concurrent_transcriptions=1, monthly_cost_cap_usd=null)`
4. **Backfill**：執行 migration 後跑一段 script，把所有現有的 pending Celery task 取消、把對應 episode 重新插入 `transcription_queue`（避免新舊 queue 同時跑）。實務上 PodcastRAG 是個人專案、無進行中 queue，這步可省略並在 release notes 註明「部署前確認沒有 in-flight 轉錄」。
5. **Deploy 順序**：
   1. Migration 上 prod
   2. 同 release deploy 新 dispatcher service + Beat service + 既有 worker（worker 程式裡 `transcribe_episode` 已加 queue row 寫回邏輯，舊 worker 不會打到新表）
   3. 觀察 1 天確認 cron tick 正常
6. **Rollback**：drop 三個 migration、停掉 dispatcher 與 Beat service、worker 仍可獨立運作（但 queue 操作 API 失效）。Rollback 不會遺失任何 transcript 資料（transcripts 不在新表）。

## Open Questions

無。Discussion 階段已收斂全部關鍵決策；未明確的小問題（拖動排序 API 細節、UI 配置）已明確 defer 到後續 UI change。
