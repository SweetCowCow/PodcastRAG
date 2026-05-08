# Tasks

## 1. Schema migration

- [x] 1.1 New alembic revision `backend/alembic/versions/<rev>_r32_topic_seg.py`，down_revision=`r6e7f8a9b0c1`
- [x] 1.2 Up: `ALTER TABLE transcript_segments ADD COLUMN topic_label VARCHAR(50) NULL` + `CREATE INDEX ix_segments_topic_label ON transcript_segments(topic_label)`
- [x] 1.3 Up: `ALTER TABLE shows ADD COLUMN segment_categories JSONB NOT NULL DEFAULT '[]'`
- [x] 1.4 Up: `ALTER TABLE tokenizer_custom_terms ADD COLUMN is_show_name BOOLEAN NOT NULL DEFAULT false`
- [x] 1.5 Down: drop in reverse order（topic_label / segment_categories / is_show_name）
- [x] 1.6 SQLAlchemy models update: `transcript_segment.py`（topic_label）/ `show.py`（segment_categories JSONB）/ `tokenizer_term.py`（is_show_name）
- [x] 1.7 Run migration locally against fresh PG; alembic upgrade + downgrade clean

## 2. Two-layer retrieval

- [x] 2.1 Add `route_episodes(db, show_id, query_embedding, k=10) -> list[uuid.UUID]` 在 `backend/app/services/rag.py`，純 SQL 對 `episode_description_chunks` 做 cosine top-k，JOIN episodes 限 show_id
- [x] 2.2 Add `_should_skip_routing(question: str) -> bool`：jieba tokens of length ≥ 2 的數量 < 2 → True
- [x] 2.3 Modify `retrieve_hybrid()` 加 `episode_id_filter: list[uuid.UUID] | None = None` 參數，將 transcript / description CTE 的 WHERE 加 `e.id IN :filter`（join 到 episodes）
- [x] 2.4 Modify `retrieve()` / `retrieve_descriptions()` 同步加 `episode_id_filter` 支援
- [x] 2.5 Add `DESCRIPTION_CAP = 3` named constant in rag.py；在 `retrieve_hybrid` merge 後實作 cap 邏輯（含 transcript 不夠時放寬規則）
- [x] 2.6 Modify `query.py` `/search` 與 `/query` 兩 endpoint 流程：embed → `_should_skip_routing` 判斷 → 必要時 `route_episodes` → `retrieve_hybrid(..., episode_id_filter=...)`
- [x] 2.7 Unit tests `backend/tests/test_route_episodes.py`：單 show 162 集回 top-10、show_id 過濾、空 description fallback
- [x] 2.8 Unit tests for cap behaviour in `tests/test_rag_rrf.py`：spec example 表（5 description 開頭 → 留 3 個 + 補 transcript）

## 3. Tokenizer dict show-name flag + 1-char filter 移除

- [x] 3.1 Modify `_build_ts_query` in rag.py：移除 `if len(tok) < 2: continue`；保留 whitespace + pure-punct filter
- [x] 3.2 Modify `tokenizer.py`：`_loaded_show_name_terms: set[str]` 模組變數；`load_dictionary` / `reload_dictionary` 同時填這個 set；export `get_show_name_terms() -> set[str]`
- [x] 3.3 Modify `_build_ts_query`：query 端從輸出 tokens 過濾掉 `tokenizer.get_show_name_terms()` 內的詞（embedding 端不變）
- [x] 3.4 Modify `app/schemas/tokenizer.py`：`TokenizerTermCreate` 加 `is_show_name: bool = False`；`TokenizerTermResponse` 加 `is_show_name: bool`
- [x] 3.5 Modify `app/api/admin/tokenizer.py`：`POST /admin/tokenizer/terms` body 接受 `is_show_name`；新增 `PATCH /admin/tokenizer/terms/{id}` 改 flag
- [x] 3.6 Modify `src/AdminTokenizerTab.jsx`：列表多一個 column 顯示 `is_show_name` checkbox；新增詞 form 加 checkbox；checkbox 改變呼叫 PATCH
- [x] 3.7 Unit tests `backend/tests/test_tokenizer_show_name_filter.py`：show-name token 從 ts_query 過濾、reload 後 flag 變動生效、embedding 不受影響
- [x] 3.8 Unit tests update existing `test_admin_tokenizer.py`：PATCH endpoint、create with is_show_name

## 4. Topic segmentation pipeline

- [x] 4.1 Create `backend/app/services/topic_segmentation.py`：定義 `UNIVERSAL_LABELS` constant + `build_classification_prompt(show, segments)` + `classify_episode(db, episode_id) -> dict[segment_id, label]`
- [x] 4.2 LLM prompt: 給通用 8 類 + show 的 segment_categories union；要求 JSON 輸出 `{segment_id: label}`；單選；short segment（< 5s）跟前一段同 label 規則寫進 prompt
- [x] 4.3 LLM call 走 ai_step_resolver `summary` step（gpt-4o-mini 已配置）；structured output JSON mode
- [x] 4.4 結果 UPDATE `transcript_segments.topic_label`；驗證每個 label 在 (universal ∪ show extension) 內，不合法 fallback to `topic_main` + warning log
- [x] 4.5 Add `backend/scripts/backfill_topic_labels.py`：CLI `--all` / `--episode-id`；per-episode try/except continue；progress + summary
- [x] 4.6 Unit tests `backend/tests/test_topic_segmentation.py`：prompt 包含 show extensions、unknown label fallback、short segment 跟前一段同 label

## 5. Admin audit endpoint + UI

- [x] 5.1 Create `backend/app/schemas/topic_seg.py`：`AuditSampleItem` schema（segment_id / episode_id / start_time / end_time / text / topic_label / prev_text / next_text / is_show_specific_label / episode_title）
- [x] 5.2 Create `backend/app/api/admin/topic_seg.py`：`GET /admin/topic-seg/audit-sample?n=<int>`；require_admin；隨機 sample non-null topic_label；JOIN 取上下文 + episode_title；計算 is_show_specific_label
- [x] 5.3 Wire `topic_seg_router` 進 `backend/app/api/admin/__init__.py` include_router
- [x] 5.4 Create `src/AdminTopicSegAuditTab.jsx`：fetch endpoint，列表三行排版（prev / target+badge / next），label badge show-specific 用不同顏色，「重抽樣」button
- [x] 5.5 Wire `admin-topic-seg-audit` 路由進 `AdminPage.jsx` pages map + h1 label dict；加進 `Shared.jsx` adminItems sidebar；`index.html` 引入 jsx
- [x] 5.6 Unit tests `backend/tests/test_admin_topic_seg.py`：default n=50、n>200 clamp、non-admin 403、is_show_specific_label 計算正確

## 6. Eval runner --metric-level

- [x] 6.1 Modify `backend/eval/runners/run.py`：argparse 加 `--metric-level {episode,chunk}` default=`episode`
- [x] 6.2 Implement episode-level matching：抓 retrieved chunk 的 episode_id 跟 anchor episode_id 集合對；忽略 `--match-window-s`
- [x] 6.3 Output JSON 加 `metric_level` 欄；summary markdown row label 加 `(episode)` / `(chunk)` 後綴
- [x] 6.4 Unit tests `backend/tests/test_eval_metric_level.py`：episode 模式跨 source 算 hit、chunk 模式維持 R3.1 行為

## 7. Stage 2 — deploy + carry-over data

- [ ] 7.1 Push所有 code 到 main，redeploy backend / worker / dispatcher / beat
- [ ] 7.2 SQL UPDATE prod：`UPDATE shows SET segment_categories = '[{"name":"playlist_segment","desc":"介紹歌曲、歌單環節"},{"name":"live_performance","desc":"來賓現場演唱"}]' WHERE title LIKE '%這又沒有很屌%'`
- [ ] 7.3 SQL UPDATE prod：把 dict 中已知節目名 / 大主題詞 flag is_show_name=true（候選：「這又沒有很屌」「大嘻哈時代」「異世界美食家」「呱吉」要看是節目主還是節目名再決定）
- [ ] 7.4 Verify prod schema：`transcript_segments.topic_label` exists nullable；`shows.segment_categories` 「這又沒有很屌」row 已寫入；`tokenizer_custom_terms` is_show_name 標記正確

## 8. Stage 3 — topic seg backfill

- [ ] 8.1 Run `python -m scripts.backfill_topic_labels --all` against prod via zeabur exec；估時 30-60 min
- [ ] 8.2 Verify counts：`transcript_segments WHERE topic_label IS NOT NULL` count = 全 segments count（< 1% 失敗 OK）
- [ ] 8.3 用 admin UI 抽 50 段審核 LLM 標籤；記錄錯誤類型（譬如 sponsor 沒抓到 / playlist_segment 漏標）到 case study

## 9. Stage 4 — eval + 收尾

- [ ] 9.1 Run `python -m backend.eval.runners.run --dataset backend/eval/datasets/this-not-that-cool.json --backend-url https://api.podcastrag.app --top-k 5 --metric-level=episode --skip-judge --out-dir backend/eval/runs/r32-post`
- [ ] 9.2 對照 R3.1 final（episode-level Recall@5 = 23.8%）vs R3.2 數字；目標 ≥ 35%
- [ ] 9.3 Append 結果到 `docs/case-studies/r31-hybrid-retrieval-rollout.md` 或新開 R3.2 case study
- [ ] 9.4 Run full backend pytest 全綠（`cd backend && python -m pytest -q`）
- [ ] 9.5 Gitleaks pre-check + commit + push 到 main
- [ ] 9.6 Backend-tests CI workflow + gitleaks CI 綠
- [ ] 9.7 Add release log v1.5 entry「先選集再找段：問答時自動鎖定相關集數」
- [ ] 9.8 Archive `r3-2-two-layer-topic-seg` via `spectra archive`；specs synced
