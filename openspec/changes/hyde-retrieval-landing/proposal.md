## Why

lexical-mismatch-query-rewrite-bakeoff（已 archive）對 prod 跑完四個 query 改寫 arm，量化勝者是 **HyDE**：標靶案例 b20/b23 的平均 must-chunk prefilter-rank 從 control 的 26.8 降到 15.7（b20 的 @1719 目標 chunk 從 rank 76 → 17），且對 calibration 防退步集無退步。其餘 arm 不是退步（query-expansion 退步 b01）就是更差且更慢（multi-vector）。

但該 bake-off 是離線量測、**未變更任何 prod retrieve path**，且只用 2 個標靶案例（報告自聲明不外推）。stop-the-line 決議由後續 change 落地，Jacky 拍板走「flag gate + 擴樣」路線：HyDE 走 env flag 預設關、先擴大樣本跑 A/B、數據站得住再 flip。本 change 即落地該決議。

## What Changes

- 新增 env flag `enable_hyde_retrieval`（預設 `False`），沿用 `enable_agentic_chat` 的 Settings flag 慣例。
- 新增 backend service helper：依 flag 決定 query 的 semantic 向量來源——flag off 時用原 question 的 embedding（行為與現況完全等價）；flag on 時先以固定 prompt + temperature=0 生一段假設答案文本、改用其 embedding。lexical（BM25）一律維持原 question。HyDE 的 prompt 與 control 等價邏輯沿用已 archive 的 `lexical_bakeoff_arms.py` 的 `_HYDE_SYSTEM`。
- 在 `query.py` 的三個 semantic retrieve 點接上該 helper：`public_search_show`、`query_show` 的 search mode、`query_show` 的 chat rule-based path。**`route_episodes`（選集路由）一律維持用原 question 的 embedding**——bake-off 用 `episode_id_filter` 繞過 routing、HyDE 對選集路由是未測領域，貿然替換會帶偏選集。
- 擴大驗證樣本：先從 `extended-multi-turn-40.json` 撈現有的詞彙失配題，不足 10 題再依 co-draft 紀律補寫，落入 golden set。
- 提供 flag on/off A/B 量測，產出報告供 Jacky 拍板是否把 flag 預設翻成 on（本 change 不自動 flip 預設值）。

## Non-Goals

- 不把 `enable_hyde_retrieval` 預設翻成 `True`——預設維持 off，flip 預設是擴樣 A/B 數據站得住後的另一次拍板。
- 不接 agentic chat path（`run_agent`）——agent 自行組裝 tool query，HyDE 注入語意與 rule-based path 不同，列為後續另議。
- 不改 `route_episodes` / `find_episodes_by_topic` 的選集路由邏輯。b23 真正卡點可能在 `find_episodes_by_topic` 只比對 title/description 的選集層（非 chunk retrieve 層），HyDE 接在 chunk 層、**不一定解得到 b23**；本 change 不處理選集層。
- 不改 `retrieve_hybrid` 本身的召回 / RRF / 候選池邏輯。

## Capabilities

### New Capabilities

- `hyde-retrieval`: flag-gated HyDE 查詢改寫，落在線上 semantic retrieve 的 chunk 召回層，預設關閉、可隨時翻回原行為。

### Modified Capabilities

(none)

## Impact

- Affected specs: hyde-retrieval（新增）
- Affected code:
  - New:
    - backend/app/services/hyde_retrieval.py
    - backend/tests/test_hyde_retrieval.py
    - backend/scripts/hyde_ab/run.py
    - docs/case-studies/hyde-landing-ab-2026-06-05.md
  - Modified:
    - backend/app/core/config.py
    - backend/app/api/query.py
    - backend/eval/datasets/extended-multi-turn-40.json
  - Removed: (none)
