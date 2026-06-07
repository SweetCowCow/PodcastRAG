## 1. Hybrid union SQL

> 對應 spec「Transcript candidate source is guarded against non-discriminative over-selection」(MODIFIED) 與 design D1/D2。

- [x] 1.1 在 `backend/app/services/episode_finders.py` 把 `_TRANSCRIPT_TOPIC_SQL` 改為雙-CTE union：CTE `by_rank`（沿用現況 `MAX(ts_rank)` over `to_tsquery('simple', :tsquery_text)`，desc，`LIMIT :cap`）、CTE `by_coverage`（對 `:tokens` 陣列 `unnest` 後，每集計 `COUNT(DISTINCT token)` where `text_tsvector @@ to_tsquery('simple', token)`，desc，tiebreak `SUM(per-token MAX(ts_rank))` desc，`LIMIT :cap`），最後 `SELECT ... FROM episodes WHERE id IN (by_rank ∪ by_coverage)` 回傳兩 arm union 的集（dedup by episode_id，保留現有回傳欄位 id/title/published_at/guests/ai_summary）。新增繫結參數 `:tokens`（token 字串陣列）。實作 design D1/D2。驗證：單獨對 prod-like DB 跑此 SQL（task 2.1 probe）兩 arm 都生效。
- [x] 1.2 在 `find_episodes_by_topic_with_source` 執行 transcript query 處，把既有 `expanded` token list 以新參數 `:tokens` 傳入 `_TRANSCRIPT_TOPIC_SQL`（與 `:tsquery_text` 同源，保證一致）；觸發條件（flag `enable_transcript_topic_prefilter` + `_discriminating_tokens(expanded) >= 2`）不變。實作 design D4。驗證：flag off 或 <2 鑑別 token 時此 query 完全不執行（候選與現況位元等價）。

## 2. DB probe 雙向驗收

> 對應 proposal Success Criteria 與 design Implementation Contract acceptance：標靶進、既有不掉。

- [x] 2.1 對 prod（或可連 DB）跑 hybrid union 候選 probe，雙向驗證並把證據記入 change 目錄（`probe-results.md`）：(a) b23 topic「迪拉 Leo王 合作」union 候選**含 EP107（`8b3d4c1d`）**；(b) 既有 enumeration 題「高雄 美食」union 候選含 GT 主集 **EP85、EP140**，且確認 union 的 ts_rank arm = 現況 SQL → union ⊇ 現況候選集、結構上不掉現況已選集。實作 design Implementation Contract 的雙向 acceptance。驗證：probe 輸出兩題候選集 + EP107/EP85/EP140 命中標記。

## 3. 單元測試

> 對應 spec MODIFIED requirement 的 acceptance criteria。

- [x] 3.1 更新 `backend/tests/test_episode_finders_transcript_aware.py`：mock `db.execute`（依 SQL 內容回不同 result）斷言——transcript query 帶 `:tokens` 參數且為 expanded token list；union 行為（by_rank 與 by_coverage 兩來源合併、dedup by episode_id）；flag off → 不執行；<2 鑑別 token → 不執行。同步調整既有斷言以符合雙-CTE union（原斷言只驗單一 `MAX(ts_rank)` query 形狀）。驗證：pytest 該檔 + `test_episode_finders.py` + `test_chat_agent_topic_prefilter.py` 全綠。

## 4. 回歸與 prod smoke

- [x] 4.1 跑既有 `backend/tests/test_chat_agent_topic_prefilter.py` 與 episode_finders 相關測試確認無回歸（**33 passed**）；對 prod（部署後 commit 2696f4f）用 `backend/scripts/b23_prod_smoke.sh` 跑 b23 題 ×6。**結果記入 `smoke-results.md`**：本 change 修正的 ③-排序層效力由 task 2.1 DB probe apples-to-apples 證明（同一會觸發路徑的 3-token topic「迪拉 Leo王 合作」下，EP107 修前 #27 出 cap → 修後經 coverage arm 進 union）。prod chat smoke 端到端 0/6 **非本 change 失敗**：gpt-5.1 穩定把實體放 `topic="Leo王"`（1 鑑別 token）、敘述放 `query` → 連 transcript 觸發 gate（≥2 token，本 change 明列不改）都沒過、走 `topic_index`，③-排序層整個沒被執行。此「thin topic-arg」缺口屬 ②-觸發層，是新 follow-up（見 smoke-results.md 衍生發現），不在本 change 範疇。驗證：回歸測試全綠 ✓；smoke 命中率與「未觸發本 change 路徑」之根因記錄於 `smoke-results.md` ✓。
