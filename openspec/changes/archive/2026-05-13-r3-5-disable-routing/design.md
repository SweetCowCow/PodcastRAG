## Context

R3.x milestone 追的是 RAG retrieval quality（episode-level Recall@5）。前置 changes：

- `r3-2-retrieval-fix`（R3.2 baseline 卡 0.1548，動 env flag 沒拉動）
- `r3-2-two-layer-topic-seg`（topic 段切割）
- `r3-4-embedding-model-swap`（cutover 到 `text-embedding-3-large` + dual-write、prod 仍跑著）

2026-05-11 觀察到 R3.2 baseline 從 R3.1 23.8% 退到 15.5%，當下 hotfix 加上 `route_episodes` two-layer routing（`backend/app/services/rag.py:_should_skip_routing` 預設 `ENABLE_TWO_LAYER_ROUTING=true`），把 R3.2 提到「0.1548」收尾。

2026-05-13 audit：

1. 移出 36 個 `thisno-core-*` LLM-auto 生成壞題（驗證樣本 4/4 全壞，常見 pattern：單關鍵字觸發深度問題、anchor 對不上 question；cross-episode anchor 第二個 episode 完全跟 question 無關）
2. 補 q05 EP66 anchor（dbeecd79，「英國 ego 藝人」段落）
3. 拆 pre-audit 48-item eval 為 human (q01-q10) vs LLM-auto 子集：
   - Human-curated R@5 = **0.0625** (n=8 retrieval items)
   - LLM-auto R@5 = **0.2598** (n=34)
   - 「fact +95% (0.18→0.353)」幾乎全來自 LLM-auto 子集；human fact = 0.0 / 3
4. 三條 spike 釐清 root cause（見 Decisions 段）：
   - B1: query 帶書名「《這又沒有很屌》」時 EP1 hits 從 3/5 掉到 0/5
   - B2: routing top-10 在帶書名 query 時 **EP1 完全不在 top-10**
   - B3: 跳 routing 跑全 show retrieve_hybrid，10 題 Recall@5 = **0.4375**

當前 prod 狀態：`ai_steps.embedding.model = text-embedding-3-large`、`RAG_USE_EMBEDDING_V2=true`、`ENABLE_TWO_LAYER_ROUTING` 未顯式設（用 code default `"true"`）。本 change 把 default 翻反 + prod env 顯式設 false。

Stakeholders：使用者（retrieval quality）、營運（Zeabur env 維護）、未來 reranker / agentic 設計（其他 R3.x changes 會在這個基礎上接續）。

## Goals / Non-Goals

### Goals
- 把 retrieval 主要瓶頸（routing 武斷擋掉答案 episode）解開
- 人類 query 上 Recall@5 從 0.0625 拉到 ≥ 0.40
- 把 golden set audit 結果（移壞題 + 補 anchor）固化成歷史紀錄、跟 routing 變更綁同一 archive
- 保留 routing code（不刪 `route_episodes` / `_ROUTE_EPISODES_SQL`），預留未來「routing 加 lexical 信號」改進路徑

### Non-Goals
- 不修 routing SQL 內邏輯（另開 r3.x change 處理「routing 加 lexical 信號」）
- 不動 embedding model（v3-large 維持）
- 不擴 golden set 規模（另開 r3.x change 處理 human-curated set 擴張到 n=30+）
- 不加 reranker / cross-encoder（另開 change）
- 不重寫 `_should_skip_routing` 的 jieba token 短 query 判斷（保留現有邏輯，只翻 env default）

## Decisions

### D1 — Default 翻向 vs 完全移除 routing code

**選翻向**：`ENABLE_TWO_LAYER_ROUTING` env 預設改 `"false"`，code path 保留。

理由：
- 未來可能修好 routing（加 lexical 信號變成 hybrid routing），保留 code 才能反手切回測試
- env flag 反手切回 routing 比重新加 code 便宜
- 保留 `route_episodes` 函式不會增加維護成本（沒人會誤呼叫，因 `_should_skip_routing` 看 env）

### D2 — Spike 三條診斷的具體資料

B1（query phrasing 對 q01「節目名是怎麼來的」的影響）：

| Query 寫法 | EP1 hit / top-5 |
|---|---|
| 「節目名是怎麼來的」 | 3 / 5 |
| 「節目名「這又沒有很屌」是怎麼來的？」 | **0 / 5** |
| 「迪拉怎麼幫節目取名」 | 1 / 5 |
| 「為什麼節目要叫這個名字」 | 2 / 5 |

B2（route_episodes top-10 for q01）：

| Query | EP1 在 routing top-10 |
|---|---|
| 「節目名是怎麼來的」 | rank 8 |
| 「節目名「這又沒有很屌」是怎麼來的？」 | **不在 top-10** |

B3（跳 routing 全 show retrieve_hybrid 跑 q01-q10）：

| 題目 | 有 routing R@5 | 跳 routing R@5 |
|---|---|---|
| q01 節目名由來 | 0 | **1.0** |
| q03 中老年開工觀 | 0 | 0 |
| q04 中老年錨點 | 0 | 0 |
| q05 UK Drill | 0.5 | 0.5 |
| q06 培姊長食譜 | 0 | 0 |
| q07 家常味定義 | 0 | **1.0** |
| q09 主持人陣容 | 1.0 | 0.5 |
| q10 安身之處跨集 | 0 | **0.5** |
| **Overall** | **0.0625** | **0.4375** |

### D3 — Latency 上限

跳 routing 後，每 query 要對全 show 的 description chunks + transcript chunks 跑 RRF。原本 routing top-10 把候選集縮小到 10 episodes 的 chunks（DESC chunks 3-6k、transcript chunks ~1k/episode），跳 routing 後查全部（DESC ~6k、transcript ~115k）。

實測 latency（spike 後 eval P95）：
- 跳 routing 後 10 題 P95 ≈ 2.7s（從 backend 內部直接呼叫，無 routing overhead）
- 走完整 pipeline（含 LLM rewrite + answer）P95 ≈ 3-4s（從前次 eval P95 ≈ 3.0s 推估）

Ship 條件：P95 latency ≤ 4500ms（容忍 50% 上升）。若超過 → 加 ivfflat probes 或 HNSW ef_search 調整、不回滾 routing。

### D4 — Ship gate

| 條件 | 動作 |
|---|---|
| Recall@5 (human q01-q10) ≥ 0.25 + P95 ≤ 4500ms | 必過 → ship |
| Recall@5 ≥ 0.40 | 加分 → 同步 archive `r3-4-embedding-model-swap`、補 r3-4 design.md D7 follow-up |
| Recall@5 < 0.25 或 P95 > 4500ms | FAIL → 不 ship、env 改回 true、本 change 不 archive、另開診斷 |

預測：B3 spike 顯示 0.4375 → 過加分 gate。

### D5 — golden set audit 變更綁入本 change 而非另起

理由：
- 兩者源自同一次 audit（5/13）
- audit 不固化進主 dataset，未來重 eval 拿到不一樣的 baseline
- audit 結果是 routing 判斷正確的前提（沒清掉 LLM-auto 假象就看不到 routing 是主犯）

### D6 — r3-4-embedding-model-swap 後續處理

本 change archive 時：
- r3-4 design.md 補 D7：「routing 才是 R3.2 ceiling 主因，embedding swap 仍維持（v3-large fact 類確有 gain，但不再作為 ship 唯一條件）」
- r3-4 archive 跟 r3-5 同一輪（pair archive）
- v2-large embedding 維持 prod、不回滾、不刪 v1 欄位（留作未來 bake-off baseline）

## Risks / Trade-offs

- **Latency 升高**：D3 已設上限 + 退路
- **Prod 行為變更，可能影響在用使用者**：本 change apply 後第一動就是觀察 P95 + 觀察 user-facing 行為。env flag 可隨時反向切回 → rollback 成本極低
- **Audit 樣本小（n=8）統計噪音**：B3 spike 數字（0.0625 vs 0.4375）在 n=8 信賴區間寬，但量級差異大（7x）足以下結論。後續 r3.x change 會擴 human golden set 到 n=30+ 收緊
- **不修 routing root cause（加 lexical）只關掉 routing**：留待未來 r3.x change；本 change 不背這個 scope。風險：未來某類 query 可能更適合 routing（例如 user 真的在問「某集」level 的問題），到時改 routing 比現在好做

## Migration Plan

1. Code 改：`backend/app/services/rag.py:_should_skip_routing()` 第 588 行附近的 `os.getenv("ENABLE_TWO_LAYER_ROUTING", "true")` 改成 default `"false"`
2. Prod env：`ENABLE_TWO_LAYER_ROUTING=false` 顯式設定（透過 `zeabur variable update`，非 create，避免 dump env）
3. Backend service redeploy
4. 跑 canary（q01 帶書名 query 對 prod /search 確認 EP1 進 top-5）
5. 跑 full eval（10 題 human-curated set）確認 Recall@5 ≥ 0.40
6. 跑 latency 觀察 30 分鐘（看 prod log P95）
7. Pass → 進 archive；FAIL → env 改回 true、apply 不算完成

回滾路徑：直接設 `ENABLE_TWO_LAYER_ROUTING=true` 即可（不需 redeploy code，env 變更會被 settings.py 在下次 process restart 後讀到 — 為快還是 redeploy 一次 backend service）。

## Open Questions

無。所有問題已在 spike 階段釐清。
