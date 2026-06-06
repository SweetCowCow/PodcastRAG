## Context

`episode_finders` 的候選集選共用一段「title_tsvector OR description-chunk EXISTS」的 tsquery 比對（`_TOPIC_SQL` 給 `find_episodes_by_topic` / `find_episodes_by_topic_with_source`；`_TOPIC_CLAUSE` 給 `find_episodes_by_recency` 及其 count）。topic 經 `_build_topic_tsquery`：jieba 斷詞 → 保留 len≥2 且非 `TOPIC_STOPWORDS` → OR-join 成 `to_tsquery('simple', ...)`。

兩個來源都不碰 `transcript_chunks`。已有 guest-dispatch 旁路（`enable_guest_dispatch: bool = True`，≥2 token 命中已知來賓時 union `episodes.guests` JSONB 命中集）作為「加候選來源 + flag kill-switch」的先例。

2026-06-06 prod verify-first 已確認（見 [[reference_topic_prefilter_transcript_buried_limit]]）：b23 瓶頸是**集選**不是 chunk 召回（scope 到 EP107 後 GT 排 3/18），且 full-show routing 解法已淘汰。

## Goals / Non-Goals

**Goals:**

- 讓 narrative cross-episode 題（答案埋逐字稿、title/desc 沒提）的 GT 集能進候選——具體標靶：b23 題選進 EP107（`8b3d4c1d`）。
- 不讓既有純 title/desc 命中的 topic 題退步：候選集不暴增、原本選到的集仍選到。
- 改動可由 flag kill-switch 關閉（鏡像 `enable_guest_dispatch`）。

**Non-Goals:**

- 不改 chunk 層召回 / voyage rerank（已驗證沒問題）。
- 不做 full-show routing 解法（已淘汰）。
- 不做語意向量選集（備案 B，見 Alternatives）。
- 不改 agent tool 選擇邏輯。

## Decisions

### D1. 新增 transcript-chunk 候選來源（主案 A，lexical；獨立 query + union）

**實作方式（apply 校正 2026-06-06）**：不把 transcript OR 進靜態 `_TOPIC_SQL`，而是**獨立一條 `_TRANSCRIPT_TOPIC_SQL` + union 進結果**，鏡像既有 guest-dispatch（`_GUEST_DISPATCH_SQL` 獨立執行後 union）的成熟 pattern。理由：(1) 保住既有 `_TOPIC_SQL` 結構與其單元測試；(2) ts_rank 排序 + cap 在獨立 query 裡好寫（`GROUP BY episode` 取 `MAX(ts_rank)` desc `LIMIT :cap`），塞進 OR-clause 做不到。

`_TRANSCRIPT_TOPIC_SQL`：經 `transcripts` 關聯到集、`transcript_chunks.text_tsvector @@ to_tsquery('simple', :tsquery_text)`，以每集最佳 chunk `ts_rank` 排序取前 `:cap` 集。flag 關閉或 <2 token 時完全不執行此 query（候選與現況位元等價）。union 進 `_with_source` 既有 topic_eps/guest_eps 的合併邏輯（dedup by episode_id）。

### D2. over-select 防護（必要，否則常見 token 撐爆候選）

常見 token（如主持人「迪拉」）在全 show 逐字稿極常見，naive OR-match 會把幾乎所有集納入候選（記憶實證 uncapped 64 集）。防護兩層：

1. **≥2-token gate（次要防線）**：transcript 來源只在 topic 的 token 數（`_build_topic_tsquery` 的 jieba 抽詞：len≥2、非 `TOPIC_STOPWORDS`、再扣 `tokenizer.get_show_name_terms()`）**≥2** 時才啟用。單一 token 的 topic 不走 transcript 來源（避免單一常見詞掃全庫）。
   - **apply 發現的現實校正（2026-06-06）**：原設計寫「扣掉 host」，但全專案**無 host registry**、且主持人「迪拉」不在 show title「這又沒有很屌」衍生的 show-name terms 內，故無法照寫實作；document-frequency 判鑑別性亦不可行（[[feedback_idf_show_wide_failed_2026_05_28]]）。因此 gate 改為「≥2 個 jieba token（扣 stopword + show-name）」，**不含 host 專屬移除**。host 造成的雜訊改由下方 ts_rank cap 為主防線吸收。
2. **ts_rank cap（主防線）**：transcript 來源命中的集，以該集最佳 transcript chunk 的 `ts_rank` 排序，只取前 `transcript_prefilter_cap`（初值 8）集併入候選。這是擋 over-select 的**主要**機制——即使常見 token 害數十集沾邊，排序後只留最吻合的前 N 集（同時吻合多個 token 者排前），雜訊集擋在 N 名外。

兩層防護的確切參數（gate 門檻 2、cap）**已於 apply 用 prod DB probe 雙向驗證（2026-06-06）**：
- 既有題「高雄 | 美食」命中 100/~150 集（OR-match 幾乎無鑑別力），但 GT 集 EP85 以 ts_rank 排第 4 → cap 內、不暴增（cap 即唯一收斂機制，符合 D2「ts_rank cap 是主防線」）。
- b23「迪拉 | Leo」命中 137 集、EP107 排第 27（host token「迪拉」幾乎每集都有、把排名壓平）；但較完整 topic「迪拉 | Leo | 第一次 | 見面」→ EP107 排第 3；純「Leo」→ 排第 10。
- **cap 定案 = 12**（非初值 8）：給「Leo-only 第 10 名」留 headroom；entity-only「迪拉 Leo王」第 27 名任何合理 cap 都救不了，該情境靠 LLM 抽出動作詞（由 prod chat smoke 端到端驗證）。

**校準揭露的本質限制**：lexical transcript OR-tsquery 對常見/host token 幾乎命中全 show，成敗高度取決於 LLM topic extractor 是否吐出鑑別性動作詞。若 prod smoke 證明 entity-only 抽取導致 EP107 仍漏，則轉 Alternatives 的 plan B（語意向量選集）。

### D3. flag kill-switch

新增 `enable_transcript_topic_prefilter: bool = True`（鏡像 `enable_guest_dispatch`）。預設 ON（這是 bug fix，off 等於沒修），`ENABLE_TRANSCRIPT_TOPIC_PREFILTER=false` 可不改 code 退回現況行為。

### D4. 只做 chat 選集路徑；recency listing scope out（apply 校正 2026-06-06）

**原設計**要 `_TOPIC_SQL`（topic 選集）與 `_TOPIC_CLAUSE`（recency 的 topic filter + count）同步加 transcript 來源。**apply 校正為只做前者**，理由：

1. **b23 只走 `_with_source`**：bug 是 chat 的 `search_with_topic_prefilter` → `find_episodes_by_topic_with_source` 選不到 EP107；`find_episodes_by_recency` 是「列出關於 X 的集數」listing，非 b23 路徑。
2. **實作不相容**：D1 選的「獨立 query + union + ts_rank cap」pattern 是在 `_with_source` 把結果集 union；`_TOPIC_CLAUSE` 是嵌在 recency `WHERE` 裡的 filter，塞不進 union 也做不出 ts_rank cap（WHERE EXISTS 無排序）。
3. **語意不同**：recency 加 transcript 命中會讓 `n_total_matched` 因 host 等常見詞暴增（「關於迪拉的集數」變幾乎全 show），over-select 防護需求與 chat 不同，值得獨立評估。

因此 `_TOPIC_CLAUSE` / `find_episodes_by_recency` 本次**不動**，列為 follow-up（若 listing 也需 transcript-aware 再開）。兩路徑短期行為分歧是刻意取捨，已記錄於此。

## Implementation Contract

- **Behavior**：flag ON 且 topic 含 ≥2 鑑別 token 時，候選集選除 title/desc 外，另納入「transcript_chunks tsvector 命中且 ts_rank 前 N」的集；flag OFF 或鑑別 token <2 時，行為與現況位元等價。
- **Interface**：
  - `config.Settings` 新增 `enable_transcript_topic_prefilter: bool = True`、`transcript_prefilter_cap: int`（初值 8，apply 校準後回填）。
  - `episode_finders` 新增 `_TRANSCRIPT_TOPIC_SQL`（獨立 query，transcript_chunks→transcripts→episodes，`ts_rank` desc `LIMIT :cap`），在 `find_episodes_by_topic_with_source` 受 flag + ≥2-token gate 控制執行後 union 進候選（鏡像既有 guest-dispatch）。`_TOPIC_CLAUSE` / `find_episodes_by_recency` 本次不動（見 D4）。
  - 鑑別 token 計算新增 helper，沿用 `_build_topic_tsquery` 的 token 抽取，再扣 `tokenizer.get_show_name_terms()`（無 host registry，不做 host 專屬移除）。
- **Failure modes**：transcript-tsquery 建構失敗或 flag off → 不加 transcript 子句、走現況路徑（fail-safe，不影響既有候選）。
- **Acceptance criteria**：
  - 單元測試：flag off → SQL 不含 transcript 子句（候選與現況一致）；flag on + 單鑑別 token → 不啟用 transcript 來源；flag on + ≥2 鑑別 token → 啟用。
  - DB probe（apply）：b23 topic 候選集**含 EP107**；既有 topic 題（歌單等）候選集數在 cap 內、不暴增。
  - 既有 `test_chat_agent_topic_prefilter.py` + episode_finders 測試全綠。
- **Scope boundaries**：in scope = `find_episodes_by_topic_with_source` 的 transcript 來源（獨立 query + union）+ flag + over-select 防護 + 校準。out of scope = `find_episodes_by_recency` / `_TOPIC_CLAUSE`（見 D4）、chunk 召回 / voyage / agent routing / 語意選集。

## Alternatives Considered

- **備案 B：語意向量選集**（embed query → 找 transcript chunk 語意最近的集）。抓得到詞彙失配，但每次選集多一次 embedding + 向量查詢、較貴且較複雜。僅在主案 A（lexical + 防護）校準後仍漏 EP107 時才評估。
- **full-show routing**（讓 narrative 題走 `search_across_episodes`）：2026-06-06 prod 已淘汰——full-show top-50 GT 全 miss（episode competition），voyage 撈不回池外。

## Risks / Trade-offs

- **over-select 仍可能**：鑑別門檻 2 + cap 8 是初值，可能對某些 topic 仍偏多或偏少。緩解：flag kill-switch + cap 為 config 可調 + apply 時 DB probe 校準雙向驗證。
- **lexical 仍可能漏詞彙失配集**：若 EP107 逐字稿用字與 topic token 完全不重疊，lexical transcript 來源也選不到。緩解：b23 已驗證 full-show 下 EP107 transcript 有 surface（rank 9），代表 lexical/語意上 EP107 transcript 對 query 有命中，主案 A 命中機率高；若 apply DB probe 證明仍漏，轉備案 B。
- **小樣本**：標靶主要是 b23 單題，可能 over-fit。緩解：以「既有 topic 題不退步」當反向 guard，且 flag 預設可關。
