## Context

承接 archived `lexical-stopword-filter-rca-deep-dive` case study（`docs/case-studies/lexical-stopword-filter-rca-deep-dive-2026-05-28.md`）結論：

- **真 root cause**：OR + ts_rank + RRF 架構下，query 層 token pruning 必然破壞 lexical bridge
- 87.5% 被砍 token 是 category (a) 真 stop-word — 不論怎麼選 list 都會破壞 bridge
- 5 個 audit GT probe 中 0/5 因為 stop-word filter 進入 lexical top-50
- aggregate 流失 -9.2 pp chunk_recall（+ -5 pp factual + -50 pp count_consistency）

**現況管線**（`backend/app/services/rag.py:528-603`）：

```
user query
  ├─ jieba 切詞 → " | ".join → :ts_query（OR-join）
  ├─ Lexical: tsvector @@ to_tsquery + ORDER BY ts_rank DESC LIMIT per_side=50
  └─ Semantic: embedding NN + LIMIT per_side=50
                    ↓
          RRF merge → LIMIT k
```

Chat agent dispatch（`backend/app/services/chat_agent.py` + SYSTEM_PROMPT）有 `search_within_episode` / `find_episode_by_ref` tool，但對 explicit EP-ref 題型常 fall back 到 `search_with_topic_prefilter` 或 retrieve_hybrid 全 show — sidestep 機會被浪費。

## Goals / Non-Goals

**Goals:**

- Layer A：lexical pipeline 用 corpus IDF 自動降權高頻 token，**保留 lexical bridge**（match=true 不變、ts_rank 順序變動讓 GT chunks 排名向上）
- Layer B：chat agent 看到 EP-ref → 強制走 `find_episode_by_ref` + `search_within_episode`，不依賴全 show retrieve
- chunk_recall_grouped 從 0.482 → ≥ 0.55、factual 不退步、hallucinated=0

**Non-Goals:**

- 不替 BM25（留 Phase 2 候選 C）
- 不動 chunking / embedding / RRF merge / per_side
- 不動 description / title pool 的 ts_rank（只動 transcript pool）
- 不重 backfill chunks（IDF 走新 freq table）

## Decisions

### Decision A1: IDF cache 走專屬 table、不走實時計算

**選**：建 `transcript_token_freq` table 存 token → df → idf，定期 refresh（譬如每天 cron / 新 episode ingest 後 incremental update）。

**拒**：每 query 實時跑 `SELECT COUNT(DISTINCT chunk_id) FROM transcript_chunks WHERE text_tsvector @@ to_tsquery(token)` 算 IDF。

**Rationale**：

- 實時計算每個 query token 跑一條 count 太慢，10 個 token = 10 個 count query
- df 一天內變動極小（新 episode 只佔 1/145+ 比例）— cache hit rate 接近 100%
- table 大小可控：每 show 約 50K-200K 唯一 token，落 PG 不到 100 MB

### Decision A2: IDF 注入 ranking 走 multi-bucket `ts_rank` 加權和（修訂版）

**修訂背景（2026-05-28 apply 階段發現）**：原方案寫 `ts_rank_cd(vector, weighted_query, 4)` 用 `token:A | token:D` 注入 IDF — 但 PG `tsquery` 的 weight label（`token:A`）實為「match filter」不是 ranking weight。`transcript_chunks.text_tsvector` 由 `to_tsvector('simple', text)` 產生、所有 position label 都是預設 `D`，所以 `token:A` 反而會把 token 從 match 排除。`ts_rank_cd` 的 weights 參數調的是 vector position label 倍率，需要 vector build 時 `setweight` 過才有效 — 我們的 tsvector 沒 setweight、要套就得重 backfill 全 corpus。原方案實作會 break lexical bridge（比 baseline 更窄）。

**選**：query 端對每個 token 拿 IDF、依 4-檔閾值分桶，build 4 條 sub-tsquery（同桶內 OR-join、空桶 → NULL）：
- IDF > 8 → bucket `A`（高 IDF 罕見 token）
- 5 < IDF ≤ 8 → bucket `B`
- 2 < IDF ≤ 5 → bucket `C`
- IDF ≤ 2 → bucket `D`（高頻 stop-word 級）

SQL 端 rank 表達式 = 4 桶 `ts_rank` 加權和：

```sql
ORDER BY (
  CASE WHEN :tsq_a IS NOT NULL
       THEN ts_rank(c.text_tsvector, to_tsquery('simple', :tsq_a)) * 1.0 ELSE 0 END +
  CASE WHEN :tsq_b IS NOT NULL
       THEN ts_rank(c.text_tsvector, to_tsquery('simple', :tsq_b)) * 0.5 ELSE 0 END +
  CASE WHEN :tsq_c IS NOT NULL
       THEN ts_rank(c.text_tsvector, to_tsquery('simple', :tsq_c)) * 0.2 ELSE 0 END +
  CASE WHEN :tsq_d IS NOT NULL
       THEN ts_rank(c.text_tsvector, to_tsquery('simple', :tsq_d)) * 0.05 ELSE 0 END
) DESC
```

Match predicate 仍用全 token OR-join `:ts_query`（不換）— match count 不變、lexical bridge 保留。

**Rationale**：

- 純 query-time 切桶，不動 tsvector、不用 `setweight`、不用重 backfill
- 4-檔已涵蓋從「stop-word」到「entity」的常見頻譜
- chunks 只命中低 IDF 桶 → rank 自然偏低但仍在 pool（保 bridge）
- 高 IDF 桶有 token → 該 chunk rank 拉高（達 spec scenario「high-IDF rank earlier」）
- 細部桶間倍率（1.0 / 0.5 / 0.2 / 0.05）跟桶閾值（8 / 5 / 2）首跑可 calibrate

**拒**：
- 原方案 `ts_rank_cd` weight array → 上述 PG semantic 不通
- `setweight` 重 backfill tsvector → 要重 ingest 全 corpus 成本太高
- 用 `ts_rank` 一律 1.0 然後 post-process 排序 → 把 weight 拆 SQL 跟 app 兩邊太碎、不可預測

### Decision A3: 首版只動 transcript pool、不動 description / title

**選**：lexical SQL 改 IDF weight 只限 `_TRANSCRIPT_RRF_SQL`，description / title pool 維持原 `ts_rank`。

**Rationale**：

- description chunks 是 episode-level 摘要，內容偏結構化、stop-word 比例低於 transcript — 風險低 + 邊際收益低
- title 文字本來就短、跟自然 query 字面交集高 — 不需動
- 只動一處 blast radius 小，先量收益再決定要不要全套

### Decision A4: IDF refresh 走 batch 不走 trigger

**選**：alembic migration 建表後跑一次 backfill；後續走 admin 端 cron job（譬如每天 3 AM）對 `transcript_chunks` 重算 token freq。

**拒**：用 PG trigger 在 transcript_chunks insert/update 時即時更新。

**Rationale**：

- transcript_chunks insert 量小（每 episode 一次 100-300 row batch），但 freq 算動到全 table — trigger 成本高
- batch refresh 簡單、可監控、可手動觸發
- 新 episode 進 corpus 到下次 refresh 之間，IDF 略有 staleness 但不致命

### Decision B1: EP-ref dispatch rule 走 prompt 不走 code branch

**選**：在 chat agent SYSTEM_PROMPT 加段落「Episode Reference Resolution」，明確列出 EP-ref pattern（`EP\d+` / `第\s*\d+\s*集` / explicit episode title 引用），明寫第一動 tool 必為 `find_episode_by_ref` + `search_within_episode`。

**拒**：在 chat_agent.py dispatcher 加 hard regex pre-check → tool call 強制注入。

**Rationale**：

- prompt-based 給 LLM 解釋空間（譬如 user 講「EP」當「episode」縮寫但沒給 number），減少 false positive
- hard branch 處理 edge case（譬如 user 同時引用兩集）會撞 dispatcher 既有邏輯
- 跟 chat-agentic-routing 一致：dispatch 規則寫在 prompt，code 只負責 tool execution + 回應 mapping
- 修錯成本低（改 prompt 文字 + redeploy）

### Decision B2: 同時補強 `search_within_episode` tool description

**選**：`search_within_episode` 的 tool schema description 加一句「whenever the user names a specific episode by number / EP-ref / title, this is the FIRST choice — do NOT fall back to global search for these queries」。

**Rationale**：

- 多一層提示 — OpenAI native tool calling 對 tool description 敏感
- 跟 prompt-level dispatch rule 共構 — prompt 講「應該」、tool description 強化「不要 fallback」
- 跟現有 search tool description 一致風格

### Decision B3: A 跟 B 各自獨立 commit、分階段 verify

**選**：
1. 先 commit Layer A（IDF）+ migration + backfill + redeploy + baseline run（chat 模式）+ 確認不退步
2. 再 commit Layer B（prompt + tool description）+ redeploy + baseline run + 確認 +recall
3. 兩個都 ship 後跑 final diff 對 baseline

**Rationale**：

- 兩 commit 拆開可單條 revert（A 退步 → revert A 留 B；B 退步 → revert B 留 A）
- per-question diff 可看 A 貢獻範圍（b18 / b20-style mismatch）vs B 貢獻範圍（b14 / mt03 t1 / mt04 t1 EP-ref）
- 紀律 per memory `feedback_env_toggle_order_discipline.md`：A 啟用 + verify env 真值 + 再做 B

## Implementation Contract

**Behavior（observable）：**

- Layer A：`retrieve_hybrid` 對相同 query 在相同 chunks 上，lexical pool 內 GT chunks 的 `ts_rank_cd` 排名顯著向前移；total match count 不變（沒砍 token）；final top-K 仍 LIMIT k 不變
- Layer B：chat agent 對含「EP\d+」query 第一個 tool call 必為 `find_episode_by_ref`；對含「第 N 集」query 同樣 dispatch；tool trace 可見

**Interface / data shape：**

- 新 table `transcript_token_freq`：`show_id uuid` / `token text` / `df bigint` / `total_docs bigint` / `idf double precision` / `updated_at timestamptz`；PK = (show_id, token)
- 新 module `backend/app/services/lexical_idf.py`：`get_idf_buckets(show_id, ts_query_tokens) -> dict[str, str]`（token → 'A'/'B'/'C'/'D' bucket label）+ `refresh_freq_table(show_id)`（batch backfill / refresh）
- 新 helper `build_bucketed_ts_queries(ts_query, buckets) -> dict[str, str | None]`（回 `{"a": "tok1 | tok2" or None, ...}`）
- 改 `_TRANSCRIPT_RRF_SQL` lexical CTE：rank 表達式換成 4 桶 `ts_rank` 加權和（CASE WHEN per 桶）；match predicate 仍用 `:ts_query`
- 改 `_build_ts_query` 不變、`retrieve()` 增 IDF lookup + bucket split step before SQL execute
- chat agent prompt 增 "Episode Reference Resolution" 段、`search_within_episode` tool schema description 補一句

**Failure modes：**

- IDF table 缺值（新 token 沒在 cache）→ fallback to weight `C`（中性）、不阻斷主 retrieval、log warning
- IDF table 整表查不到（migration 沒跑成功）→ fallback to 原 `ts_rank` path、不阻斷主 retrieval
- Layer B prompt 改完 LLM 不遵守 → backup safety：`find_episode_by_ref` tool 本來就存在，agent 只是更早呼叫；error path 不變

**Acceptance criteria：**

1. 本地 unit test `test_lexical_idf.py`：IDF 計算公式正確、weight 分桶正確、cache miss fallback 行為正確
2. 本地 unit test `test_agent_epref_dispatch.py`：mock agent 給 「EP134 ...」query → 第一 tool call assert `find_episode_by_ref`
3. Prod DB probe：對 b14 query 跑新 SQL，b14 GT chunks (`9543a933` / `f6cd079f`) 至少 1 個進 lexical pool top-50（vs 老的 #19K-32K）
4. Chat baseline `chunk_recall_grouped ≥ 0.55` / `factual_correctness ≥ 0.88` / `hallucinated=0` / 無 PASS→FAIL

**Scope boundaries：**

- 修改範圍鎖 `backend/app/services/rag.py` transcript pool + `chat_agent.py` (or prompt 檔) EP-ref dispatch + 新 `lexical_idf.py` + 新 table migration
- 不動 description / title lexical SQL
- 不動 retrieve_hybrid 外圍 endpoint signature
- 不動 prefilter / RRF weight / RRF_K / chunking / embedding
- 不動 golden set / dataset

## Risks / Trade-offs

| Risk | Mitigation |
|---|---|
| IDF 4-檔分桶閾值（8 / 5 / 2）拍腦袋不準 | Phase 1a backfill 後跑 prod sample 8 題 audit、看 GT chunks rank shift 再 calibrate 閾值 |
| token_freq table backfill 時間長 / 卡 prod | batch 跑（每 show 一個 batch）、跑在低峰時段、用 `LOCK TABLE` 不要鎖 transcript_chunks |
| IDF cache staleness 影響召回 | Phase 1a backfill 後 1 週觀察、cron 跑 hourly refresh（成本低）；staleness <1 hr 影響可忽略 |
| chat agent 對「EP」字串 false positive（譬如 user 講 "ep" 縮寫某英文詞）| prompt 明寫 pattern 必須含數字、tool description 強化「by number / ref / title」三種具體 trigger |
| Layer B 過度 trigger 把 cross-episode 題型誤走 single-episode search | per-question regression check + b22 / b23 / b27 等 cross-episode 題目納入 baseline |
| IDF weight 注入 setweight 對 PG planner 不友善 | 跑 EXPLAIN ANALYZE 確認還是走 GIN index scan、不退到 seq scan |
| description / title pool 沒改造成 RRF score 不平衡 | 觀察 baseline、若 description 反客為主擠掉 transcript 答案再開 follow-up |

## Migration Plan

1. **Phase 1a — IDF infrastructure**：alembic migration 建表 + `lexical_idf.py` + unit test、本地跑通；admin endpoint `POST /admin/lexical_idf/refresh` 觸發 batch backfill
2. **Phase 1b — Prod backfill**：對所有 active show 跑一輪 backfill（estimated 5-10 分鐘 per show × 3 shows ≈ 30 分鐘）；驗 table row count > 0
3. **Phase 1c — IDF SQL ship**：改 `_TRANSCRIPT_RRF_SQL` → `ts_rank_cd` + setweight；commit + push + redeploy；prod sample 8 題 SQL probe 確認 GT rank 上移
4. **Phase 1d — Baseline A**：跑 chat 模式 baseline、落地 `baseline-step1-idf-only-2026-05-XX.json`；對比 v2 baseline 確認不退步
5. **Phase 2a — Agent prefilter prompt**：改 SYSTEM_PROMPT + `search_within_episode` tool description；commit + push + redeploy
6. **Phase 2b — Baseline A+B**：跑 chat baseline、落地 `baseline-step1-idf-prefilter-2026-05-XX.json`；對比 v2 baseline + step 4 baseline；per-question diff 拆 A / B 貢獻
7. **Phase 3 — 達標判定**：
   - 全達標（cr ≥ 0.55 / fc ≥ 0.88 / hall=0 / 無 PASS→FAIL）→ archive
   - 部分達標 → archive 本 change + propose `lexical-bm25-replace-ts_rank`（候選 C）
   - 退步 → 看 commit 拆 A / B：哪一條 regress 就 single-commit revert

**Rollback**：兩 commit 拆開可單條 revert；IDF table 留著無 schema cost；prompt 改 revert 直接從 git 拉回上版本。

## Open Questions

- IDF 4-檔閾值 8 / 5 / 2 是否合理 — Phase 1c 跑完 prod sample 8 題後可 calibrate；首跑可能偏離最佳值
- token_freq table 在 cross-show 共用（每 show 一份 freq table）vs 全 corpus（pooling 跨 show）— 首版用 per-show 較簡單，未來看資料量再決定
- description pool 是否該同時動 — 首版不動，看 baseline 表現再決定
- Layer B 是否影響 multi-turn t2/t3（user 在 t2 沒重提 EP-ref，但 agent state 已 pin）— 觀察 mt03 / mt04 t2 t3 baseline
