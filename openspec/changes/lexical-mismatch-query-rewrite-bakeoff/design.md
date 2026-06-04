## Context

EQ3a 診斷把 b20、b23 兩個 cross-episode golden case 的失敗歸到同一根因：query 表面詞與 ground-truth chunk 幾乎零重疊的 chunk-level 詞彙/語意失配。現有 retrieval pipeline（topic-prefilter → ts_rank lexical + embedding hybrid → voyage rerank）對這類 query 召不回標靶 chunk（b20 @1719 prefilter-rank 78），且已排除 voyage 弱與 GT 髒兩個假設（GT 全 human-verified-2026-06-04）。

修這類失配的候選手段（query-expansion、HyDE、multi-vector）互斥、成本與風險不同；2026-05-28 盲押 lexical-fallback 導致整條 change 退步全廢。本 change 用受控離線 bake-off 在落地前量測，避免重蹈覆轍。

架構約束（apply 階段對源碼驗證後確認）：`embed_texts` 需 db 裡的 step config、`retrieve_hybrid` 需 db session 連 prod DB，arm 的「改寫→embed→retrieve」這段**必須在 prod backend 內執行**，本機 HTTP script 碰不到 prod DB。既有 `/admin/diagnose/prefilter-rank`（`diagnose_prefilter.py:146/169/174`）寫死從 dataset 取原 query、自己 embed 原 question，**無法注入 arm 改寫**。因此本 change 新增一個 sibling admin diagnose endpoint 承載 bake-off，arm 改寫邏輯放 backend service 層，harness 仍走 HTTP（復用 `audit_voyage_pipeline.py` 的 prod session 樣板）、不接線上 query API。

## Goals / Non-Goals

**Goals:**

- 在固定測試案例上並排量測至少 4 個 arm（control / query-expansion / hyde / multi-vector），用統一 metric 判出對詞彙失配最有效的手段。
- 同步量測手段的成本（額外 LLM call 數、延遲），讓「召回收益 vs 成本」可被人工權衡。
- 用 calibration 防退步集確保改寫手段不傷害原本就召得回的 query。
- 產出可複查的 bake-off 報告 + 明確勝者判定 + stop-the-line 落地閘門。

**Non-Goals:**

- 不把勝者落地到 prod retrieval path（落地是後續獨立 change，需 Jacky 拍板）。
- 不碰 b22 的 routing + distributed-evidence 問題（b22 獨立 change）。
- 不碰 b23 的 narrative/topic-prefilter 解法軸（b23 獨立 change；b23 在此僅作為 bake-off 測試案例，驗詞彙手段對 narrative 題有沒有效）。
- 不修改 golden set GT、不改線上 `rag-query` 查詢契約（`/shows/{id}/query`）。新增的 `/admin/diagnose/lexical-bakeoff` 是 admin-only 離線診斷 endpoint，不屬線上查詢路徑；既有 `/admin/diagnose/prefilter-rank` 行為亦不更動。

## Decisions

### Arm 集固定為 control、query-expansion、hyde、multi-vector

四個 arm 共用同一條下游 retrieve 路徑與同一份候選池設定，唯一變因是「query 進 retrieve 前怎麼被改寫/擴充」：

- `control`：原 query 直接進 retrieve（現狀基準線）。
- `query-expansion`：用 LLM 對原 query 產生同義/相關詞擴充，OR 進 lexical query 並保留原 embedding query。
- `hyde`：用 LLM 對原 query 生成一段假設性答案文本，對該文本取 embedding 當檢索向量（原 query 仍保留 lexical）。
- `multi-vector`：對原 query 拆成多個子查詢各取 embedding，與 chunk embedding 取 max-similarity 聚合。

選這四個是因為它們覆蓋「擴 lexical 面」（expansion）、「換 embedding 來源」（hyde）、「多向量聚合」（multi-vector）三條正交路線，control 提供退步偵測基準。其他手段（如重新 chunking、換 embedding model）屬不同 change 範疇，排除。

### 測試案例固定為 b20 + b23 + calibration 防退步集

主標靶 = b20（must @1719+@1993）、b23（must @1766/@1819/@1847/@1866），皆 human-verified-2026-06-04。另納入 calibration 防退步集（沿用 eval calibration_8）：這組 query 原本 control 就召得回，用來確認改寫手段不會把原本對的 query 弄壞。只測 2 個標靶案例是已知的小樣本限制，報告須明標，結論不外推到未測題型。

### 主 metric = 標靶 chunk prefilter-rank，副 metric = chunk_recall@must，並列成本欄

主 metric 用「標靶 chunk 在候選池的 prefilter-rank」而非只看最終 chunk_recall，因為它能區分「標靶根本沒進候選池」與「進了但被 rerank 壓下去」兩種失敗，定位力更強。副 metric chunk_recall@must 對齊 eval gate 語言。每個 cell 並列成本（額外 LLM call 數、平均延遲），供落地權衡。

### 新增 admin bake-off endpoint，arm 改寫在 backend service，harness 走 HTTP orchestrate

既有 `/admin/diagnose/prefilter-rank` 封閉（寫死 dataset 原 query、無 override），無法承載 arm 注入。本 change 新增 sibling endpoint `POST /admin/diagnose/lexical-bakeoff`：接 `{arm, items, top_n, show_id}`，內部對每個 item 依 arm 跑「改寫 → embed → `retrieve_hybrid` → 比對 GT chunk 得 prefilter-rank」，回每 item 的 `gt_ranks` + cost（額外 LLM call 數、延遲）。arm 改寫邏輯（expansion/HyDE/multi-vector）放 backend service 層（因需 LLM client + `embed_texts` + db session）；`control` arm 行為與既有 endpoint 等價。harness（`backend/scripts/lexical_bakeoff/`）只負責 orchestrate（對每 arm×case 打 endpoint）+ 收 metric + 組報告，復用 `audit_voyage_pipeline.py` 的 prod session 讀取樣板。整條唯讀、不寫表、不走線上 `/shows/{id}/query`；對 prod 跑前依 reference_prod_eval_session 先 curl `/me` 驗 200。

### 評分視角 = mixed（量化 metric 判 arm 優劣，human 視角判落地）

量化層：哪個 arm 把標靶 prefilter-rank 拉最前、chunk_recall 最高，是純數據判定。落地層：query-expansion / hyde 每 query 多一次 LLM call（成本+延遲），是否值得落地是 human 權衡，不能只看召回數字。design 明寫此視角，避免「召回贏就落地」的 AI-delegate 偏誤（依 feedback_bakeoff_perspective_calibration）。

### stop-the-line：勝者不自動落地，等 Jacky 拍板

bake-off 報告產出後流程停下，不自動 merge 任何 arm 進 prod retrieve path。由 Jacky 看報告後拍板：是否落地、落地哪個 arm、由哪條後續 change 落地。harness 與 arm 實作留存供落地 change 復用。

## Implementation Contract

- **Behavior**：執行一個 bake-off runner 命令，對固定案例集 × 4 個 arm 跑離線檢索量測，輸出每 (arm, case) 的標靶 prefilter-rank、chunk_recall@must、額外 LLM call 數與平均延遲，並印出勝者判定與 calibration 退步檢查結果。
- **Interface / 資料形態**：
  - 新增 admin endpoint `POST /admin/diagnose/lexical-bakeoff`，request `{arm: str, items: list[str], top_n: int, show_id: str}`，response 沿用既有 prefilter-rank 形狀並每 item 增補 `cost`（`{extra_llm_calls: int, latency_ms: float}`）與 `rewrite_debug`（arm 改寫後的 lexical query / HyDE 文本 / 子查詢，供報告記錄）。
  - 每個 arm 在 backend service 層實作統一介面：輸入 `(question, db, embed_step)` → 輸出 retrieve 所需的 `(lexical_question, embedding_vectors, extra_llm_calls)`，由 endpoint 統一餵進 `rag.retrieve_hybrid`（`control` 等價於原 question 直送）。
  - harness runner CLI 接受參數指定 arm 子集、case 子集、目標 backend（prod 或 local）。
  - 輸出兩份：機器可讀 JSON 結果（每 cell 一筆，含 metric + cost + rewrite_debug）落 `backend/scripts/lexical_bakeoff/results/`；人讀 markdown 報告（arm × case 矩陣 + 勝者 + 成本 + 小樣本免責聲明）落 `docs/case-studies/`。
- **Failure modes**：單一 (arm, case) 量測拋錯 → 該 cell 標 `ERROR` 並續跑其餘 cell，不整批中斷；目標 backend 連線/驗證失敗（如 prod session 過期）→ fail loud 並中止（不可靜默產半套報告）；endpoint 端單一 item 改寫/檢索拋錯 → 該 item 回 `{error: ...}`（比照既有 endpoint 的 per-item error 慣例）不讓整批 500。
- **Acceptance criteria**：
  - 報告含全部 (arm, case) cell，無遺漏、無 placeholder。
  - 勝者判定附量化依據（prefilter-rank / chunk_recall 數字），非主觀敘述。
  - calibration 防退步集對每個非 control arm 都有「未退步 / 退步」結論。
  - 報告含評分視角段落（量化 vs 落地）與小樣本限制聲明。
- **Scope boundaries**：in scope = 新增 admin diagnose bake-off endpoint、backend service 層 4 arm 改寫實作、harness orchestration script、跑量測、產報告與結論。out of scope = 落地任一 arm 到 prod retrieve path、修改既有 `/admin/diagnose/prefilter-rank` 行為、b22 routing、b23 narrative 解法、改 GT、改線上 `/shows/{id}/query` 查詢路徑。

## Risks / Trade-offs

- [只測 2 個標靶案例，結論可能過擬合] → 納入 calibration 防退步集 + 報告明標小樣本，結論限定「對這兩案的詞彙失配」不外推。
- [HyDE / expansion 用 LLM 生成，輸出不可重現] → 固定 prompt、temperature=0、記錄 model 與版本於結果 JSON。
- [query 改寫增加延遲與成本] → 每 cell 並列成本欄，落地決策由 human 視角納入權衡。
- [對 prod 資料跑，session 過期或污染] → 唯讀檢索、開跑前 curl `/me` 驗 200、不寫入任何表。
- [multi-vector 子查詢拆法影響結果] → 子查詢拆法與聚合方式記於結果 JSON，列為報告中的已知變因。

## Migration Plan

純離線 bake-off，無 prod 部署、無 schema 變更、無 rollback 需求（不碰線上路徑）。harness 與 arm 程式碼留存於 repo 供後續落地 change 復用。

## Open Questions

- multi-vector arm 的子查詢拆法：預設用 LLM 把原 query 拆成 2–3 個面向子查詢各取 embedding、retrieve 時取 max-sim 聚合；apply 階段若實作成本過高，可退化為「原 query + 一個 LLM 改寫 query」雙向量。最終採法須記於報告。
- 勝者門檻的硬數字（prefilter-rank 要進前幾、chunk_recall 要達多少）在跑出 control 基準線後於報告中定錨，不預設絕對值（避免憑空猜數字）。
