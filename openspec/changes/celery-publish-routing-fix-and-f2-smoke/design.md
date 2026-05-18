## Context

F1（`celery-routing-and-dispatcher-fix`，2026-05-18 archive）把 Celery 拆成 4 條 queue（`transcribe` / `topic` / `summary` / `control`），並用 `task_routes` 把所有 task 對應到指定 queue、`task_default_queue="control"` 當安全網。F2（`task-failure-monitoring-and-circuit-breaker`，2026-05-18 ship）在 F1 之上加 circuit breaker、`paused_task_count`、ZSend 告警、SummaryTask base class 等。

F2 ship 後 smoke 抓到「重新生成 AI 摘要」按鈕點下去 backend 回 `200 {"enqueued": true}`、但 worker 從未收到 task、Redis `summary` queue 也是空的。其他三種 task type（`cron_tick` / `transcribe_episode` / `classify_episode_topics`）都正常被 worker pick → 不是整體 routing / worker / broker 全死，**只 summary publish 這條路 silent drop**。

附帶在 default `celery` queue 撈到一筆殘留 stuck `cron_tick`，代表 beat 的 publish 也有走錯 routing（F1 沒清乾淨的 leak）。

相關 specs：`task-queue`（Celery routing / publish 行為）、`task-failure-monitoring-and-circuit-breaker`（F2 行為驗證收尾，但其 spec 文字不動）。

## Goals / Non-Goals

**Goals:**

- 定位「backend `.delay()` 回 200 OK 但訊息沒進 broker」的真正原因（必須 reproducible 證據，不能停在猜測）。
- 修好 publish-side 後，「重新生成 AI 摘要」按鈕一按 worker 在數秒內收到 task 並執行。
- 順手把 default `celery` queue 的 `cron_tick` leak 清掉，未來 cron_tick 不會再卡 default queue。
- 跑完 F2 完整主動 smoke（circuit open / 告警 / resume / recovery / UI badge），讓 F2 可以乾淨 archive。

**Non-Goals:**

- 不重構 Celery 整體 init 結構（除非 root cause 真在這層）。
- 不換 broker。
- 不改 F2 circuit breaker 業務參數（threshold / TTL / pause window）。
- 不在本 change 動 F2 spec 文字。
- 不 backfill 已被 silent drop 的歷史 summary request（使用者重按即可）。

## Decisions

### Decision: 先 investigate 才動手修

**選擇**：先把 4 個 leading hypothesis 逐一驗證、拿到 reproducible 證據鏈再寫 fix code。

**理由**：

- 表面 code 看起來都對（routing / task name / include / decorator 都存在），盲修很可能改錯點、回頭還是 silent drop。
- 4 個 hypothesis 各有不同的修法（env 對齊 / broker connection failover / task name resolution / module import 副作用），錯估會延誤 F2 收尾。
- silent drop 最危險，留半信半疑的修法在 prod 等於沒修。

**替代**：直接「加 `broker_connection_retry=False` + `task_publish_retry_policy={'max_retries': 0}` 強制 publish 失敗 raise」逼出 traceback — 治標、改完仍不知原本為什麼吞錯，未來再犯不一定能複現。

### Decision: 4 個 leading hypothesis（root cause 候選）

**H1：Backend FastAPI process 跟 Celery worker process 用不同 `CELERY_BROKER_URL`**

- 場景：Zeabur 在 backend service 跟 worker service 分別設 env，兩邊指到不同 Redis instance（或一個指 internal hostname、一個指 public hostname、或一個有 typo）。
- 後果：backend `.delay()` 推進 broker A，worker 聽 broker B，broker A 沒人 consume → 訊息積在 broker A 永遠不被收到。但本 case Redis `summary` queue `llen=0` → broker A 也沒收到，反證可能不是這個；除非 backend env `CELERY_BROKER_URL` 根本指到第三個失效的 instance / 空字串走 fallback。
- 驗證方法：見 Investigation Methodology H1。

**H2：Backend FastAPI process import `celery_app` 時 broker 連線初始化失敗 + `broker_connection_retry_on_startup=True` 退化成 in-memory/null transport**

- 場景：Celery 有 `broker_connection_retry_on_startup` 與 publisher pool 機制；如果第一次 connect 失敗、且 `task_publish_retry_policy` 設 `max_retries` 但仍最終失敗、且 producer code path 把 exception 吞掉，`.delay()` 會 return 一個 `AsyncResult` 看起來成功但訊息其實沒落 broker。
- 後果：log 完全乾淨、Redis llen=0、worker 從沒收到 — 完全符合本 case 現象。
- 驗證方法：見 Investigation Methodology H2。

**H3：F2 `SummaryTask` base class 影響 task name resolution**

- 場景：F2 新增 `SummaryTask(Task)` base class 含 `on_failure` / `on_success` hook 來餵 circuit breaker。Celery `name="..."` explicit 設定理論上 publisher 跟 worker 都用同一 string、不該 mismatch；但若 base class `__init_subclass__` 或某個 metaclass 行為改變 task name 註冊到 `app.tasks` registry 的 key，publisher 看到的 task name 跟 routes 對不上 → task 走 `task_default_queue="control"` 而不是 `summary`。
- 後果：訊息會出現在 `control` queue 而不是 `summary` queue。本 case 沒驗 control queue llen → 需補驗。
- 驗證方法：見 Investigation Methodology H3。

**H4：F2 對 `summary_task.py` 加 entry circuit check 提早 raise / module-level 副作用炸 import**

- 場景：F2 在 summary_task module 加 `import` 時跑的副作用（譬如 module-level `circuit_state = get_circuit_state(...)` 連 DB / Redis），backend process import 時失敗、被吞掉、`generate_episode_summary` symbol 雖然存在但其實沒 bind 到 celery app；或 task entry 第一行直接 `raise CircuitOpen` 但 publisher 不會看到（publisher 只是 send_task，不會 run task body）。
- 後果：worker 端 import 時也會踩同樣副作用 → 但 worker 還活著且能 pick `cron_tick` / `transcribe` / `topic` 三種 task，所以這個 hypothesis 機率最低，但需排除（worker 可能因 import 順序差異而沒踩到）。
- 驗證方法：見 Investigation Methodology H4。

### Decision: Investigation methodology（具體 SOP）

**H1 驗證**：

```
zeabur variable list --id <backend_svc>   | grep CELERY_BROKER_URL
zeabur variable list --id <worker_svc>    | grep CELERY_BROKER_URL
zeabur variable list --id <dispatcher_svc>| grep CELERY_BROKER_URL
zeabur variable list --id <beat_svc>      | grep CELERY_BROKER_URL
```

四個 service 的 broker URL 字串必須完全一致。任何差異（hostname / port / db number / password）即為 root cause。**注意 secret hygiene**：取得結果落 `/tmp` 檔、不印 chat。

**H2 驗證**（backend container 直接驗 broker 連線）：

```
zeabur service exec --id <backend_svc> --interactive=false -- python -c "\
from app.workers.celery_app import celery_app
conn = celery_app.broker_connection()
conn.ensure_connection(max_retries=3)
print('connected:', conn.connected, 'transport:', conn.transport_cls)
"
```

預期 `connected: True transport: redis`；若 transport 出現 `memory` / `None` / raise exception → H2 confirmed。

**Backend container 直接送 test task 驗證 publish**：

```
zeabur service exec --id <backend_svc> --interactive=false -- python -c "\
from app.workers.summary_task import generate_episode_summary
r = generate_episode_summary.delay('11111111-1111-1111-1111-111111111111')
print('task_id:', r.id, 'backend:', r.backend)
"
```

接著立刻 `redis-cli -h <host> -a <pw> llen summary` 看 llen 是否從 0 變 1。若 llen 不動但 `r.id` 看起來合法 → publish silent drop confirmed in backend process。

**H3 驗證**：

```
zeabur service exec --id <worker_svc> --interactive=false -- celery -A app.workers.celery_app inspect registered | grep summary
zeabur service exec --id <worker_svc> --interactive=false -- celery -A app.workers.celery_app inspect active_queues
```

確認 worker 端註冊的 task name 字串。Backend container 同樣方式列：

```
zeabur service exec --id <backend_svc> --interactive=false -- python -c "\
from app.workers.celery_app import celery_app
print([t for t in celery_app.tasks if 'summary' in t])
print(celery_app.conf.task_routes)
"
```

兩邊 task name string 必須完全一致；routes dict 必須含對應 key。

另：補驗 `redis-cli llen control` —— 若 control queue llen > 0 且裡頭有 summary task，H3 confirmed（routing fall-through）。

**H4 驗證**：

```
zeabur service exec --id <backend_svc> --interactive=false -- python -c "\
import app.workers.summary_task as m
print('module loaded:', m)
print('task obj:', m.generate_episode_summary)
print('task app:', m.generate_episode_summary.app)
"
```

確認 backend process 端 task object 確實 bind 到正確 celery app instance（非 None / 非 dummy）。若 `task.app` is None 或不是 prod celery_app → H4 confirmed。

### Decision: F1 cron_tick leak fix 策略

**選擇**：直接在 beat schedule 的對應 entry 加 `options={"queue": "control"}`，不依賴 `task_routes` 自動分流。

**理由**：

- F1 雖然有 `task_routes` + `task_default_queue="control"`，但 beat 的 publish path 在某些 Celery 版本對 `options` 顯式指定比 `task_routes` 優先；殘留的 stuck `cron_tick` 在 default `celery` queue 暗示 beat 沒走 routes。
- 顯式 `options.queue` 是 Celery 官方建議的 beat 寫法，最不會被未來 routing 變動影響。

**替代**：debug 為什麼 beat 沒走 routes —— 屬於本 change 的 investigation 副線；若 H1-H4 root cause 與 beat 同源就一起修，否則直接 patch beat entry 比較快。

### Decision: F2 smoke 用「真實流量 + 主動觸發」雙管

**選擇**：

- 主動觸發 fault：手動 patch summary_task entry 強制 `raise` N 次（N = circuit threshold），驗 circuit open / pause；recovery 用「等 TTL 過 + 手動 resume」雙 path 各驗一次。
- 告警驗證：用 ZSend test mode（已建立的 test recipient），不寄到正式收件人。
- UI 驗證：chrome-devtools-mcp 開後台 task 狀態頁，截圖確認紅色 badge 與 pause 數字。

**理由**：

- 純等真實流量觸發 circuit 不可控、demo 不出來。
- ZSend 真寄到 owner 信箱會洗版 + 失去測試意義。

### Decision: 不在本 change 改 F2 spec 文字

**選擇**：本 change 只做 publish-side bug fix + smoke 收尾。F2 spec（`task-failure-monitoring-and-circuit-breaker`）的 requirement 文字維持原狀。

**理由**：

- F2 spec 描述「circuit open / pause / 告警」的行為本身沒錯，被卡的是 publish path 而非 circuit logic。
- 若 investigation 證實 `task-queue` spec 對 publish path 行為（譬如「publish 必須驗證 broker 收到才回 enqueued=true」）需要新增 requirement，再以 spec delta 補在本 change。

## Implementation Contract

**Behavior（修完後使用者觀察到的）**：

- 後台「重新生成 AI 摘要」按鈕一按，backend 回 `200 {"enqueued": true}`，worker 在 10 秒內 log 出 `Task app.workers.summary_task.generate_episode_summary[...] received`，並依正常流程跑摘要。
- 後台 task 狀態頁在 circuit open 時顯示紅色 badge + `paused_task_count > 0`；resume 後 badge 變綠。
- ZSend 告警信在 circuit 達到 threshold 時送出一封；recovery（TTL 過 / 手動 resume）後再送一封 recovery 通知。
- default `celery` queue 沒有任何殘留 cron_tick 訊息；所有 cron task 都進 `control` queue。

**Interface / data shape**：

- 不新增 API endpoint；不新增 DB schema；不新增 env 永久變數（`SUMMARY_TASK_FORCE_RAISE` 是臨時 smoke flag，smoke 結束移除）。
- 若 fix 涉及 `celery_app.py` 修 broker config（e.g. 把 `broker_connection_retry_on_startup=True` 改 False、或加 `task_publish_retry_policy={'max_retries': 3, ...}`），維持向後相容。
- 若 fix 涉及 beat schedule entry，每個 entry 都顯式加 `options={"queue": "control"}` dict。

**Failure modes**：

- Publish 真的失敗時（譬如 broker down）：必須 raise 到 API layer 回 5xx，**不可** silent return `{"enqueued": true}`。Fix 後此行為應由 unit test 或 manual repro 確認。
- Circuit open 時：summary task entry 走 fast-fail 路徑（既有 F2 行為），不會打 LLM provider。
- ZSend 額度耗盡：告警退化為 log warning，不阻擋 circuit pause 主流程。

**Acceptance criteria**：

- H2 SOP 的 test task call 在 backend container 內跑：`r.id` 拿到 + `redis-cli llen summary` 從 0 變 1（或 fix 後 publish 失敗時 raise，呼叫端拿到 exception）。
- chrome-devtools-mcp 在 prod 後台執行 「重新生成 AI 摘要」 → worker log 在 10 秒內出現對應 received line。
- 主動 smoke：5 個 sub-check（circuit open / paused_task_count 上升 / 告警信寄出 / 後台紅 badge / 手動 resume + recovery 信）全綠並截圖留證。
- default `celery` queue `llen=0` 持續 24 hr。

**Scope boundaries**：

- In scope：publish-side root cause 調查與修復、beat cron_tick leak 修復、F2 完整主動 smoke、release log + 路線圖收尾、archive F2。
- Out of scope：F2 spec 文字修改、circuit breaker 業務參數調整、broker 換型、worker concurrency / queue 拆法調整、歷史 silent drop 訊息 backfill。

## Risks / Trade-offs

- **Risk：investigation 拿不到 reproducible 證據（H1-H4 全 negative）** → Mitigation：補第五個 hypothesis（譬如 backend FastAPI 的 async event loop 跟 Celery sync producer 衝突、或 connection pool 在 multi-worker uvicorn 下被孤兒化），擴大 SOP；不要為了趕進度盲修。
- **Risk：修了 publish 但 F2 主動 smoke 仍卡在別處（譬如 ZSend 額度耗盡、UI 沒實作 badge）** → Mitigation：smoke 拆成 5 個 sub-task，每個獨立驗、卡哪個記哪個。
- **Risk：cron_tick leak fix 改 beat schedule 影響其他 cron task（quota_digest / db_backup / eval_reminder / tokenizer_reload）** → Mitigation：beat schedule 每個 entry 都加 `options.queue="control"`（F1 既有意圖），改完跑 beat 一個完整 cron cycle 驗證每個 task 都走對 queue。
- **Risk：手動觸發 fault 的 patch 忘記 revert，prod 一直 raise** → Mitigation：patch 用 feature flag（env `SUMMARY_TASK_FORCE_RAISE=true`）控制、smoke 完成立刻 unset + redeploy；不直接改 code。
- **Trade-off：investigation 階段花 0.5-1 天，F2 主動 smoke 必須往後延** → 可接受；F2 routing 部分既有功能在 prod 已運作，不影響其他 task type。

## Migration Plan

1. **Stage A — Investigation（tasks 1.x）**：跑 4 個 hypothesis 驗證 SOP，寫 root cause 報告（不 commit code）。
2. **Stage B — Fix publish-side bug（tasks 2.x）**：依 root cause 改 code / config / env；本機跑單元測試（若可）。
3. **Stage C — Fix cron_tick leak（tasks 3.x）**：改 beat schedule entry；驗證 default queue 不再有殘留 cron_tick。
4. **Stage D — Deploy**：commit + push main → Zeabur 四 service redeploy → 用 H2 SOP 的 test task call 驗證 publish 真的進 broker。
5. **Stage E — F2 主動 smoke（tasks 4.x）**：用 `SUMMARY_TASK_FORCE_RAISE` 觸發 N 次 fault → 看 circuit open → 看 `paused_task_count` 上升 → 收到告警信 → 後台紅 badge → 手動 resume → recovery 信 → unset flag + redeploy。
6. **Stage F — 收尾（tasks 5.x）**：release log entry / 路線圖更新 / archive F2 / archive 本 change。
7. **Rollback**：publish-side fix 若引入 regression（譬如 cron_tick / transcribe / topic 也壞），git revert 該 commit + worker / backend redeploy；leak fix 與 smoke 階段獨立可選擇性 revert。

## Resolved Questions

- **是否需要動 F2 spec 文字？** → 不動。F2 spec 描述的 circuit / pause / 告警行為正確，本 change 是 publish path bug，不影響 F2 requirement 語義。
- **是否合併 aihub-adapter fallback typed exception wiring？** → 視 H1-H4 root cause 而定。若 root cause 與 fallback wiring 共用 code 路徑（譬如 Celery producer 對 exception 的處理）就一次解；否則拆獨立 follow-up change，本 change 只負責 publish bug + leak + smoke。

## Open Questions

- **H1-H4 四個 hypothesis 涵蓋完整嗎？** → 待 investigation 第一輪後檢視；若全 negative 需補 H5+。
- **Test task call 使用的假 episode_id 會不會被 worker 真的拿去跑 + 失敗 + 觸發 F2 circuit？** → 用真實但 status=cancelled 或不存在的 id 較安全；smoke 階段要記得排除這幾筆對 F2 統計的污染。
