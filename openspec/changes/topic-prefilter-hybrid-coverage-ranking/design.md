## Context

`episode_finders.find_episodes_by_topic_with_source` 在 flag on + ≥2 鑑別 token 時，執行 `_TRANSCRIPT_TOPIC_SQL`：transcript_chunks → transcripts → episodes，`text_tsvector @@ to_tsquery('simple', :tsquery_text)`（tsquery 為 topic 各 token 的 OR），`GROUP BY episode` 取 `MAX(ts_rank)` desc `LIMIT :cap`（cap=`transcript_prefilter_cap`=12），union 進 topic/guest 候選。`tsquery_text` 由 topic 經 jieba 斷詞 + stopword/show-name 過濾後以 `|` 串接（見 `find_episodes_by_topic_with_source` 的 expanded 計算）。

2026-06-07 prod 證實 b23 EP107 端到端命中率極低，根因為 host token「迪拉」灌爆 OR pool 使 EP107 best-chunk ts_rank 出 cap（詳見 proposal Root Cause 與 [[reference_topic_prefilter_transcript_buried_limit]]）。

## Goals / Non-Goals

**Goals**：讓 narrative 跨集題的 GT 集（標靶 EP107）進候選，且不回歸 enumeration 題只命中單一 token 的相關集。

**Non-Goals**：見 proposal Non-Goals（不純替換 coverage、不做語意向量、不改 chunk 召回 / rerank / routing / 觸發 gate）。

## Decisions

### D1. Hybrid union 排序（取代單一 MAX(ts_rank) 排序）

`_TRANSCRIPT_TOPIC_SQL` 回傳候選 = 兩個 arm 的 union（dedup by episode_id）：
- **ts_rank arm**：沿用現況——每集 `MAX(ts_rank)` over OR-tsquery，desc，取前 `:cap` 集。保住 enumeration 題單 token 相關集。
- **coverage arm**：每集計「命中幾個不同 topic token」＝對 tsquery 拆出的各 token 分別判 `text_tsvector @@ to_tsquery('simple', token)`，COUNT(DISTINCT 命中 token)；以 coverage desc 排序、coverage 同分時以 `SUM(per-token MAX(ts_rank))` desc tiebreak，取前 `:cap` 集。撈進 narrative 題多 token 涵蓋的 GT 集。

實作方式（與既有 guest-dispatch union pattern 一致）：可於單一 SQL 內用兩個 CTE（ts_rank arm、coverage arm）各取前 `:cap` 後 `UNION` episode_id 集，或在 Python 端跑兩個既有 query 後合併 dedup。**選單一 SQL 雙 CTE union**：減少 round-trip、coverage 計算需 per-token 展開（tsquery token 以參數陣列傳入），SQL 端 `unnest` 處理最自然。topic token 陣列由 Python（既有 expanded list）傳入新參數（如 `:tokens`）。

### D2. token 陣列來源

coverage arm 需「各 token 分別比對」，故除既有 `:tsquery_text`（OR 串）外，新增參數 `:tokens`（expanded token 陣列，即組成 OR 串的同一批 token，未經 `|` 串接）。兩者由同一份 `expanded` 衍生，保證一致。

### D3. cap 與 over-select

union 後候選上限 ≤ 2×`:cap`（兩 arm 各 ≤ cap，重疊則更少）。沿用 `transcript_prefilter_cap`=12 → union ≤ 24。voyage rerank 下游吸收（記憶證「集進候選後 rerank 召得回」）。不新增 flag；`enable_transcript_topic_prefilter` off 或 <2 鑑別 token 時兩 arm 都不執行（行為與現況位元等價）。

### D4. 觸發條件不變

flag `enable_transcript_topic_prefilter`、≥2 鑑別 token gate（`_discriminating_tokens`）維持。本 change 只改「命中後怎麼排序取集」。

## Implementation Contract

- **Behavior**：flag on 且 ≥2 鑑別 token 時，transcript 候選來源 = (top-cap by MAX(ts_rank)) ∪ (top-cap by distinct-token coverage, sum-rank tiebreak)，dedup by episode_id；flag off 或 <2 token 時不執行、候選與現況位元等價。
- **Interface**：
  - `_TRANSCRIPT_TOPIC_SQL` 改為雙-CTE union，新增繫結參數 `:tokens`（token 字串陣列）；既有 `:show_id` / `:tsquery_text` / `:cap` 保留。
  - `find_episodes_by_topic_with_source` 在執行 transcript query 時多傳 `:tokens`（既有 expanded list）。
- **Failure modes**：token 陣列為空 / 無命中 → 兩 arm 皆空 → transcript 候選為空（與現況同，不報錯）。tsquery / token 含 tsquery 運算子 → 沿用既有 `_re.sub` 清洗。
- **Acceptance criteria**：
  - DB probe：b23 topic「迪拉 Leo王 合作」union 候選**含 EP107**；「高雄 美食」union 候選含 EP85 + EP140 + cov=1 的 EP44。
  - 單元測試：mock db.execute 斷言 transcript query 帶 `:tokens` 參數、union 行為（兩 arm 結果合併 dedup）；flag off / <2 token 不執行。
  - prod chat smoke：b23 題候選/citations 含 EP107（受 LLM topic 生成影響，記錄命中率，不要求 4/4，但需明顯優於修前 0/4）。
- **Scope boundaries**：in scope = `_TRANSCRIPT_TOPIC_SQL` 排序（雙 arm union）+ `:tokens` 參數 + 對應單元測試 + 雙向 DB probe。out of scope = 觸發 gate / flag、chunk 召回 / voyage、routing、`find_episodes_by_recency`、`_TOPIC_CLAUSE`、語意向量選集。

## Risks / Trade-offs

- **候選上限翻倍（≤24）**：可能讓 scoped retrieve 池稍大。緩解：voyage rerank 按 query 語意收斂；cap 仍為 config 可調。
- **coverage tiebreak 仍受 host token 影響**：coverage arm 內 host token 也算一個 token；但因 union 已保 ts_rank arm，且 coverage 把「多 token 涵蓋」拉前，標靶集（EP107 coverage #4）已進。若未來仍漏，再評估 host token 剝除（需 host registry，本 change 不做）。
- **prod smoke 仍受 LLM topic 生成變異影響**：union 改善的是「給定 topic 後 EP107 能否進候選」；topic 本身是否含足夠 token 仍由 answer 模型決定（gpt-5.1 穩定輸出「迪拉 Leo王 合作」3 token，對本 change 有利）。
