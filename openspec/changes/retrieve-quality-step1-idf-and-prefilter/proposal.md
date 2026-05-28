## Outcome — 2026-05-28: FAILED, both layers reverted

兩 Layer 跑完 chat 模式 baseline 後皆未達標、全部 revert：

| Metric | Baseline | Layer A only | Layer B only |
|---|---|---|---|
| `chunk_recall_grouped` | 0.482 | **0.382** (-0.100 ❌) | **0.340** (-0.142 ❌) |
| `factual_correctness` | 0.892 | **0.831** (-0.061 ❌) | **0.875** (-0.017) |
| Regressed cases | 0 | 7 | 6 |

**Root causes**（細節在 design.md「Layer A Postmortem」/「Layer B Postmortem」+ case study `docs/case-studies/retrieve-quality-step1-idf-and-prefilter-2026-05-28.md`）：

1. **Layer A**：show-wide IDF 對 podcast transcript 不適用 — entity token 雖然 show-wide rare、但**在 answer-episode 內部很常見**（譬如「伴手禮」在 EP44 滿地都是），bucketed weighting 把 topic-related-but-not-answer chunks rank 推高、把 answer chunks 擠出 top-K
2. **Layer B**：以為「純 prompt dispatch nudge」是 zero-risk，實際上新 prompt 段改了 agent 整體 query 制定行為，下游 `search_within_episode` 收到的 `query` 字串隨之改變 → tsquery tokens 不同 → ts_rank 結果不同 → GT chunks 沒命中

**Outcome 留下的東西**：
- prod 仍有 orphan `transcript_token_freq` table（< 100MB，無程式引用，留作 EP-scoped IDF 可能 reuse）
- 對應 alembic migration `aab5c6d7e8f9` 保留（避免 alembic_version 對不齊）
- 兩條 case study 教訓寫進 memory：`feedback_idf_show_wide_failed_2026_05_28.md` + Layer B 飽和教訓延伸 `feedback_prompt_saturation_more_is_less.md`

**Next path**：propose **評估框架升級**（span-level tracing + Ragas）— 下次動 retrieval / prompt 前要先有 observability 才能預測這種 side effect。

---

## Summary

Two orthogonal retrieval-quality improvements bundled as one change（兩個正交 layer，分兩個 commit ship）：(A) lexical pipeline 在 ts_rank 層用 corpus-wide token frequency (IDF) 自動降權高頻 token，取代失敗的 query 層 stop-word filter；(B) chat agent 強化「explicit EP-ref 題型」dispatch logic，看到 `EP\d+` 或集數提示時優先走 `search_within_episode` 跳過全 show retrieve_hybrid。

## Motivation

承接 archived `lexical-stopword-filter-rca-deep-dive`（case study `docs/case-studies/lexical-stopword-filter-rca-deep-dive-2026-05-28.md`）結論：

**核心 RCA**：在 OR-joined tsquery + ts_rank LIMIT per_side=50 + RRF merge 三層架構下，query 層任何 token pruning 都會破壞「弱 lexical bridge 對 RRF tie-breaking 的貢獻」。修法必須走 **weighting 而非 filtering**。

**量化現況基準**（`baseline-post-judge-v2-2026-05-27.json`）：
- `chunk_recall_grouped` = 0.482
- `factual_correctness` = 0.892
- b14 / mt03 t1 / mt04 t1 等 explicit EP-ref 題型在全 show retrieve 中 GT 排名遠超 LIMIT 50

兩條修法是 RCA case study 的 ROI 排序 top 2 候選：
- (A) IDF weighting：M effort、+5~+12 pp recall、低風險 — 直接補 RCA 指出的「不該 prune，該 weight」修法方向
- (B) Agent prefilter dispatch：S effort、+3~+8 pp recall、低風險 — sidestep retrieve_hybrid 對 EP-ref 題型的盲點

兩條動不同層（A 動 SQL/retrieval、B 動 agent dispatch logic），合 ship 仍可 per-question diff 歸因（b14/mt03 t1/mt04 t1 是 prefilter 貢獻、b18/b20-style 是 IDF 貢獻），且兩個獨立 commit 出問題可單條 revert。

## Proposed Solution

### Layer A — IDF-based corpus weighting（retrieval SQL）

1. 新增 corpus token frequency cache 機制：對 `transcript_chunks.text_tsvector` 跑全 show 統計，產 token → document_frequency map，落地進 `transcript_token_freq` table（schema: `show_id` / `token` / `df` / `total_docs` / `idf`），定期 refresh
2. 改 lexical SQL：把 `ts_rank(c.text_tsvector, to_tsquery(...))` 換成 IDF-weighted variant — 用 `ts_rank_cd` 搭配 `setweight` 把每個 query token 的 IDF 對應 weight 注入 tsvector，讓高頻 token 自然降權但**保留 lexical match**
3. 不動 `_build_ts_query`（沿用既有 OR-join 邏輯）、不動 RRF merge、不動 per_side cap

### Layer B — Agent prefilter dispatch strengthening（chat-agentic-routing）

1. SYSTEM_PROMPT 加 explicit dispatch rule：偵測 `EP\d+` / `第 X 集` / explicit episode reference → 第一動必走 `find_episode_by_ref` + `search_within_episode`，不走 `search_with_topic_prefilter` 或 `retrieve_hybrid` 全 show fallback
2. tool description 補強：`search_within_episode` 標註「whenever the user names a specific episode by number / EP-ref / title, this is the FIRST choice — do NOT fall back to global search for these queries」
3. eval-only validation：跑 baseline 對比 RAR(EP-ref) 4 題（b14 / b16 / b17 / mt03 t1 / mt04 t1）chunk_recall + factual

兩條獨立 commit、分階段 verify。Layer A 先（影響面廣）、Layer B 後（影響面窄）。

## Non-Goals

- 不動 jieba tokenizer、custom dictionary、stop-word list（A 不靠 token-level filter）
- 不動 chunking / embedding / RRF merge weight / RRF_K
- 不寫 BM25 替換 ts_rank（留 candidate C `lexical-bm25-replace-ts_rank` 作 Phase 2 備案）
- 不動 golden set / GT chunk_id
- 不重 backfill 全 show transcript_chunks（IDF 只走新 freq table，原 chunks 不動）
- 不改 description / title pool 的 ts_rank（先只動 transcript pool；description 若退步另開 follow-up）

## Alternatives Considered

- **重啟 `retrieve-hybrid-lexical-stopword-filter`（細選 stop-word list）**：RCA 已證 87.5% 被砍 token 是真 stop-word 仍是 bridge — 不論怎麼選都會破壞
- **BM25 全替 ts_rank**（candidate C）：理論最強 +5~+15 pp，但 L effort 重寫核心 SQL、風險中-高，留作 Phase 2 備案
- **A 跟 B 拆兩 change 序列 ship**：紀律 per memory `feedback_parked_changes_apply_order.md`「每完成一個 archive 重跑 baseline」— 但該紀律是「同層 change」才該堅持；A B 不同層、不互踩、per-question diff 可歸因，合 ship 省一輪 eval 時間 + commit 拆兩個出問題單條 revert 即可

## Impact

- Affected specs:
  - Modified: `rag-query`（lexical retrieval 加 IDF weighting 行為）
  - Modified: `chat-agentic-routing`（EP-ref dispatch rule 補強）
- Affected code:
  - New: `backend/app/services/lexical_idf.py`（token frequency cache + IDF 計算 helper）
  - New: alembic migration 加 `transcript_token_freq` table
  - Modified: backend/app/services/rag.py（lexical SQL 改 IDF-weighted）
  - Modified: backend/app/services/chat_agent.py 或對應 prompt 檔（dispatch rule + tool description）
  - New: backend/tests/services/test_lexical_idf.py
  - New: backend/tests/services/test_agent_epref_dispatch.py
  - New: backend/eval/results/baseline-step1-idf-prefilter-2026-05-XX-chat.json
  - New: docs/case-studies/retrieve-quality-step1-idf-and-prefilter-2026-05-XX.md
- Affected ops: prod redeploy；新 table backfill（IDF table 從 transcript_chunks 算出，分 batch 跑、不阻塞 prod query）
- Risk:
  - 中 — IDF 計算公式 / 注入 tsvector 機制是新作法，可能埋微調空間
  - 低-中 — agent prompt 調整可能誤觸發 dispatch（譬如 user 講「ep」當縮寫但非 EP-ref）
  - per-question regression check 是主要 safety net；兩 commit 拆 ship 可單條 revert

## Success Criteria

對比基準 `backend/eval/results/baseline-post-judge-v2-2026-05-27.json`（pre-change clean baseline）：

- `chunk_recall_grouped` ≥ **0.55**（baseline 0.482，目標 +0.07）
- `factual_correctness` ≥ **0.88**（baseline 0.892，不退步）
- `hallucinated_cases` = 0（不增加）
- 無任何題 grading 從 PASS → FAIL（per-question regression check）
- Per-question diff：A 貢獻（IDF）跟 B 貢獻（prefilter dispatch）能在表上分開讀出 — b14/mt03 t1/mt04 t1 進步是 B；b18/b20-style 進步是 A
