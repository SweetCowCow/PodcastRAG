## Why

`route_episodes`（two-layer routing 第一層）正在主動傷害真實使用者 query 的 retrieval：

| 指標 | 有 routing | 跳過 routing |
|---|---|---|
| Recall@5（10 題 human-curated golden set，q01-q10）| 0.0625 | **0.4375** |

2026-05-13 spike 顯示移除 routing 直接帶來 **7x improvement**。Root cause：routing SQL 是 pure cosine + DISTINCT-per-episode，沒 lexical 信號；帶專有名詞的 query（如「節目名「這又沒有很屌」是怎麼來的？」）會被 cosine 拉到「description 提到該書名的 episodes」，**真正答案所在的 EP1（講由來的那集）被排到 top-10 外**，retrieve 階段根本看不到候選。

Routing 2026-05-11 加入時是 hotfix（R3.2 baseline 從 R3.1 23.8% 退到 15.5%），但那個 baseline 量在 LLM-auto-inflated 測試集上 — LLM-auto 題 anchor 跟 question keywords 高度重疊，routing 撈得到紅利；真實 user query 上 routing 反而擋住答案。Audit 完成後（移出 36 個 LLM-auto 壞題、補 q05 EP66 anchor），純人類測試集顯示 routing 是淨負面。

## What Changes

- 把 `_should_skip_routing()` 的 `ENABLE_TWO_LAYER_ROUTING` 環境變數 default 從 `"true"` 改 `"false"`
- Prod 環境設定 `ENABLE_TWO_LAYER_ROUTING=false`（flag 早已存在，本 change 把它正式 ship 為新預設值）
- Golden set audit 結果固化進 `backend/eval/datasets/this-not-that-cool.json`：移出 36 個 `thisno-core-*` LLM-auto 壞題、補 q05 EP66 anchor、加 audit 記錄段落
- 更新 `docs/case-studies/r32-routing-regression-2026-05-11.md` 補 follow-up note：當初 routing hotfix 的判斷基於有問題的測試集
- 不刪 routing 相關 code（`route_episodes` / `_ROUTE_EPISODES_SQL` 保留），預留未來改進 routing（加 lexical 信號）的路徑

## Non-Goals (optional)

- 不在本 change 修 routing SQL 加 lexical 信號（另起改進 routing 的 r3.x change）
- 不在本 change 動 embedding model（`text-embedding-3-large` 維持，r3-4 archive 條件改寫但不回滾）
- 不在本 change 擴 golden set 到 n=30+（並行另開 change）
- 不在本 change 加 reranker / cross-encoder（另起 change）

## Capabilities

### New Capabilities

（none）

### Modified Capabilities

- `rag-query`: retrieval 預設行為改成「不走 two-layer routing，直接掃全 show」；保留 env flag 反向開回 routing
- `rag-eval-dataset`: golden set 限定 human-curated 來源；LLM-auto 不直接進主 dataset（需 staging + 二次審核）

## Impact

- 受影響規格：`rag-query`、`rag-eval-dataset`
- 受影響程式：
  - 修改：backend/app/services/rag.py（`_should_skip_routing` default 翻向）
  - 修改：backend/eval/datasets/this-not-that-cool.json（固化 audit 結果）
  - 修改：docs/case-studies/r32-routing-regression-2026-05-11.md（補 follow-up note）
  - 修改：Zeabur backend service env `ENABLE_TWO_LAYER_ROUTING=false`（運維側設定，非 repo 檔）
  - 新增：（無）
  - 移除：（無，routing code 保留作為未來改進基礎）
- API 行為：`/shows/{show_id}/search` 與 `/shows/{show_id}/query` 對相同 query 回的 top-K 可能改變；description retrieval 的 lexical 信號更能發揮
- Latency：P95 預期略升（需查全 show 不只 top-10 episode），會在 success criteria 中設上限
- 相依：本 change archive 後會回頭把 `r3-4-embedding-model-swap` 一起 archive — r3-4 design.md D4 gate 條件在 follow-up note 重新詮釋（v2-large embedding 維持，因 routing 才是主因，embedding swap 不算失敗）
