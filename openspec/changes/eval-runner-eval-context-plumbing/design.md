## Context

雙寫架構（`eval-framework-upgrade` 2026-05-30 ship）已就位：

- PG `eval_traces` 表結構完整（`b6c7d8e9f0a1` migration、23 欄 + 3 索引含 `(run_id, item_id)`）
- `span_writer.write_span()` 對 PG 雙寫 + ON CONFLICT DO NOTHING + try/except fail-safe
- `set_eval_context()` / `get_eval_context()` ContextVar API 已在 `backend/eval/tracing/langfuse_setup.py` 就位
- `agent.py` 內 `propagate_attributes` 區段已從 `get_eval_context()` 撈 item_id / run_id / turn_idx、注入 Langfuse Cloud metadata
- `?debug_trace=true` admin gate 已就位（`backend/app/api/query.py` 內 `include_trace = debug_trace and user.role == "admin"`）

但驗證後確認 `set_eval_context()` 全 codebase 零 caller，導致：

- PG sink 對所有流量（prod + eval）皆 skip 寫（ContextVar default None → `write_span` early return on missing `item_id`/`turn_idx`/`run_id` per `span_writer._REQUIRED_COLUMNS`）
- Cloud sink 雖然 `@observe` 仍會上傳 trace，但 metadata 內 `item_id`/`run_id`/`turn_idx` 也全空

eval runner（`backend/scripts/run_chat_agent_eval_v2.py`）跟 `/query` endpoint 是 out-of-process 關係，ContextVar 沒法跨 process 傳遞。所以本 change 的核心：在 runner ↔ backend 之間定義一個三欄 metadata 傳輸契約，並把 backend 收到後 bind ContextVar 的位置定下來。

## Goals / Non-Goals

**Goals:**

- eval runner v2 跑前 generate 一個 `run_id` 字串、寫進結果 JSON 檔頭
- runner 每送一 turn 注入 `X-Eval-Run-Id` / `X-Eval-Item-Id` / `X-Eval-Turn-Idx` 三個 HTTP header
- backend `/query` 對 admin role + 三個 header 齊全的請求呼叫 `set_eval_context()` + finally `reset_eval_context()`
- 非 admin 或 header 不齊：靜默忽略（不 4xx），ContextVar 保持 None、PG sink 維持 skip
- 跑完一輪 calibration_8 後可用 SQL `WHERE run_id = ? GROUP BY item_id, turn_idx` 證明每 turn 都有 span 且三欄填滿
- `prompt_fingerprint_diff.py` 接通 `--source=sql --run-id-old=... --run-id-new=...` 路徑、產出 markdown diff

**Non-Goals:**

- v1 runner（`run_chat_agent_eval.py`，schema_version=1）不動
- 不擴 PG schema（已就位）
- 不改 Cloud SDK 路徑（metadata 注入已就位）
- 不做「Cloud → PG 補拉」reconcile script（未來 follow-up）
- 不對 prod user 流量寫 PG（ContextVar 預設 None → skip）

## Decisions

### Decision 1：Transport 用 HTTP header 不用 query string 或 body

選 `X-Eval-Run-Id` / `X-Eval-Item-Id` / `X-Eval-Turn-Idx` 三個 custom HTTP header。

**Alternatives：**

- (a) Query string `?eval_run_id=...&eval_item_id=...&eval_turn_idx=...`
- (b) Request body 加 `eval_context: {run_id, item_id, turn_idx}` Optional field

**Rationale：**

- (a) Query string 會洩到 access log，違反 `feedback_zeabur_deployment_log_leaks_query_string.md` SOP；item_id 不是 secret 但符合 trace context 不放 query string 原則
- (b) Body 改動會污染 `ChatQueryRequest` Pydantic model、影響所有 client；header 是 admin debug gate 既有 pattern 同類延伸（per LANGUAGE.md `Admin debug gate` 定義）
- Header 在 nginx / FastAPI middleware 都好處理、不會落 access log

### Decision 2：Auth gate 共用 `?debug_trace=true` admin gate

只有 `user.role == "admin"` 才 honor 三個 header 並呼叫 `set_eval_context()`；非 admin 或缺 header 靜默 ignore。

**Alternatives：**

- (a) 新增 eval-only role 或 secret token
- (b) 任何帶 header 的請求皆 bind ContextVar

**Rationale：**

- (a) 過度設計、現階段只有一個 admin（`ssweetcoww@gmail.com`）跑 eval
- (b) 開放 prod user 流量寫 PG 會污染 dataset、違反 design Decision 1a「prod user traffic leaves this None」
- 沿用既有 admin gate pattern 簡化心智模型

### Decision 3：Bind 點用 FastAPI dependency 不用 middleware

寫 `bind_eval_context()` dependency、`/query` endpoint signature 內 `Depends(bind_eval_context)`，內部 try / finally `set` → `reset`。

**Alternatives：**

- (a) ASGI middleware 跑全 endpoint
- (b) `/query` endpoint 內 inline 呼叫

**Rationale：**

- (a) middleware 影響所有 endpoint、過廣；目前只 `/query` 需要
- (b) inline 不易測試、若未來 `/search` 也要可以再開 follow-up 加 Depends（YAGNI 守住現範圍）
- Dependency 模式跟既有 `get_current_user` / `get_db_session` 一致、好讀

### Decision 4：run_id 命名 = ISO 時間 + 8 字隨機

格式 `eval-YYYYMMDDTHHMMSSZ-<8-char-hex>`，例 `eval-20260530T153012Z-a1b2c3d4`。

**Alternatives：**

- (a) 純 UUID4
- (b) 使用者自填 `--run-id` 參數

**Rationale：**

- UUID4 排序差、看不出時間；時間前綴方便 ls / grep + 跨 day 對齊
- 8 字隨機尾巴避免同秒撞名（同人手動 retrigger 兩 run）
- runner CLI 仍可 `--run-id` override（debug 場景）但 default 自動生成

### Decision 5：SQL RCA demo script 跟 plumbing 一起 ship

新增 `backend/eval/scripts/sql_rca_demo.py`，跑完 plumbing 後執行此 script 對 PG 跑三條代表性 SQL，作為「plumbing 通了」的 verify 手段，同時對未來 Tier 1 b20 RCA / Tier 2 retrieval change 是現成範本。

**Alternatives：**

- (a) 純做 plumbing、demo script 推 follow-up
- (b) 把 SQL 寫進 README 不做 script

**Rationale：**

- (a) plumbing 無 verify ground truth 就 ship 違反 `feedback_verification_discipline`；要證實 PG 真寫進
- (b) script 比 README 更可重複跑、CI 也能 invoke

## Implementation Contract

### 行為（observable）

- 任何一輪 `run_chat_agent_eval_v2.py` 跑完後：
  - 結果 JSON 檔頭含 `"run_id": "eval-..."` 欄位
  - PG `eval_traces` 對該 `run_id` 至少有 1 個 span（cal_8 = 8 item 各至少 1 span，multi-turn item 各 turn 各至少 1 span）
  - 對該 run_id 所有 span，`run_id` / `item_id` / `turn_idx` 三欄皆 NOT NULL
- prod chat 流量（無 admin role 或無三個 header）：
  - eval_traces 對該 request 寫入 0 筆（既有行為不變）
  - Langfuse Cloud 仍正常收 trace（既有行為不變）

### 介面 / data shape

- HTTP header：
  - `X-Eval-Run-Id: <str>` — runner 生成的 run 識別字串
  - `X-Eval-Item-Id: <str>` — golden set item id（譬如 `b20`、`mt01`）
  - `X-Eval-Turn-Idx: <int as str>` — 多輪題的 turn index（單輪題 = 0）
- FastAPI dependency：
  - 函式名 `bind_eval_context`，位置 `backend/app/api/deps.py`
  - 簽名類 async generator：取 request headers + 當前 user → 條件 set/reset ContextVar
  - 行為：admin role + 三 header 齊全 → set；否則 yield 不動 ContextVar
- Runner 結果 JSON：
  - 檔頭 metadata 內新增 `run_id` string field（既有 `backend_commit` / `timestamps` 旁邊）
- SQL RCA demo CLI：
  - `python -m backend.eval.scripts.sql_rca_demo --run-id <run_id> [--compare-run-id <other_run_id>]`
  - 印三段 SQL 結果：(1) per-turn span count (2) optional 跨 run search_query diff (3) per-turn tool timeline

### Failure modes

- 三 header 任一缺 → 靜默不 bind（不 4xx，不影響既有 request）
- `set_eval_context()` 內部 raise → 包 try/except、log warning、不 break request（per design Decision 7 fail-safe）
- PG insert 失敗 → `span_writer` 既有 try/except 捕捉、log warning、不 raise（既有行為）
- 同 `run_id` 重複 span_id → ON CONFLICT DO NOTHING（既有行為）

### Acceptance criteria

- 新 unit test `backend/tests/test_eval_context_dependency.py` 至少三 case 通過：
  - admin + 三 header 齊全 → ContextVar 被 set 為 dict、reset 為 None
  - non-admin + 三 header 齊全 → ContextVar 保持 None
  - admin + header 不齊 → ContextVar 保持 None
- 對 `_calibration_8.json` 跑一輪 v2 runner、然後手動 SQL `SELECT COUNT(*), COUNT(DISTINCT item_id) FROM eval_traces WHERE run_id = '<that_run_id>'`：count > 0 且 distinct item_id ≥ 8
- `sql_rca_demo.py` 對該 run_id 跑、三段 SQL 都有非空輸出
- `prompt_fingerprint_diff.py --source=sql --run-id-old <r1> --run-id-new <r2>` 對兩個 run_id 跑出 markdown diff、與 inline-HTTP 版本對 calibration_8 結果（item/turn/tool/query）一致

### Scope boundaries

**In scope：**

- runner v2 改動（run_id 生成 + header 注入 + result JSON header）
- `/query` endpoint dependency 加入
- `bind_eval_context` dependency 實作 + unit test
- `sql_rca_demo.py` 新建
- `prompt_fingerprint_diff.py --source=sql` 路徑

**Out of scope：**

- v1 runner 改動
- 其他 endpoint（`/search` 等）加 dependency
- PG schema 改動
- Langfuse Cloud SDK 改動
- Cloud → PG reconcile / backfill script
- prod chat 流量寫 eval_traces

## Risks / Trade-offs

- **Header injection 風險**：admin 帳號被盜用就可以亂塞 run_id 污染 PG → Mitigation：admin gate 已是現有信任邊界，本 change 不擴大攻擊面；若日後想多人跑 eval，再加 audit log
- **PG insert latency 對 eval timing 影響**：fire-and-forget 但 `await session.commit()` 仍 block → Mitigation：single-row INSERT 進 indexed table 通常 < 5ms、對 eval 用例可接受（eval 比的是 baseline 差異不是絕對 latency）；若實測超過 20ms / span 再評估 background task 化
- **跨 run SQL 比對誤對齊**：若同個 item_id 在兩個 dataset 版本意義不同會誤比 → Mitigation：dataset 走 schema_version 區分、demo SQL 加 `WHERE run_id IN (...)` 限縮、不靠 item_id 跨版比較
- **Dependency 順序錯誤把 set 跑在 user role 未解前**：FastAPI dependency tree 解析 → Mitigation：在 `bind_eval_context` signature 內 `Depends(get_current_user)` 顯式宣告依賴，FastAPI 保證 resolve 順序
