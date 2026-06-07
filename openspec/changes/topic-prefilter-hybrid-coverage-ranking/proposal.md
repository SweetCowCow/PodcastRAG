## Problem

`topic-prefilter-transcript-aware`（b23 change）的目的是讓答案埋在逐字稿、metadata 沒提的 cross-episode narrative 題能把 GT 集選進候選。但部署後 prod 端到端驗證 NEGATIVE：對 b23 題（「迪拉跟 Leo王 怎麼從不認識變成合作夥伴／第一次見面」，GT = EP107 `8b3d4c1d`）跨多次 chat smoke，EP107 進候選 / 被引用的命中率極低（2026-06-07 實測：gpt-5.1 0/4、gemini-2.5-pro 1/4），即使 routing 已正確 force 到 `search_with_topic_prefilter`（4/4）。

## Root Cause

`episode_finders._TRANSCRIPT_TOPIC_SQL` 對 topic 的 OR-tsquery 命中集，以「每集最佳 chunk 的 `MAX(ts_rank)`」排序、取前 `transcript_prefilter_cap`（=12）集。問題：topic 通常含主持人 token「迪拉」，它在全 show 逐字稿幾乎每集都出現 → OR-match 候選池灌爆到 137+ 集 → EP107 的最佳 chunk ts_rank 被一堆「entity token 講很多次」的集壓下去，掉出 cap 12。

2026-06-07 DB probe 實證（show 政大黑音）：
- topic「迪拉 Leo王 合作」（gpt-5.1 穩定輸出）→ 以 `MAX(ts_rank)` 排序，EP107 排第 27（出 cap）。
- 但改以「命中幾個不同 topic token（distinct-token coverage）」排序 → EP107 排第 4（進 cap）。

→ 純 lexical `MAX(ts_rank)` 排序對「host/entity token 灌爆池」這型無鑑別力；coverage 訊號能把「同時涵蓋多個 topic token」的 narrative GT 集拉前。與 answer 模型無關（換模型都救不了，見 archive/2026-06-07-answer-model-bakeoff-and-switch）。

## Proposed Solution

把 `_TRANSCRIPT_TOPIC_SQL` 的單一排序改為 **hybrid union**：候選 = (top-N by `MAX(ts_rank)`) ∪ (top-N by distinct-token coverage，coverage 同分時以 `SUM(per-token MAX(ts_rank))` 為 tiebreak)，dedup by episode_id。

- **coverage arm** 撈進 narrative 題的 GT 集（b23：EP107 coverage 排第 4 → 進候選）。
- **ts_rank arm** 保住 enumeration 題只命中單一 token 的相關集（純 coverage 替換會把它們踢掉，見 Non-Goals 的否決理由）。

只動 `_TRANSCRIPT_TOPIC_SQL` 的查詢與其組裝排序；候選來源觸發條件（flag `enable_transcript_topic_prefilter`、≥2 鑑別 token gate）不變。

## Non-Goals

- **不做「純 coverage 排序替換」**（已否決）：2026-06-07 probe 證明會回歸 enumeration 題——「高雄 美食」下只命中「美食」單 token 的相關集 EP44 從 ts_rank 第 9 掉到 coverage 第 30、出 cap；且巧合 cov=2 的無關集（EP135 斷捨離、EP74 人類圖）爬到頂污染。narrative 與 enumeration 兩型要的排序相反，故採 union 而非替換。
- 不做語意向量選集（design Alternatives 的 plan B）：union 已用 DB probe 證明能撈進 EP107，較貴的 embedding 路線無必要。
- 不改 chunk 層召回（`retrieve_hybrid`）/ voyage rerank：已驗證「集進候選後 scoped retrieve + rerank 召得回 GT chunk」（瓶頸是集選不是 chunk 召回）。
- 不改 agent routing / tool 選擇（b22 範疇）、不改 `find_episodes_by_recency` / `_TOPIC_CLAUSE`。
- 不改候選來源的觸發 gate（≥2 鑑別 token、flag）。

## Success Criteria

- b23 題（topic「迪拉 Leo王 合作」）經 hybrid union 後，EP107（`8b3d4c1d`）**進入候選集**（DB probe + prod chat smoke 驗證）。
- 既有 enumeration 題「高雄 美食」的 GT 主集（EP85、EP140）**仍在候選內、不掉**（雙向 DB probe 驗證）。更強保證：union 的 ts_rank arm 與現況 SQL 相同，故 union ⊇ 現況候選集，結構上不掉任何現況已選的集。（註：propose 階段誤把 EP44 當 cov=1 回歸案例，apply 期 probe 更正——EP44 在現況排序本就排第 15、不在 cap 12，非本 change 造成；詳見 probe-results.md。）
- 既有 `test_episode_finders*.py` 與 `test_chat_agent_topic_prefilter.py` 全綠。
- 候選集上限放寬至 union 後的 ~2N（voyage rerank 下游吸收），不引入 over-select 失控（既有題候選集數不暴增到不合理）。

## Impact

- Affected specs: chat-agentic-routing（修改 transcript-chunk 候選來源的排序 requirement，納入 coverage union）
- Affected code:
  - Modified: backend/app/services/episode_finders.py
  - Modified: backend/tests/test_episode_finders_transcript_aware.py
  - New: (none)
  - Removed: (none)

## Dependencies

本 change 的 delta spec 以 **MODIFIED** 改寫 requirement「Transcript candidate source is guarded against non-discriminative over-selection」，該 requirement 由 `topic-prefilter-transcript-aware`（目前 active 5/6、未 archive）ADD。故 **archive 順序：先 archive `topic-prefilter-transcript-aware`（其 requirement 進主 spec）→ 再 archive 本 change（MODIFIED 套用）**。`spectra analyze` 會在本 change 報「MODIFIED requirement not found in main spec」直到前者 archive，屬預期。

`topic-prefilter-transcript-aware` 的 task 5.1（prod b23 引用 EP107）正是被本 change 修好——前者交付「transcript 候選**來源**」，本 change 修「候選**排序**讓 EP107 真的進池」。前者 archive 時其 task 5.1 應 re-scope 為「來源存在 + routing 觸發」，EP107 端到端可靠性交本 change 驗收（見 [[reference_topic_prefilter_transcript_buried_limit]]）。
