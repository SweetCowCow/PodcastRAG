## Problem

Eval runner 對 enumeration 題型的計分只看公開 search endpoint（`POST /shows/{id}/search`）回的 top-K=5 chunks，從中抽 episode_ids 算 `episode_set_recall`。但實際對使用者有意義的「相關集數列表」是 chat endpoint（`POST /shows/{id}/query`）回應裡的 `enumeration_episodes` 欄位（R3.3 + r3-3-chat-enum-grounding 引入），這個欄位**完全沒進計分**。

具體量化失準（2026-05-16 跑 r3-3-chat-enum-grounding eval baseline 抓到）：

- q25「節目裡有哪些集是歌單？」expected 25 集
- Runner 算的 `episode_set_recall` = **0.04**（1/25，search top-K=5 結構性 ceiling 是 0.20）
- 手動打 chat endpoint：`enumeration_episodes` 回 23 集，命中 expected 25 集中的大多數，真實 `episode_set_recall` ≈ **0.92**

差距 23 倍。所有後續 retrieval / enumeration 改動的 eval lift 都會被低估到看不出，等於量測瞎子飛。

## Root Cause

`backend/eval/runners/run.py` 的 enumeration 計分分支：

```python
if eval_mode == "enumeration":
    retrieved_eps = _to_episode_ids(chunk_ids)  # 只從 search top-K chunks 推
    ep_recall = episode_set_recall(retrieved_eps, expected_eps)
```

`chunk_ids` 來自 `_retrieve(backend_url, show_id, question, top_k, token)` — 這個函式只打 search endpoint。當初寫的時候 enumeration_episodes 欄位不存在（R3.3 才加），runner 沒被擴充。`rag-eval-runner` spec 也只描述了 search-endpoint 路徑。

## Proposed Solution

對 `eval_mode == "enumeration"` 的項目，runner 在原本的 search top-K retrieval 之外，**額外**呼叫 chat endpoint 拿 `enumeration_episodes`，把這些 episode_id 併進 `retrieved_episode_set`：

1. `_retrieve_chat_enumeration(backend_url, show_id, question, token) -> (list[uuid], int | None)` 新增 helper。打 `POST /shows/{id}/query` body `{mode: "chat", question, messages: []}`、需要 session cookie + CSRF token（CSRF 走 `/me` 響應 body 拿，與 frontend `AuthContext` 同 pattern）。回傳值：episode_id 列表 + 完整 `enumeration_total`。
2. Enumeration 計分改成：
   ```python
   retrieved_eps_search = _to_episode_ids(chunk_ids)
   retrieved_eps_chat, chat_total = _retrieve_chat_enumeration(...)
   retrieved_eps = set(retrieved_eps_search) | set(retrieved_eps_chat)
   ep_recall = episode_set_recall(retrieved_eps, expected_eps)
   ```
3. JSON 報表每個 enumeration item 多帶 `enumeration_episodes_count: int` 欄位（chat path 拿到的列表長度）以及 `episode_set_recall_chat_only: float`（只用 chat path 算的 recall，方便 RCA 對比兩路徑）。

Chat endpoint 比 search 貴（每呼叫 ~3-5s + 消耗 quota），所以**只對 enumeration item 多打**這條，非 enumeration item 保持只打 search。

## Non-Goals

- **不改 search endpoint 端的計分行為**：chunk_id / open_set_lenient 模式繼續完全靠 search top-K chunks，不打 chat，不會增加 cost
- **不變更 spec 的 chunk-based aggregation**：`metrics.chunk_based.recall_at_k_mean` 維持只算 chunk_id / open_set_lenient
- **不引入新 dataset 欄位**：`expected_episode_ids` 既有欄位夠用
- **不對 enumeration 加 top-K 限制**：chat enumeration_episodes 後端不 cap（per r3-3-chat-enum-grounding Decision 6），runner 全收
- **不改 token / auth 路徑**：繼續用 `--auth-token` flag + session_id cookie（與 frontend pattern 一致）

## Success Criteria

1. 對 prod 重跑 r3-3-chat-enum-grounding 那輪 eval（commit `7250969`），q25 歌單的 `episode_set_recall` 從 0.04 跳到 ≥ 0.85（命中 23+/25）
2. q26 高雄美食的 `episode_set_recall` 從 0.333 跳到 ≥ 0.5（chat 應該也能撈到 expected 之外的 4-5 集中的多數）
3. chunk_based 子集（n=28）的 Recall@5 / MRR 數字 **byte-identical**（runner 對非 enumeration item 行為不變）
4. JSON 報表每個 enumeration item 新欄位 `enumeration_episodes_count` 與 `episode_set_recall_chat_only` 都存在且為合法數值
5. 新加的 `_retrieve_chat_enumeration` 函式對「chat endpoint 回 5xx / 沒 csrf / 空 response」三個 failure 路徑 fail-open 回 `(empty list, None)`，runner 不 crash 繼續跑下一題

## Impact

- Affected specs:
  - Modified: `rag-eval-runner`（`Enumeration scoring` requirement 改為「search + chat union」；新增「Chat enumeration query fail-open」requirement）
- Affected code:
  - Modified:
    - `backend/eval/runners/run.py`（新增 `_retrieve_chat_enumeration` helper；enumeration 分支改成 union 計分；JSON 報表 schema 加兩欄位）
  - New:
    - `backend/tests/test_runner_chat_enumeration.py`（helper 單元測試 + enumeration 計分 union 邏輯測試 + fail-open 路徑測試）
  - Removed: 無
