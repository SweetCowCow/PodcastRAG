## 1. query 轉發 + 生效-token 推導

> 對應 spec MODIFIED「Transcript candidate source is guarded against non-discriminative over-selection」與 design D1/D2/D4。

- [x] 1.1 在 `backend/app/services/episode_finders.py` 的 `find_episodes_by_topic_with_source` 新增 keyword-only 參數 `query: str | None = None`。實作 design D2 的生效-token 規則：先算 `topic_tokens = _discriminating_tokens(<topic 既有 expand>)`；若 `len(topic_tokens) >= 2` → 生效 token = `topic_tokens`（query 不介入）；否則若 `query` 非空 → 生效 token = `_discriminating_tokens(<topic expand> + <query expand>)`（dedup、保序，沿用既有 jieba/`TOPIC_STOPWORDS`/`get_show_name_terms()` 過濾）；否則 = `topic_tokens`。transcript-aware 路徑的 ≥2 gate、`tsquery_text`（OR-join）、`:tokens`（coverage arm 陣列）一律改用此「生效 token」（維持 `" | ".join(tokens) == tsquery_text` 同源不變式）。`topic_index`（title/desc）、guest-dispatch、`find_episodes_by_recency` 路徑不動，仍只用 topic。實作 design D1（簽章）+ D2 + D4。驗證：`query=None` 時生效 token == `topic_tokens`（既有呼叫點位元等價）；topic<2 + 含 ≥2 鑑別 token 的 query → gate 開、tsquery/tokens 用合併 token。
- [x] 1.2 在 `backend/app/services/chat_agent/tools.py` 的 `_search_with_topic_prefilter` 把 `find_episodes_by_topic_with_source(...)` 呼叫改為傳入 `query=inp.query`。確認同檔 `_find_episodes_by_topic`（find_episodes_by_topic 工具）與 `episode_finders.find_episodes_by_topic` wrapper **不**傳 query（保持舊行為）。實作 design D1。驗證：grep 確認只有 `_search_with_topic_prefilter` 傳 query；其餘呼叫點簽章不變。

## 2. 單元測試

> 對應 spec MODIFIED requirement 的 acceptance criteria 與 design Implementation Contract 三分支。

- [x] 2.1 在 `backend/tests/test_episode_finders_transcript_aware.py` 新增測試覆蓋三分支：(a) `query=None` + topic≥2 → 生效 token == topic 鑑別 token、與現況一致（transcript query 帶該組 tokens）；(b) topic 單 token（如「Leo王」）+ 提供含 ≥2 鑑別 token 的 query（如「迪拉跟 Leo王 第一次見面、從不認識到合作夥伴的故事」）→ transcript query **有執行**、且 `params["tokens"]` 與 `tsquery_text` 同源、含 query 帶進的鑑別 token；(c) topic≥2 + 提供 query → 生效 token 仍 == topic 鑑別 token（query 不改變選集，斷言 tokens 不含 query-only 詞）。用既有 `_mock_db_by_sql` / `_transcript_sql_calls` 風格。驗證：pytest 該檔 + `test_episode_finders.py` + `test_chat_agent_topic_prefilter.py` 全綠。

## 3. DB probe 雙向驗收

> 對應 proposal Success Criteria 與 design D3 over-select 邊界。

- [x] 3.1 對 prod（或可連 DB）跑雙向 probe 並記入 change 目錄 `probe-results.md`：(a) **標靶**——以 b23 的實際 agent 入參（`topic="Leo王"`、`query="迪拉跟 Leo王 第一次見面、從不認識到合作夥伴的故事"`）依 task 1.1 規則算出生效 token，跑 transcript-aware hybrid union，確認候選**含 EP107（`8b3d4c1d`）**；(b) **非回歸**——enumeration 題「高雄 美食」（topic 已 ≥2，query fallback 不觸發）候選**含 EP85、EP140**、候選集數不暴增（與本 change 前一致）。實作 design D3 雙向 acceptance。驗證：probe 輸出兩題生效 token + 候選集 + EP107/EP85/EP140 命中標記，記於 `probe-results.md`。

## 4. 回歸與 prod smoke

- [ ] 4.1 跑既有 `backend/tests/test_chat_agent_topic_prefilter.py`、`test_episode_finders.py`、`test_episode_finders_transcript_aware.py` 確認無回歸（全綠）；改動部署後（git push 觸發 Zeabur build，等 RUNNING），用 `backend/scripts/b23_prod_smoke.sh` 對 prod 跑 b23 題 ≥4 次，記錄於 change 目錄 `smoke-results.md`：EP107 進候選 / 被引用的命中率，且至少一次 `prefilter_source=transcript_index`（確認 ②-觸發層真的打開、非 topic_index）。確認**明顯優於修前 0/6**（受 LLM 變異影響不要求 4/4，但須 >0 且 transcript 路徑有觸發）。驗證：三檔測試全綠；`smoke-results.md` 記錄命中率 + `prefilter_source` 證據，且 EP107 命中 >0/6 基線。
