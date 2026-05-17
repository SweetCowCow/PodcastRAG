## 1. SQL 改造

- [x] 1.1 `find_episodes_by_topic` 回傳的 episode 列表 SHALL 包含「title_tsvector match OR description chunks tsvector match」的所有 episodes（distinct by `episodes.id`，按 `published_at DESC NULLS LAST` 排序）— 在 `backend/app/services/episode_finders.py` 重寫 `_TOPIC_SQL` 為 EXISTS-OR 形式（以 `episodes` 為 driving table）；可順手把 `_TOPIC_SQL_OUTER_ORDER` outer wrapper 收斂掉（EXISTS-OR 已天然 distinct）。驗證：手動跑 `psql` 對 prod DB 執行新 SQL，輸入 `:tsquery_text='歌單'`，回傳列表 SHALL 包含 EP19 / EP84 / EP87 / EP89 / EP96 / EP108 全部 6 集。
- [x] 1.2 `find_episodes_by_topic` 對空 `topic_terms` / stopword-only 輸入 SHALL 維持回 `[]` 且不打 DB；對含特殊字元（`&|!()<:>\\`）的輸入 SHALL 維持現行 `re.sub` 清理。驗證：跑既有的 `backend/tests/services/test_episode_finders.py` 既有測試全綠（無回退）。

## 2. 單元測試

- [x] 2.1 新增測試案例 `test_find_episodes_by_topic_title_only_match`：assert 一個 title 含 topic 字、description 不含的 episode 出現在回傳清單。驗證：`pytest backend/tests/services/test_episode_finders.py::test_find_episodes_by_topic_title_only_match -v` 通過。
- [x] 2.2 新增測試案例 `test_find_episodes_by_topic_description_only_match`：assert 一個 description 含 topic 字、title 不含的 episode 仍出現在回傳清單（回歸測試）。驗證：`pytest backend/tests/services/test_episode_finders.py::test_find_episodes_by_topic_description_only_match -v` 通過。
- [x] 2.3 新增測試案例 `test_find_episodes_by_topic_both_match_dedup`：assert 一個 title + description 都含 topic 字的 episode 在回傳清單中恰好出現一次。驗證：`pytest backend/tests/services/test_episode_finders.py::test_find_episodes_by_topic_both_match_dedup -v` 通過。

## 3. 部署與 prod 驗證

- [x] 3.1 變更 commit 後 git push 觸發 Zeabur build；若 webhook 沒觸發 build，跑 `zeabur service redeploy --id <backend-svc-id> -y -i=false` 確保新 code 上線。驗證：`curl https://podcastrag-api.zeabur.app/stats` 200 OK，且 `/healthz` 回新 commit SHA（或於 Zeabur dashboard 確認 build SHA 與 main HEAD 一致）。
- [x] 3.2 對 prod chat 跑 q25「節目裡有哪些集是歌單？」一次，`enumeration_episodes` 的 episode_id 集合 SHALL ⊇ q25 expected_episode_ids 27 集（含原 21 集 + 6 漏撈集 EP19 / EP84 / EP87 / EP89 / EP96 / EP108）。驗證：以 `tools/q25_check.sh`（臨時腳本，apply 階段建立或一次性 curl）比對回傳 episode_ids 與 `backend/eval/datasets/this-not-that-cool.json` q25 expected 集合，列出 missing；missing 集 SHALL 為空。

## 4. Eval runner 全套回歸

- [x] 4.1 對 prod backend 跑 `backend/eval/runners/run.py` 全套 30 題：aggregate `episode_set_recall` SHALL ≥ 0.94（從 0.88 提升至少 6 個百分點），且 `Recall@5` aggregate SHALL ≥ 0.86（不回退）。驗證：開啟新 result JSON `backend/eval/results/eval-this-not-that-cool-<新 timestamp>.json`，讀取 `aggregate.episode_set_recall` 與 `aggregate.recall_at_5`，數字達標。
- [x] 4.2 對 prod chat 抽樣其他 topic 題（至少 q26 高雄美食 + 另一題譬如「動漫」或「雷鬼」），對照 `enumeration_episodes` 集合與既有預期，false positive 集數新增量 SHALL ≤ 2 集。驗證：手動跑 chat 並列出回傳 episode_ids，逐集肉眼判讀題目意圖；超標時記錄並回頭調整 stopword filter 或回退。

## 5. 收尾

- [x] 5.1 更新 release log（`docs/release-log/` 對應檔案）加入本 change 條目，採使用者視角描述：哪類題目從此能撈得更全（譬如「問『有哪些集是 X 主題』時，標題寫了主題但內文沒寫的集數現在也會列進來」）。驗證：release log diff 中新條目存在且使用使用者語氣（無 SQL / tsvector 等技術詞）。
- [ ] 5.2 `/spectra-archive enumeration-topic-finder-include-title`：把 spec deltas 合進 `openspec/specs/rag-query/spec.md`、change 目錄移到 archives。驗證：`spectra list` 不再列出 `enumeration-topic-finder-include-title`；`grep -n "title_tsvector" openspec/specs/rag-query/spec.md` 顯示新合入的 scenario 文字。
