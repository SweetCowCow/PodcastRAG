## 1. 設定旗標

> 對應 spec requirement「Topic candidate selection includes transcript-chunk matches」；design D3「flag kill-switch」。

- [x] 1.1 在 `backend/app/core/config.py` 的 `Settings` 新增 `enable_transcript_topic_prefilter: bool = True`（鏡像 `enable_guest_dispatch`，`ENABLE_TRANSCRIPT_TOPIC_PREFILTER=false` 可關）與 `transcript_prefilter_cap: int = 8`（初值，task 4.1 校準後回填）。實作 spec requirement「Topic candidate selection includes transcript-chunk matches」的 flag 部分。驗證：import settings 不報錯、兩欄位可由環境變數覆蓋（單元測試讀預設值通過）。

## 2. transcript-chunk 候選來源 + over-select 防護

> 對應 spec requirement「Topic candidate selection includes transcript-chunk matches」與「Transcript candidate source is guarded against non-discriminative over-selection」；design D1「新增 transcript-chunk 候選來源（獨立 query + union）」、D2「over-select 防護」、D4「只做 chat 選集路徑；recency scope out」。

- [x] 2.1 在 `backend/app/services/episode_finders.py` 新增 helper：給定 topic 算「token 數」＝jieba 斷詞（len≥2、非 `TOPIC_STOPWORDS`、再扣 `tokenizer.get_show_name_terms()`）後的詞數（沿用 `find_episodes_by_topic_with_source` 的 expanded 計算）。實作 spec requirement「Transcript candidate source is guarded against non-discriminative over-selection」的 ≥2-token gate 計算（無 host registry，不做 host 專屬移除；over-select 主防線為 ts_rank cap）。驗證：單元測試——「迪拉 Leo王」算出 ≥2、單一 token topic（如「歌單」）算出 <2。
- [x] 2.2 在 `episode_finders.py` 新增 `_TRANSCRIPT_TOPIC_SQL`（transcript_chunks→transcripts→episodes，`text_tsvector @@ to_tsquery('simple', :tsquery_text)`，`GROUP BY` 集取 `MAX(ts_rank)` desc `LIMIT :cap`），並在 `find_episodes_by_topic_with_source` 受 `enable_transcript_topic_prefilter` + ≥2 鑑別 token 控制執行後，union 進既有 topic_eps/guest_eps 合併（dedup by episode_id），鏡像既有 guest-dispatch。flag off 或 <2 token 時完全不執行此 query（候選與現況位元等價）。`_TOPIC_CLAUSE`/recency 不動（D4）。實作 spec 兩條 requirement。驗證：單元測試——flag off → 不執行 transcript query（候選與現況一致）；單 token → 不執行；≥2 token + flag on → 執行且帶 cap param；EP107 經 transcript 命中可進候選。

## 3. 單元測試

> 對應 spec 兩條 requirement 的 acceptance criteria。

- [x] 3.1 新增 `backend/tests/test_episode_finders_transcript_aware.py`：用 mock `db.execute`（依 SQL 內容回不同 result）斷言——flag off → 不執行 `_TRANSCRIPT_TOPIC_SQL`（候選與現況等價）；flag on + <2 鑑別 token → 不執行；flag on + ≥2 鑑別 token → 執行且帶 `:cap` param；鑑別 token 計算正確扣除 stopword + show-name term。同步更新 `backend/tests/test_episode_finders.py` 的 `test_find_by_topic_does_not_touch_transcript_chunks`（原斷言「永不碰 transcript_chunks」已被本 change 反轉）為 flag-aware 行為。驗證：pytest 兩檔全綠。

## 4. DB probe 校準（apply 時驗證 over-select 防護）

> 對應 design D2 必驗項：標靶選進 + 既有題不暴增。

- [x] 4.1 對 prod（或可連的 DB）用 b23 topic「迪拉 Leo王」+ 既有 topic 題（如「歌單」「高雄美食」）量 transcript-aware 候選集：確認 b23 候選**含 EP107（`8b3d4c1d`）**、既有題候選集數在 cap 內不暴增；據此定 `transcript_prefilter_cap` 終值並回填 task 1.1 的 config 預設與 design。實作 design D2 的雙向驗證關卡。驗證：probe 輸出 b23 候選含 EP107 的證據 + 既有題候選集數列表；config cap 已更新。

## 5. 回歸與收尾

- [ ] 5.1 跑既有 `backend/tests/test_chat_agent_topic_prefilter.py` 與 episode_finders 相關測試確認無回歸；對 prod（flag 預設 on 部署後）打一筆 b23 chat 查詢，確認 agent 經 `search_with_topic_prefilter` 後候選含 EP107、回答引用到 EP107 的 GT 段。驗證：既有測試全綠；prod b23 查詢 trace 顯示候選含 EP107。
