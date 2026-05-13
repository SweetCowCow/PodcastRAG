## 1. DB schema + Alembic migration — design D1 / D2 / D6

- [x] 1.1 [spec: Description chunks carry chunking_version] 新建 Alembic revision `t8_chunking_version_description_chunks`，`down_revision = "s7f8a9b0c1d2"`，在 docstring 明寫「downgrade only safe before any v2 row exists」
- [x] 1.2 [spec: Description chunks carry chunking_version] upgrade()：`add_column chunking_version smallint NOT NULL DEFAULT 1` + `add_column chunk_index smallint NOT NULL DEFAULT 0`
- [x] 1.3 [spec: Composite unique allows (v1, v2) coexistence] upgrade()：`drop_constraint episode_description_chunks_episode_id_key` + `create_unique_constraint uq_desc_chunk_episode_version_index ON (episode_id, chunking_version, chunk_index)`
- [x] 1.4 [spec: Composite unique allows (v1, v2) coexistence] downgrade()：對稱 drop 新 unique + recreate 舊 unique + drop 兩個欄位
- [x] 1.5 本機跑 `alembic upgrade head` → `\d episode_description_chunks` 確認欄位 + constraint；跑 `alembic downgrade -1` 再 `upgrade head` 確認 round-trip

## 2. SQLAlchemy model — design D1 / D2

- [x] 2.1 [spec: Description chunks carry chunking_version] `backend/app/models/episode_description_chunk.py` 加 `chunking_version: Mapped[int]` + `chunk_index: Mapped[int]` 兩個欄位（含 server_default）
- [x] 2.2 [spec: Composite unique allows (v1, v2) coexistence] 拿掉 `episode_id` 上的 `unique=True`，改加 `__table_args__ = (UniqueConstraint("episode_id", "chunking_version", "chunk_index", name="uq_desc_chunk_episode_version_index"),)`

## 3. Retrieval：v1+v2 透明合併 — design D3

- [x] 3.1 [spec: retrieve_hybrid pools v1 and v2 description chunks] `backend/app/services/rag.py` 的 `_DESC_RRF_SQL` SELECT 子句加 `d.chunking_version`（WHERE 不動，pool 共存）
- [x] 3.2 [spec: retrieve_hybrid pools v1 and v2 description chunks] `_DESC_SEMANTIC_ONLY_SQL` 同樣加 `d.chunking_version` 進 SELECT
- [x] 3.3 [spec: ChunkHit exposes chunking_version metadata] `ChunkHit` dataclass 加 `chunking_version: int = 1` 預設值
- [x] 3.4 [spec: ChunkHit exposes chunking_version metadata] `retrieve_descriptions()` 構造 ChunkHit 時填 `chunking_version=int(row["chunking_version"])`；transcript-side ChunkHit 維持預設 1
- [x] 3.5 [spec: ChunkHit exposes chunking_version metadata] `dedup_hits()`（或 enrich_hits 對應位置）dedup key 改成 `(episode_id, chunking_version, chunk_index)`，避免同集 v1+v2 兩 hit 同 episode 在 top-K 重覆顯示

## 4. Indexer 寫入帶 version — design D4

- [x] 4.1 [spec: description indexer accepts chunking_version] `backend/app/services/description_indexer.py` 的 `index_episode_description()` signature 加 `chunking_version: int = 1, chunk_index: int = 0` keyword-only
- [x] 4.2 [spec: description indexer accepts chunking_version] UPSERT `index_elements` 改 `[episode_id, chunking_version, chunk_index]`
- [x] 4.3 [spec: description indexer accepts chunking_version] 「delete-existing-row when empty」邏輯 WHERE 加 `chunking_version = :v`，避免誤殺另一版本
- [x] 4.4 [spec: description indexer accepts chunking_version] 既有 caller（描述 backfill）保留呼叫不帶 version → 預設寫 v1，零行為差異

## 5. Cleanup CLI 腳本 — design D5

- [x] 5.1 [spec: cleanup_v1 script is idempotent and dry-run by default] 新建 `backend/scripts/cleanup_v1_description_chunks.py`，argparse `--show-id` 必填、`--execute` flag、`--force` flag
- [x] 5.2 [spec: cleanup_v1 script is idempotent and dry-run by default] 預檢查：對 show 內每集統計 v2 chunk 數，缺 v2 的集數印出來 → 沒 `--force` 就 abort exit 2
- [x] 5.3 [spec: cleanup_v1 script is idempotent and dry-run by default] dry-run（預設）只印計畫，不 DELETE
- [x] 5.4 [spec: cleanup_v1 script is idempotent and dry-run by default] `--execute` 才跑 `DELETE ... WHERE show_id = ? AND chunking_version = 1`，per-episode transactional（一集失敗回滾該集，繼續下一集）

## 6. Monitoring endpoint（可選）— design D7

- [x] 6.1 [spec: chunking-status admin endpoint reports v1/v2 breakdown] `backend/app/api/admin/chunking_status.py`（或現有 admin router 內加 handler）GET `/admin/chunking-status`，admin auth required
- [x] 6.2 [spec: chunking-status admin endpoint reports v1/v2 breakdown] 跑 design D7 提供的 SQL，回傳 per-show v1/v2/episode_total

## 7. 單元測試 — 對應所有 spec scenarios

- [x] 7.1 新建 `backend/tests/test_chunking_version_coexistence.py`
- [x] 7.2 [spec scenario: existing rows backfilled to v1] migration 上完後既有 row 全部 `chunking_version=1, chunk_index=0`
- [x] 7.3 [spec scenario: (episode, v1) and (episode, v2) coexist] 寫 v1 + 寫 v2 同 episode 不 unique violation；寫 (episode, v1, idx=0) 第二次正常 UPSERT
- [x] 7.4 [spec scenario: retrieve_hybrid returns mixed v1+v2 hits] mock DB / fixture：插入同 show 的 v1 + v2 chunks，呼叫 `retrieve_descriptions()` 確認 result 中可能同時含 v1 + v2 hit（依 score）
- [x] 7.5 [spec scenario: ChunkHit.chunking_version reflects DB value] 上述 result 每個 hit 的 `chunking_version` 屬性對齊 DB 寫入值
- [x] 7.6 [spec scenario: dedup_hits collapses same-episode multi-version] 構造 v1+v2 同 episode 都進 top-K 的情境，dedup_hits 後只剩 RRF score 較高那筆
- [x] 7.7 [spec scenario: indexer writes versioned row] `index_episode_description(..., chunking_version=2, chunk_index=3)` 寫進去後 SQL select 對應欄位是 (2, 3)
- [x] 7.8 [spec scenario: cleanup dry-run prints plan only] cleanup CLI dry-run 不修改 DB；exit code 0
- [x] 7.9 [spec scenario: cleanup safeguards against missing v2] 對缺 v2 的 show 跑 cleanup `--execute` 沒 `--force` → exit code 2 + 不執行 DELETE

## 8. 部署 + smoke

- [x] 8.1 commit + push 整 change
- [x] 8.2 Zeabur backend service redeploy → 確認 `alembic upgrade head` 跑完無錯
- [x] 8.3 Prod SQL `SELECT chunking_version, COUNT(*) FROM episode_description_chunks GROUP BY 1`，確認全部 row `(1, N)` — 沒有遺漏 backfill
- [x] 8.4 Prod `/shows/45fc2462-17cf-42f5-98a7-68fe1a222228/search?q=...` 500-free smoke
- [x] 8.5 跑 `/admin/chunking-status` 確認 endpoint 工作，pilot show v1=163 v2=0
- [x] 8.6 寫一筆 dummy (episode, chunking_version=2, chunk_index=0) row 手動進 DB（簡單 INSERT），跑 search 確認 response 結構 OK + dedup 正確；刪除 dummy 還原
- [x] 8.7 update memory `project_pending_changes.md` 對應條目（本 change archived 後一起做；現在只先 propose）
