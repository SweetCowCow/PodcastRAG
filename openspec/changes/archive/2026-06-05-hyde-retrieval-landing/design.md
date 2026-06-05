## Context

lexical-mismatch-query-rewrite-bakeoff（archived 2026-06-05）對 prod 跑完四 arm bake-off，HyDE 為量化勝者（標靶平均 must prefilter-rank 26.8 → 15.7、calibration 無退步）。bake-off endpoint `diagnose_lexical_bakeoff.py` 用 `episode_id_filter=prefilter_eps`（由 GT 推導的 episode）**繞過 `route_episodes`**，因此 HyDE 只在「選集已正確、量 episode 內 chunk 召回」這一層被驗證過。

線上有三個 semantic retrieve 點，每處 `query_embedding` 同時餵 `route_episodes`（選集路由）與 `rag.retrieve_hybrid`（chunk 召回）：
- `public_search_show`（公開語意搜尋）
- `query_show` mode=="search"（登入語意搜尋）
- `query_show` chat rule-based path（用 history-rewritten question 的 embedding）

第四條 agentic path（`run_agent`，flag `enable_agentic_chat` 預設 on）自行組裝 tool query，不在本 change 範圍。

## Goals / Non-Goals

**Goals:**

- 把 HyDE 落到上述三個 semantic retrieve 點的 **chunk 召回層**，行為與 bake-off 的 hyde arm 一致：semantic 向量改用「假設答案文本」的 embedding，lexical（BM25）維持原 question。
- 走 env flag `enable_hyde_retrieval`，預設 `False`。flag off 時三個入口行為與現況**位元等價**（embed 同一個原 question、無額外 LLM call）。
- 提供 flag on/off A/B 量測 + 擴樣 golden set，產報告供 Jacky 拍板是否 flip 預設。

**Non-Goals:**

- 不 flip 預設值（維持 off）。
- 不接 agentic chat path。
- 不改 `route_episodes` / `find_episodes_by_topic` 選集層；不改 `retrieve_hybrid` 召回邏輯。

## Decisions

### D1: HyDE 向量只餵 chunk 召回，routing 維持原 question 向量

`route_episodes` 在 bake-off 中被 `episode_id_filter` 繞過、HyDE 對選集路由是**未測領域**。若把 HyDE 向量也餵 routing，可能把查詢路由到錯誤 episode（風險未量化）。故落地時：
- `route_episodes(db, show_id, base_vec)` —— 一律用原 question 的 embedding `base_vec`。
- `retrieve_hybrid(..., query_embedding=semantic_vec, question=<原 question 或 rewritten>)` —— `semantic_vec` 為 flag-gated：flag off = `base_vec`；flag on = HyDE 文本的 embedding。
- 後果：flag on 時每查需 **2 次 embed**（原 question 給 routing + HyDE 文本給召回）+ **1 次 LLM**（生 HyDE 文本）。flag off 時維持 1 次 embed、0 次 LLM。

### D2: helper 介面集中於 backend/app/services/hyde_retrieval.py

提供單一進入點，讓三個呼叫端共用、避免邏輯散落：

```
async def resolve_semantic_embedding(
    db: AsyncSession,
    question: str,           # 已是 routing / lexical 要用的那個 question（chat path 傳 rewritten）
    base_vec: list[float],   # 呼叫端已算好的原 question embedding（routing 也用它）
    embedding_cfg: StepConfig,
) -> HydeResult
```

`HydeResult` 含 `semantic_vec: list[float]`、`used_hyde: bool`、`hyde_text: str | None`、`extra_llm_calls: int`。flag off 直接回 `semantic_vec=base_vec, used_hyde=False`。HyDE 的 system prompt 與 control 邏輯沿用 bake-off 的 `_HYDE_SYSTEM`（自 `lexical_bakeoff_arms.py` 抽用或複製常數，註明來源）。

### D3: 失敗一律 fail-open 回退原向量

HyDE 生成走 LLM，任何失敗（step 未設定、client ctor、LLM error、空回覆）一律回退 `base_vec` 並記 log warning，retrieve 照常用原 question 向量跑。沿用 `_extract_entities_fail_open` 的 fail-open 模式——retrieve path 不得因 HyDE 失敗而 5xx。

### D4: chat path 的 question 用 rewritten

`query_show` chat rule-based path 既有邏輯先用 history 把 question rewrite 成 `rewritten`，再 embed。HyDE 落地時 `resolve_semantic_embedding` 的 `question` 與 `base_vec` 都以 `rewritten` 為準（HyDE 文本據 rewritten 生成），與既有 routing/lexical 對齊。

## Implementation Contract

- **Behavior**：`enable_hyde_retrieval=False`（預設）時，三個入口的回傳與現況完全一致。設為 `True` 時，三個入口的 chunk 召回改用 HyDE 文本向量、選集路由與 BM25 lexical 不變；每次查詢多一次 LLM 生成（觀測得到延遲增加約 1.5–2s）。
- **Interface**：新增 `app.services.hyde_retrieval.resolve_semantic_embedding(...) -> HydeResult`（簽名見 D2）；新增 `Settings.enable_hyde_retrieval: bool = False`（`config.py`，沿用 `enable_agentic_chat` 慣例）。
- **Failure modes**：HyDE 生成任一失敗 → 回退 `base_vec`、`used_hyde=False`、log warning、不拋例外。flag off → 完全不進 HyDE 程式碼路徑、不建 LLM client。
- **Acceptance criteria**：
  - `backend/tests/test_hyde_retrieval.py`：(a) flag off 時 `resolve_semantic_embedding` 回 `base_vec` 且 `extra_llm_calls==0`；(b) flag on 且 LLM 正常時回 HyDE 文本向量、`used_hyde==True`；(c) flag on 但 LLM 拋錯時 fail-open 回 `base_vec`、`used_hyde==False`。
  - flag off 跑既有 query 測試全綠（行為等價回歸）。
  - `backend/scripts/hyde_ab/run.py` 對 prod 跑 flag on/off A/B（依 reference_prod_eval_session 用 playwright-state session、開跑前 curl /me 驗 200），產出 `docs/case-studies/hyde-landing-ab-2026-06-05.md`，含擴樣題集的 must prefilter-rank on vs off 對照 + calibration 退步檢查 + mixed 評分視角。
- **Scope boundaries**：
  - In scope：`config.py` flag、`hyde_retrieval.py` helper、`query.py` 三個 semantic 入口接 helper、擴樣 golden set、A/B harness + 報告。
  - Out of scope：agentic path、選集路由邏輯、`retrieve_hybrid` 召回邏輯、flip 預設值。

## Risks / Trade-offs

- **小樣本外推風險**：bake-off 僅 b20/b23 兩案。緩解＝本 change 不 flip 預設、先擴樣到 10+ 詞彙失配題跑 A/B 才由 Jacky 拍板。
- **b23 不一定解得到**：b23 真正卡點可能在 `find_episodes_by_topic` 選集層（只比 title/description），HyDE 接在 chunk 層。A/B 報告須對 b23 分別標示「選集層是否本來就召得到」，避免把選集層 miss 誤記為 HyDE 無效。
- **延遲成本**：flag on 時每查多 1 次 LLM（約 1.5–2s）+ 多 1 次 embed。屬落地層 human 判斷（召回收益 vs 延遲），由 A/B 報告呈現、不由本 change 自動決定。
- **生成變異**：HyDE 文本由 LLM 生成，已固定 prompt + temperature=0，仍可能有變異；A/B 報告須記錄 model 與 HyDE 文本樣本。
