## Context

Voyage rerank-2.5 已 ship（archive `2026-05-27-retrieval-rerank-via-voyage`，PARTIAL）。第二輪 eval 數據：

| 題 | baseline | voyage | delta |
|---|---:|---:|---:|
| b20 chunk_recall | 0.000 | 0.250 | ⬆ |
| b21 chunk_recall | 0.400 | 0.600 | ⬆ |
| b23 chunk_recall | 0.333 | 0.000 | ⬇⬇ |
| b22 factual | 0.65 | 0.30 | ⬇⬇ |
| b23 factual | 0.80 | 0.40 | ⬇⬇ |

兩條候選假說（rerank-2.5 跨集 signal 弱 / agent routing 干擾）目前都只是推測。前 session 已踩過「沒驗證 pipeline 階段 I/O 就推結論」的雷（_AGENTIC_SEARCH_TOOLS 漏 prefilter tool latent bug 被 Voyage eval 才暴露，原 chunk-recovery 的「0.244 持平」結論因此 contaminated）。本 change 紀律：**每階段 I/O 對 expected 驗證一次再動 code**。

## Goals

- 對 b22 / b23 確認 root cause 在 chat agent → search_with_topic_prefilter → voyage_rerank → citation collector → grader 整條 pipeline 的哪一階段
- root cause 明確後 targeted fix
- 最終 8 題 subset 重跑：cross_episode chunk_recall ≥ 0.40 + factual ≥ 0.80

## Non-Goals

- 不預設 root cause（不假設 doc payload / agent routing / voyage 弱 / grader bug 中任一單一原因）
- 不換 rerank provider / model
- 不調 N
- 不動 b20 retrieval miss
- 不擴大 dataset

## Decisions

### Pipeline I/O audit before any code change

Stage A 是純診斷工具 + case study，**不寫 application code**。對 b22 / b23（外加 b21 當 control / sanity）跑 9 階段 I/O dump：

1. **Grader sanity check (control)**：對 b21 已知結果（chunk_recall=0.6）手算 GT vs citations 對應關係，確認 `chunk_recall_grouped` 算分公式跟 codebase 一致 — 排除 grader 本身有 bug 把問題藏住
2. **Agent topic extraction**：dump LLM 抽出的 `topic` 字串（從 `tool_calls[].args.topic`）— b22 / b23 各抽什麼？對「家常味跨集」/ b22「listing 型」是否合理？
3. **`find_episodes_by_topic` output**：用該 topic call episode_finders，看 candidate UUIDs — b23 兩個 GT episodes（`8b3d4c1d` + `cb96f6f8`）是否都在 candidate set 內？
4. **`retrieve_hybrid(k=30)` pool composition**：reuse `POST /admin/diagnose/prefilter-rank`（已存在）拿 top-30 list — GT chunks 在 pool 第幾名？跨集還是只在 1 集？
5. **Voyage doc payload bytes**：實際送 voyage 的 documents 陣列 — `len(documents)`、`[len(d) for d in documents]`、前 3 個 doc 完整字串。確認是否如預期 = 純 `chunk.text`（目前 `text_only` 路徑）
6. **Voyage response raw**：voyage rerank 回傳的 `resp.results` 陣列原始 dump（code 以 `getattr(resp, "results")` 取用，每個 `r` 有 `.index` / `.relevance_score`，見 `backend/app/services/rag_rerank.py:241-250`）— 每個 `(index, relevance_score)` 列出。索引範圍 ∈ [0, 30)？relevance 分佈長怎樣？
7. **Index → chunks mapping**：voyage 回 index `i` 對應的 chunks[i] 是不是原 retrieve_hybrid pool 第 i 個？對 b23 跨集情境特別驗證（chunks 在 pool 內順序是否被 dedup / re-sort 過影響 mapping）
8. **`_collect_agentic_citations` output**：collector 拿 `tc.result_full` 解開後 → sort → top-5。GT chunks 在 collector 輸出內嗎？
9. **Grader 看的 citations**：eval runner 傳給 grader 的 citations 陣列跟 collector 輸出一致？

每階段對比「expected」（依設計推測）vs「actual」（實際 dump）vs「結論（match / drift / unknown）」三欄，落地 `docs/case-studies/voyage-rerank-pipeline-audit-2026-05-27.md`。

**Why audit instead of trust**：前案例的 citation collector 漏 prefilter tool bug 是「dev 階段所有 unit test 都過、tool_calls 在 debug_trace 看也都正確、smoke 對 b21 拿到 3/5 GT chunks 在 top-5、但 eval grader 卻報 must_hits=0」 — 沒走 audit、直接信 metric，就會錯結論。本次必須擋掉這條路。

**資料來源限制（2026-06-04 implementation 階段發現，user 拍板 option A）**：prod query trace 的 `result_full` 只帶 `search_with_topic_prefilter` 的輸出 envelope（`chunks` / `prefilter_episode_count` / `prefilter_source` / `fallback_to_full_pool` / `rerank_applied` / `rerank_input_count`），**不暴露 voyage 內部**（pre-rerank 輸入池實際 chunks、raw response 的 index/relevance_score、index→chunks mapping）—— 這些是 `voyage_rerank()` 內部、回傳只有 `(chunks_top_k, applied)`。為嚴守 Stage A「不動 application code」，採**黑箱夾擊法**：
- Stage 5 = `rerank_input_count` + `rerank_applied`（doc 為純 text，靜態事實見 `rag_rerank.py:226`）
- Stage 6-7 = `verdict=unknown` / `actual=None`（prod 不暴露；design error mode 已預先授權）
- root cause 判別不靠 voyage 內部 dump，改靠 **stage 4 in（GT 是否在 retrieve_hybrid top-30 池）↔ stage 8 out（GT 是否在 response.citations）夾擊** + `fallback_to_full_pool`（b22「沒進 voyage path」假說可直接證）。stage 7 off-by-one / dedup 風險改靠 `rag_rerank.py:249-256` 靜態 review 補（idx 已 bounds-check + dedup，風險低）。

### Diagnostic tool design

`backend/scripts/audit_voyage_pipeline.py`：

- argparse `--item-ids b22,b23,b21 --backend <url> --out <path>`
- 對每題：refresh session → POST `/shows/{id}/query?debug_trace=true` → 從 response trace 抽 stage 2-7 資料、call admin endpoint 拿 stage 4 資料、用 dataset 對照 stage 1 + 9
- 輸出單一 JSON file with per-item per-stage I/O，外加 markdown table 印 stdout

### Stage B routing — decide after Stage A

Stage B 動作集合（依 Stage A 結論其中一條）：

| Stage A 結論 | Stage B fix |
|---|---|
| Doc payload 對應，voyage rank 結果跟 GT 對應好但 grader 漏看 | 修 grader / collector / chunks dict shape |
| Doc payload 對應，voyage rank 但實際 ranking 把 GT 推後（rerank signal 弱）| Doc payload ablation（title / before-after enrichment）|
| topic 抽錯 → candidate episodes 不對 | 修 agent topic extraction prompt 或 episode_finder |
| candidate 對但 retrieve_hybrid 漏 GT 在 top-30 內 | 屬 b20-style retrieval miss，併入 `cross-episode-b20-retrieval-investigation` 另立 |
| b22 走 listing path 沒進 voyage，factual 退步是別處 | 修 agent routing prompt 或 list_episodes tool |
| 多個階段都 drift | 拆開 propose 多個 follow-up changes |

Stage B 範圍由 Stage A 結論確認後**在本 change 內**直接更新 spec / design / tasks 再執行。

### Stage B — confirmed scope (2026-06-04, user 拍板「b23 收斂 prefilter + b22 拆出」)

Stage A（case study `voyage-rerank-pipeline-audit-2026-05-27.md`）證實分類 **(d)**：

- **b23 root cause = topic prefilter over-match**：topic「迪拉 Leo王」jieba 切成 `迪拉|Leo|王`
  的 OR tsquery，host token「迪拉」幾乎每集都中 → `find_episodes_by_topic_with_source`
  回傳 **64 集**（`_TOPIC_SQL` 按 `published_at DESC` 無 LIMIT）。agent 真實 retrieve_hybrid
  在 64 集寬池取 top-30，把實際 GT（EP107 Leo王 初遇，ideal 單集池 rank 3/30）稀釋出局。
  **voyage 至多次因**（stage 6-7 不暴露，無法 100% 歸因 voyage）。
- **b22 root cause = routing + distributed-evidence retrieval miss**：agent 走
  `get_show_overview`/`search_across_episodes`，**完全不進 voyage path**；7/7 either-GT 連
  ideal 池都 miss。**與本 change（voyage/prefilter）無關 → 拆成獨立 follow-up change，不在本 change 修。**

**本 change Stage B 只做 b23 prefilter-breadth 收斂**：把 `_TOPIC_SQL` 從
「`ORDER BY published_at DESC` 無 LIMIT」改成「按 topic 相關度（ts_rank）排序 + LIMIT N 集」，
讓最相關的集排前面、截斷長尾低相關集，避免 host-token 把候選撐到數十集稀釋 cross-episode GT。

## Implementation Contract

**Observable behavior**：

- Stage A 結束時 `docs/case-studies/voyage-rerank-pipeline-audit-2026-05-27.md` 存在且每階段有「expected / actual / 結論」三欄
- Stage A 寫完之前**不修任何 application code**（diagnostic tool + case study 例外）
- Stage B 動作由 Stage A 結論決定；最終 8 題 subset 重跑 gate（cross_episode chunk_recall ≥ 0.40 + factual ≥ 0.80）有明確 PASS / FAIL

**Interface**：

- `backend/scripts/audit_voyage_pipeline.py` argparse 接 `--item-ids` / `--backend` / `--out` / `--session-cookie-file` / `--me-json`
- 輸出 JSON shape：`{"items": [{"item_id", "stages": [{"stage": 1-9, "name", "expected", "actual", "verdict": "match|drift|unknown"}], "overall_verdict": "..."}]}`
- **Stage B 介面（2026-06-04 confirmed）**：`episode_finders.find_episodes_by_topic_with_source`
  的 `_TOPIC_SQL` 改為按 `ts_rank` 相關度排序 + `LIMIT :max_eps`：
  - relevance = `GREATEST(ts_rank(title_tsvector, q), COALESCE(max(ts_rank over matching description chunks), 0))`，
    `ORDER BY relevance DESC, published_at DESC NULLS LAST LIMIT :max_eps`
  - 新增 setting `topic_prefilter_max_episodes: int`（default 由 re-audit 證據定，起手 10），
    env 可覆寫；設 `0` 或負值 = 不限制（rollback 行為，回到舊「無 LIMIT」語意）
  - guest-dispatch union（`merged` 路徑）的 cap：對 topic_eps 套 LIMIT，guest_eps 仍全帶
    （guest 是高精度訊號，不稀釋）
  - **N 不用猜**：default 值由 re-audit b23（EP107 GT 是否回到 citations）+ b20/b21（不退步）的證據確定

**Stage B acceptance（取代「待 Stage A 結論」）**：
- 改 `_TOPIC_SQL` 後 re-run audit script，b23 stage 3 candidate count 從 64 大幅下降、
  且 b23 stage 8 gt_matched ≥ 1（GT 回到 citations）；b20/b21 stage 8 不退步
- 8 題 subset eval gate：cross_episode chunk_recall mean ≥ 0.40 + factual mean ≥ 0.80
- b22 不在本 change 修；拆出獨立 follow-up（在 Open Questions / proposal 記指針）

**Error / failure modes**：

- Audit script 任何階段抓不到資料 → stage `verdict=unknown` + `actual=None`，不 crash；繼續抓後續階段
- 如 session 過期 → 印明確 error 中斷
- Stage A 跑完發現 root cause 是「Voyage 真的對中文 long context 弱、ablation 也救不了」→ Stage B = revert + negative finding，本 change archive 為 NEGATIVE

**Acceptance criteria**：

- Audit script 跑得起來，b22 / b23 / b21 三題 9 階段 I/O dump 落地
- case study 含 27 列（3 題 × 9 階段）對比，每列有 expected / actual / 結論
- Stage A 結論段明確指出 root cause（單一原因或多原因）
- Stage B fix 落地後重跑 eval，gate 過 → archive；不過 → negative finding 寫完

**In scope**：

- Diagnostic script `audit_voyage_pipeline.py`
- Stage A case study
- Stage B fix（範圍由 Stage A 結論決定）
- 最終 eval

**Out of scope**：

- 預設 root cause 是 doc payload
- 預設 root cause 是 agent routing
- Voyage provider / model 變動
- N 變動
- 其他 retrieval tool
- b20 retrieval miss
- multi-turn ordinal_resolution

## Risks / Trade-offs

- **Risk**：Stage A audit 跑完仍找不到明顯 drift（每階段都符合預期但 grader 還是給 0）→ 結論變「rerank 對這 domain 就是不適合」，Stage B = revert + negative finding
- **Risk**：Stage A 找到的 root cause 牽涉多個階段，Stage B 範圍暴增 → 拆出多個 follow-up change，本 change archive 為 partial
- **Risk**：audit script 對 admin endpoint / prod debug_trace 的依賴可能因 session timeout 跑到一半中斷 → 加 checkpoint，個別 item 失敗不 block 全 run
- **Trade-off**：Stage A 純診斷不產 metric 進步；但避免在錯誤假說上花更多時間。前 change 的 citation bug 就是因為跳過 audit 才繞了一大圈

## Migration Plan

Stage A：

1. 寫 audit script
2. Refresh e2e session
3. 對 b21（control）+ b22 + b23 跑 audit
4. 落地 case study

Stage B（依 Stage A）：

1. 更新 design / spec / tasks 補上 fix 範圍
2. 寫 application code
3. Local test + push deploy
4. 跑最終 eval

**Rollback**：Stage A 沒 code 改動 → 無需 rollback。Stage B 視 fix 範圍而定，通常 1 commit revert。

## Open Questions

- 對 b22 預期會看到 voyage path 沒被走過 — 如果這成立，b22 factual 退步真因不在 voyage 而是別處（譬如 list_episodes 行為變化或 agent SYSTEM_PROMPT side effect）。Stage A 結論段要明確處理 b22 vs b23 是不是同一個 root cause
- audit script 是否需要 mock voyage / 直接打 prod？打 prod 較真實但占 quota；mock 較快但漏 prod-only bug。傾向先打 prod（成本 trivial）
- Stage A 結論寫完是否要 stop-the-line 找 user 拍板 Stage B 範圍？傾向 yes，避免 Stage B 直接 scope creep
