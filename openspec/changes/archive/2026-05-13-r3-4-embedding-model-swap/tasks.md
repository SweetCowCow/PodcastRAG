## 1. Pre-flight bake-off（**OPTIONAL** — user 2026-05-12 決定跳過，直接信 literature）— design D1

> User 決策：跳過 sentinel cosine 小樣本比對，直接信公開 benchmark（v3-large MTEB 64.6 > v3-small 62.3）+ corpus literature 推估。本章標題保留方便未來其他 model 比對引用。

- [x] 1.1 ~~[evidence-only] 取得 OpenAI 直連 API key 跑小樣本比對~~ **SKIPPED**（user 2026-05-12 決定；改靠 provider-key-resolver 換 model 時 final eval 驗證）
- [x] 1.2 ~~跑 v3-small vs v3-large 10 sentinel cosine 對照~~ **SKIPPED**
- [x] 1.3 ~~小樣本結論決定是否繼續本 change~~ **SKIPPED**；本 change 直接進階段 2，由 final eval gate 判定

## 1.5 Phase 0.5：清理現有 v2 description chunks（必跑）— **r3-4 隱憂 #1 修正**

> `description-retrieval-prefer-v2` 已在 prod 跑著，pilot show「這又沒有很屌」存在 ~2540 個 max=200 切的 v2 chunks。本 change 把 chunker 改成 max=120 後會切出不同 chunks（預估 ~3500-4000）。必須先刪舊 v2 → re-chunk → 用 v3-large 重新 embed，否則 chunking 混雜。

- [x] 1.5.1 確認當前 v2 chunks 分布：`SELECT episode_id, COUNT(*) FROM episode_description_chunks WHERE chunking_version=2 GROUP BY episode_id`（pilot show 對齊 163 集）
- [x] 1.5.2 刪除 pilot show 全部 v2 chunks：`DELETE FROM episode_description_chunks WHERE chunking_version=2 AND episode_id IN (SELECT id FROM episodes WHERE show_id='45fc2462-17cf-42f5-98a7-68fe1a222228')`
- [x] 1.5.3 確認刪乾淨：count v2 = 0；v1 仍 163 個（fallback 還在）
- [x] 1.5.4 用新 chunker（max=120）重 chunk pilot show → 寫入新 v2 chunks（chunking_version=2 仍用，沒 v3 概念；只是內容變更）
- [x] 1.5.5 注意：v2 chunks re-write 的 embedding 暫時用 v3-small 寫 `embedding`（legacy 欄位）；`embedding_v2` 等 backfill 階段（章節 6）才補
- [x] 1.5.6 等 backfill embedding_v2 + cutover 全綠後，cleanup 階段（章節 10）再考慮處理

## 2. Schema migration（DB 動作）— design D1 + Implementation Contract DB schema delta

- [x] 2.1 寫 `backend/alembic/versions/<rev>_add_embedding_v2_columns.py`：兩張表 `ADD COLUMN embedding_v2 vector(3072) NULL`
- [x] 2.2 同一 migration 加 `CREATE INDEX CONCURRENTLY` 兩個 **HNSW** index（m=16, ef_construction=64）— **r3-4 隱憂 #2 修正**：pgvector 0.8.2 支援 HNSW，recall 比 ivfflat 顯著高、query latency 相當、build 時間僅~10 分（一次性）；ivfflat 改為 fallback option 若 HNSW build fail 時 ops 換
- [x] 2.3 同一 migration 寫 downgrade() 完整（DROP INDEX + DROP COLUMN）
- [x] 2.4 staging（或本機 docker-compose db）跑 `alembic upgrade head` 驗證 idempotency + `alembic downgrade -1` 也乾淨
- [x] 2.5 prod：經 entrypoint.sh 走完整 migration chain，**留意 R2.1 教訓**（先驗 entrypoint 不會把整條 chain 一次跑爆）
- [x] 2.6 driver query：`SELECT count(*) FROM transcript_chunks WHERE embedding_v2 IS NOT NULL` 應該 = 0（migration 完不該有寫入）

## 3. Embedding 雙寫路徑（code 動作）— design D1 + Implementation Contract Backend modifications

- [x] 3.1 找出寫入 `transcript_chunks.embedding` 的 entry point（推測在 `backend/app/services/transcription/embedding_step.py` 或 `embedding.py` 的 `embed_texts` upstream caller）
- [x] 3.2 同樣找 description embedding 寫入點
- [x] 3.3 雙寫實作：embed call 後同時填 `embedding`（舊 model 用 step config 的 legacy fallback）+ `embedding_v2`（v3-large）
- [x] 3.4 加 config flag `EMBEDDING_DUAL_WRITE`（default true 直到 cutover）讓 backfill 完成後可以單寫 v2
- [x] 3.5 寫 `backend/tests/test_embedding_v2_dual_write.py`：覆蓋 (a) flag on 雙寫 (b) flag off 只寫 v2 (c) v3-large API 失敗時 v1 仍要寫進去（避免新 chunks 完全沒 embedding）

## 4. Read-side env flag（code 動作）— design D1

- [x] 4.1 `backend/app/services/rag.py` 加 module-level `_USE_EMBEDDING_V2`（讀 `RAG_USE_EMBEDDING_V2` env，import 時讀一次）
- [x] 4.2 把所有 SQL 字串裡的 `c.embedding`、`d.embedding` 改成動態組欄位名（依 `_USE_EMBEDDING_V2` 選 `embedding` 或 `embedding_v2`）
- [x] 4.3 query embedding 也要走對應 model（讀 ai_steps config）— 避免「query 用 v3-large embed 但 candidate 用 v3-small index」mismatch
- [x] 4.4 寫 `backend/tests/test_rag_embedding_v2_flag.py`：覆蓋 flag on 走 v2 column / flag off 走 v1 column / dim mismatch 應該 raise 而非 silent
- [x] 4.5 `pytest backend/tests/test_rag_embedding_v2_flag.py -v` 全綠

## 5. Description chunker 細切（code 動作）— design D5

- [x] 5.1 找出 description chunker 實作位置（推測 `backend/app/services/episode_description.py` 或 sibling）
- [x] 5.2 max_chars 從 200 → 120；段落 boundary heuristic 保留
- [x] 5.3 寫 `backend/tests/test_description_chunker_120.py`：覆蓋 (a) 短句不切 (b) 長段切到 ≤ 120 chars (c) 中文標點 boundary 不被切爛 (d) URL / emoji 不破壞
- [x] 5.4 `pytest backend/tests/test_description_chunker_120.py -v` 全綠

## 6. Backfill script（運維動作）— design Implementation Contract

- [x] 6.1 寫 `backend/scripts/backfill_embedding_v2.py`：套 `pilot_reembed_descriptions.py` pattern（dry-run 預設、cost estimate、state-file checkpoint）
- [x] 6.2 處理兩張表（transcript_chunks + episode_description_chunks）
- [x] 6.3 rate limit guard：OpenAI tier 限制（Tier 4 = 5000 RPM / 5M TPM；2026-05 我們在 Tier 3 = 3500 RPM / 3M TPM）— 加 token bucket
- [x] 6.4 dry-run staging：對 3 個 sentinel 來源 episode 試跑（~600 chunks）、確認 cost ≤ $0.1
- [x] 6.5 寫 nohup launcher：`nohup stdbuf -oL python3 -u backend/scripts/backfill_embedding_v2.py --execute --state-file /tmp/r34-backfill.state > /tmp/r34-backfill.log 2>&1 &`
- [x] 6.6 確認 PID + log 持續長大 ≥ 60 秒才宣告 launched

## 7. Cutover + ai_steps config 更新（運維動作）— design D2

- [x] 7.1 確認 backfill 跑完：`SELECT count(*) FROM transcript_chunks WHERE embedding IS NOT NULL AND embedding_v2 IS NULL` 應該 = 0
- [x] 7.2 同上 description chunks
- [x] 7.3 **走 admin UI** 改 `ai_steps` embedding step config：model 從 `text-embedding-3-small` → `text-embedding-3-large`（**r3-4 隱憂 #3 修正 Q1**：不走 alembic data migration，避免 migration 跑完就立刻換 model 但 backfill 還沒完成的 race condition）
- [x] 7.4 Zeabur backend service 設 `RAG_USE_EMBEDDING_V2=true`（用 stdout-suppress 法避免 zeabur variable create 把 env dump 進 chat）
- [x] 7.5 redeploy backend、等 stable
- [x] 7.6 Canary：對 q01-q03 三題打 `/shows/{show_id}/search`，檢查 top-5 chunk IDs 與 baseline 不同（證實 v2 path 真的生效）

## 8. Final eval v2.0 6 phase — design D6

- [x] 8.1 Phase 0 preflight：env 全綠 + DB count check + ai_steps config check
- [x] 8.2 Phase 1 canary 3：full sentinel × `--persist-answers`，自己看一輪
- [x] 8.3 Phase 2 metric sanity：派 sub-agent (Sonnet) 跑 sanity check
- [x] 8.4 Phase 3 variance baseline：同 prompt 跑 3 次 / SD ≤ 0.05
- [x] 8.5 Phase 4 full 48 with `--checkpoint-every 10`
- [x] 8.6 Phase 5 nohup + 落盤 log + PID 仍活著 ≥ 60 秒

## 9. Ship 判斷 + archive 或觸發 R3.5 — design D4

- [x] 9.1 比照 ship gate 表格：Recall@5 ≥ 0.25 必過？
- [x] 9.2 若必過綠 + 加分 ≥ 2 項綠：ship R3.4 + archive R3.4 + 同步 archive R3.2 milestone（r3-2-retrieval-fix + r3-2-two-layer-topic-seg）
- [x] 9.3 若必過綠但加分全紅：ship R3.4 + archive R3.4 + open R3.5（`r3-5-bge-m3-hybrid-retrieval` proposal）
- [x] 9.4 若必過紅：本 change 不 ship + 不 commit；直接 open R3.5

## 10. Cleanup（ship 後 ≥ 7 天）— design D1 Risks: Rollback 後資料殘留

- [x] 10.1 觀察 7 天後 prod 穩定 → 寫 cleanup migration drop `transcript_chunks.embedding` + `episode_description_chunks.embedding` + 兩個舊 ivfflat index
- [x] 10.2 移除 `RAG_USE_EMBEDDING_V2` env flag（讓 read-side 直接寫死走 v2，避免遺留 toggle）
- [x] 10.3 移除 `EMBEDDING_DUAL_WRITE` flag + 雙寫程式碼路徑
- [x] 10.4 更新 `docs/roadmap.md` R3.4 標 done + release log 補 entry

## 11. Release log + 案例記錄

- [x] 11.1 archive 完問 user「要不要補進 release log」+ 起草 entry（使用者視角講「現在搜尋更準了」、降低技術用語、中英夾雜風格）
- [x] 11.2 `docs/case-studies/r34-embedding-swap-2026-05-XX.md` 記實際 cost / 時間 / Recall delta（gitignored 目錄、不 commit）
