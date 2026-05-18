## Context

PodcastRAG 目前所有 Celery task 都用 Celery 內建 `autoretry_for=(...)` + `max_retries=3` + `retry_backoff` 做重試（見 `tasks.py` / `topic_task.py` / `summary_task.py` / `quota_digest.py` / `eval_reminder.py` / `db_backup.py`）。失敗達 max_retries 後 Celery 直接放棄，沒有：
- 跨 task 失敗統計（無法判斷「是不是這個外部服務整個壞了」）
- 對外通知（除了 worker log，沒人知道）
- 暫停機制（永久錯誤 task 持續燒 retry budget + LLM quota）
- 一鍵恢復（補完額度後要人工去重 enqueue 已 mark failed 的 row）

5/10 兩個事故證實此空白：
1. EP20 transcribe 9hr 0 segments — task 無 progress 但 Celery 視為「在跑」（沒拋 exception），現有 retry 機制完全沒被觸發
2. R3.2 topic backfill 323 task silent drop — Celery 認為 task name unregistered → 直接 ack，**從來沒進 task code，當然不會 retry**，DB 沒寫一筆

既有 `api-health-tracking` capability 把每次外部 API call 結果（ts/ok/duration/http_status）寫進 Redis ring buffer，是觀測「**單次 call**」的結果。本 change 補上「**跨 task / 跨時間窗的失敗率**」與「**對 provider 暫停**」這兩個高一階的觀測 + 控制。

## Goals / Non-Goals

**Goals:**

- 任何 task 失敗都會在 DB 留紀錄（含 task name / failure_type / error_message / failed_at / provider）
- 30 min 滑動窗口統計失敗次數，超閾值寄 ZSend 告警（user 不用主動盯）
- 永久錯誤直接 mark failed 不浪費 retry 配額
- 對 provider 失敗閾值觸發後，所有後續 task 自動暫停 5 min 後 retry，避免穿過 quota
- 自動 + 手動雙路徑恢復（自動：30 min sentinel probe；手動：admin button）
- v1 簡單可上線，v2 擴充細粒度 resume 不用改 DB

**Non-Goals:**

- 不引入 Sentry / Datadog / Prometheus（觀測寫進 Postgres + ZSend 已夠）
- 不做 metrics dashboard（屬 R1.3 Langfuse 範疇）
- 不做按 task type 細粒度 resume（v2，UI-only 擴充）
- 不做 SMS / Slack / PagerDuty
- 不動 F1 修的 queue routing / dispatcher（依賴 F1 archive 後才開做，避免互相 merge conflict）
- 不重做既有 `api-health-tracking` ring buffer（保留，本 change 在它之上加聚合層）
- 不做 distributed leader election（Beat 單實例已足夠當前需求）

## Decisions

### Decision: 失敗事件寫 Postgres `task_failure_log` 表，不沿用 Redis ring buffer

**選擇**：新增 `task_failure_log` 表（`id, task_name, task_args_json, failure_type, error_message, error_class, provider_id, retry_count, failed_at, recovered_at`），每次 Celery `Task.on_failure` 觸發時寫一列。

**理由**：

- 滑動窗口聚合需要 `WHERE failed_at > NOW() - INTERVAL '30 min' GROUP BY task_name` 這類 SQL — Redis ring buffer 做不到
- 持久化保留 → 可看歷史趨勢（譬如「OpenAI 上週失敗 50 次，這週 5 次」）
- 表大小估計：每天平均失敗 < 100 筆 → 一年 < 40K 筆，加上 30d retention cron 清舊資料，PG 完全可承受

**替代**：用 Redis sorted set 加 ZADD with score=ts — 快但無歷史 + 重啟丟資料 + admin UI 查詢不好做。

### Decision: 錯誤分類用「白名單永久錯」而非「白名單暫時錯」

**選擇**：新增 `error_classifier.py` 維護 `PERMANENT_ERROR_PATTERNS` 集合：

- HTTP 4xx 中：401 / 402 / 403 / 415（檔太大）/ 422（unprocessable）
- HTTP 400 帶特定 message：`context_length_exceeded`、`invalid_api_key`、`insufficient_quota`
- Celery exception：`TaskNotRegistered`、`NotRegistered`、`KeyError("task")`
- 自定義 exception：`InvalidProviderConfigError`、`PromptTooLongError`

其他 exception 一律視為暫時錯（保守策略 — 寧可 retry 沒用，也不要錯把暫時錯當永久錯導致誤殺）。

**理由**：

- 永久錯類型有限且穩定（OpenAI / AI Hub 文件明確列出）
- 未知錯保留 retry 給 transient bug 機會
- 比白名單暫時錯（會列出無數種 timeout / connection reset / 5xx）安全得多

**替代**：白名單暫時錯 — 易漏，新類型 5xx 都會被誤殺。

### Decision: Circuit breaker 狀態存 PG `service_circuit_state` 表，不用 Redis

**選擇**：新增 `service_circuit_state` 表（`provider_id PK, state, opened_at, paused_task_count, last_probe_at, last_probe_result, manual_resumed_by, manual_resumed_at`）。state 預設 `closed`。

**理由**：

- 跟失敗 log 同 DB 方便 join 統計
- Beat probe 跟 admin manual resume 都需要 transactional 更新（避免 probe 跟 manual 同時改互踩）— PG row-level lock 解決
- 數量小（每 provider 一列，目前 3 列）效能無感
- 重啟不丟狀態（Redis 會丟）

**替代**：Redis SET / HSET — 失敗無 transaction、沒 lock、重啟丟資料。

### Decision: Task 進場 circuit check 用「自我 retry 5 min 後」而非「拒收 task」

**選擇**：task 開頭呼叫 `circuit_breaker.is_open(provider_id)`，若 `True` → `raise self.retry(countdown=300, max_retries=None)`，把 task 退回 broker 5 min 後重試。

**理由**：

- 不丟 task — 自動恢復後 task 會自然繼續
- 實作簡單，不用維護「pending 暫存表」
- 5 min 跟 sentinel probe 30 min 錯開 → 自動恢復後 task 最壞等 5 min 就再試
- `max_retries=None` 避免 task 因為長時間 circuit open 用完 retry quota（sentinel probe 才是控制點）

**替代 1**：直接 fail task 標 paused → 恢復時要重新 enqueue → 多一個「找出該重 enqueue 哪些 task」的查詢層。

**替代 2**：worker level pause（停 consume queue）→ 全部 task 包括其他 provider 的也停了 → 過殺。

### Decision: Sentinel probe 用「該 provider 現有 task 模板的 dummy 變體」

**選擇**：每個 provider 對應一個 `probe_func` 跑一個輕量請求：

- OpenAI: `client.chat.completions.create(model='gpt-4o-mini', messages=[{'role':'user','content':'ping'}], max_tokens=1)`
- AI Hub: 同上但走 AI Hub base URL
- ZSend: `GET /` health endpoint（不真的寄信）

成本 < $0.0001/次，每 30 min 跑一次 → 月成本 ~$0.001，可忽略。

**理由**：

- 用真實 API call 試水溫，比假設「過 5 min 就好了」可靠
- 跟正式 task 走同樣 client / 同樣 auth → 真的能反映 production 狀態
- 失敗也只是維持 open，不會放出大流量燒額度

**替代**：盲目過 30 min 就 reset state — 可能 quota 還沒補就放出大流量再炸一次。

### Decision: Admin 手動恢復「按 provider 一個 button」+ 資料模型留 task_type 欄位

**選擇**：v1 admin UI 「服務狀態」tab 列 3 個 provider 各一個 [⏵ 手動恢復] button。`task_failure_log.task_name` 已是細粒度，但 v1 manual resume 不分 task type — 一鍵恢復某 provider 下所有 task。但 `service_circuit_state` 預留 `task_type` 欄位（v1 全部寫 NULL），v2 可加 row 細化。

**理由**：

- v1 場景 90% 是「OpenAI 補完額度全恢復」 — 不分 task type 反而簡單
- 留 `task_type` 欄位後 v2 改 UI 加按 task type button 不用 alembic migration（per user discuss 結論）

### Decision: ZSend 失敗告警去重，不要 30 min 內每分鐘都寄

**選擇**：`failure_alert` Beat task 每 5 min 跑一次（不是每分鐘），檢查任 task 在過去 30 min 失敗 ≥ 3 次 **且** `task_failure_log.alerted_at IS NULL`，寄信後把該批 row update `alerted_at=NOW()`。

**理由**：

- 避免 user 信箱被洗
- 5 min 解析度對 user 反應夠用（既然 user 自己 30 min 才會回來看）
- alerted_at 列裡用 → 同一波失敗只寄一次

**替代**：每分鐘跑 — 信件爆炸 + ZSend SES quota 浪費。

## Risks / Trade-offs

- **Risk: PERMANENT_ERROR_PATTERNS 漏列某種 4xx → 真的永久錯被當暫時錯重試燒 quota** → Mitigation: 保守清單 + Beat task 每天巡邏「retry 3 次後 final-fail 但不在 PERMANENT 名單」的 row，告警 admin 補名單；release log 寫清楚怎麼擴充
- **Risk: Sentinel probe 跑成功但 prod 流量還是失敗（probe 跟 prod 走不同金鑰 / 不同 endpoint）** → Mitigation: probe 用跟 prod 完全相同的 ai_steps 配置，避免 drift；首次 deploy 時手動驗證 probe path
- **Risk: 自動 30 min probe 跟 admin manual resume 撞 race（兩邊同時試 close circuit）** → Mitigation: PG row lock + state transition 用 `WHERE state='open' RETURNING` atomic update，後到的 noop
- **Risk: alerted_at 機制讓「同一波失敗繼續惡化」沒 follow-up alert** → Mitigation: 30 min 後 alerted_at 過期，新 batch 進來會再寄；同時 sentinel probe 寄「仍然 open」的提示信
- **Trade-off: failure_alert 5 min 解析度 vs 即時** → 接受最差 5 min 才知道，換 ZSend 不被洗信箱
- **Trade-off: circuit per provider 而非 per provider×task_type** → v1 簡單，v2 擴充無 migration cost

## Migration Plan

1. **Stage A — DB schema + 基礎服務**（無對外行為改變）
   - alembic migration 加 2 表
   - 寫 error_classifier / circuit_breaker service
   - 全套 unit test
2. **Stage B — Worker hooks**（task 開始記錄失敗 + circuit check）
   - 改 5 個 worker（tasks / topic_task / summary_task / quota_digest / eval_reminder）的 `Task.on_failure` 寫 failure log
   - task 進場加 circuit check
   - autoretry 逻辑加 PERMANENT_ERROR 短路
3. **Stage C — Beat tasks + ZSend**
   - 加 failure_alert 跟 circuit_probe 進 beat_schedule
   - 改 zsend.py 加 helper
4. **Stage D — Admin UI + REST**
   - 加 admin_circuit.py REST endpoints
   - 加 ServiceStatusTab + nav 連結
5. **Stage E — Deploy + smoke**
   - Push → Zeabur 4 service redeploy
   - 故意把 OpenAI key set 成假的，確認 5 min 內收到告警 + circuit open + admin UI 顯示 + 手動 resume 後恢復
   - rollback：env 恢復 + alembic downgrade（兩個新表 drop，影響面 0）

### Decision: aihub 永久錯啟用 OpenAI direct fallback once

**選擇**：當 aihub provider 拋出 `ContentPolicyViolationError` / `budget_exceeded` / `insufficient_quota` 三種特定永久錯時，task 在寫 failure log 跟觸發 circuit 之前，先嘗試一次 OpenAI direct fallback。Fallback 用硬編碼 `AIHUB_TO_OPENAI_MODEL_MAP` 對映表（gpt-5-mini→gpt-4o-mini、gemini-2.5-flash-lite→gpt-4o-mini、gpt-4o-mini→gpt-4o-mini、gpt-4o→gpt-4o；claude-haiku-4-5 無 fallback）。

**理由**：

- 直接動機：2026-05-10 prod 觀察 aihub 後面是 Azure OpenAI，Azure 內容過濾器會擋部分中文 podcast 內容（藥名 / 髒話 / 敏感話題）。OpenAI direct 沒這個過濾器
- ContentPolicy 跟 budget 都是「對換 provider 就能解決」的錯，重試本身才是真解
- 限定一次 fallback：避免 aihub→openai→aihub 死循環
- 限定 aihub 方向：openai direct 失敗沒第二供應商可換，沒 fallback 必要
- 模型映射硬編碼：簡單、可預期；新增模型加一行 dict entry 即可，不需 DB schema 變動

**替代 1**：兩個 provider 互相 fallback — 死循環風險高，且 openai direct 沒理由 fallback 到 aihub。

**替代 2**：fallback 配置寫進 DB（ai_steps_fallback 表）— 過度工程化，目前只有 1 個方向 + 5 個模型，硬編碼足夠。

**替代 3**：直接把 aihub model 換成 gemini-2.5-flash-lite 解決 Azure 過濾（已在 2026-05-10 session 做了 hot-swap）— 這是個臨時解，但不能解決 budget_exceeded（充值 race window 期間仍會失敗）。Fallback 是更通用的長期解，跟 model swap 互補。

## Open Questions

- `failure_alert` 寄信內文格式：純文字 vs HTML？傾向純文字（user 是技術人 + ZSend 純文字 deliverability 高）
- circuit open 時是否要在 backend `/health` endpoint 反映？傾向不反映（健康檢查是 service-level，circuit 是 provider-level，混在一起容易誤報 service down）
- Admin button 按下時是否先彈確認？傾向是（避免誤按浪費 quota）
