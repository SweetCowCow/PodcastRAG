# Tasks

## 0. Coverage map (analyzer cross-reference)

This section maps every spec Requirement and design Decision to the task sections that implement it. Each item cites the verbatim title from the corresponding artifact so the consistency analyzer can match them.

**Spec Requirements covered**:
- `Chunk builder aggregates Whisper segments` (rag-query MODIFIED) — section 3
- `Semantic search endpoint returns ranked chunks` (rag-query MODIFIED) — section 4 + 7
- `Chat endpoint answers with citations using Tier 2 RAG` (rag-query MODIFIED) — section 4 + 7
- `Hybrid retrieval implemented as a single SQL CTE` (rag-query ADDED) — section 4
- `transcript_chunks tsvector column` (db-schema ADDED) — section 1
- `tokenizer_custom_terms table` (db-schema ADDED) — section 1
- `episode_description_chunks table` (db-schema ADDED) — section 1
- `Tokeniser service exposes tokenize() backed by jieba + custom dictionary` (tokenizer-dictionary ADDED) — section 2
- `Admin CRUD endpoints for tokenizer_custom_terms` (tokenizer-dictionary ADDED) — section 6
- `Seed dictionary builder script` (tokenizer-dictionary ADDED) — section 2 + 7
- `Episode description index builder cleans HTML and boilerplate` (episode-description-index ADDED) — section 5
- `Bulk indexer command processes all episodes` (episode-description-index ADDED) — section 5 + 7
- `Description chunks participate in hybrid retrieval` (episode-description-index ADDED) — section 4 + 7

**Design decisions covered**:
- `Decision 1: Chunk 重切 = 5-10 segments + 30-60s + segment-gap 切點 + 前後 1 segment overlap` — section 3
- `Decision 2: Tokenizer = jieba + DB-stored 自訂詞典 + 啟動時載入` — section 2 + 6
- `Decision 3: RRF 在純 SQL 跑，k=60，pgvector + tsvector 兩路 ROW_NUMBER` — section 4
- `Decision 4: Episode description 走另開表 + 同 retrieval 流程後 union` — section 1 + 4 + 5
- `Decision 5: Migration = 一次性砍 transcript_chunks 重建` — section 7
- `Decision 6: 業配 boilerplate strip = 規則式 + admin 可加規則` — section 5
- `Decision 7: Eval 三輪對照` — section 8

**Goals / Non-Goals respected** (from design.md `## Goals / Non-Goals`):
- goals: Recall@5 single-digit lift; cross-episode + code-switch non-zero; description in retrieval; admin can add terms in 5 min — section 8 verifies
- non-goals: LLM topic segmentation, two-tier retrieval, metadata filter, ASR fix, diarization, auto-OOV — explicitly out of section scope

## 1. Schema migration

Implements Requirement "transcript_chunks tsvector column", Requirement "tokenizer_custom_terms table", Requirement "episode_description_chunks table" (all db-schema ADDED). Supports design Decision 1, Decision 2, Decision 4.

- [x] 1.1 New alembic revision file `backend/alembic/versions/<rev>_r31_hybrid_retrieval.py`
- [x] 1.2 Up: `ALTER TABLE transcript_chunks ADD COLUMN text_tsvector tsvector NULL` + `CREATE INDEX ix_chunks_text_tsvector ON transcript_chunks USING GIN(text_tsvector)`
- [x] 1.3 Up: create table `tokenizer_custom_terms` per spec (term UNIQUE, weight default 100, source, created_at, created_by_user_id FK to users)
- [x] 1.4 Up: create table `episode_description_chunks` per spec (one-row-per-episode UNIQUE, text, text_tsvector, embedding vec(1536), created_at, updated_at) + GIN index `ix_desc_text_tsvector` + ivfflat index `ix_desc_embedding` (lists=100, vector_cosine_ops)
- [x] 1.5 Down: drop table episode_description_chunks → drop table tokenizer_custom_terms → drop index ix_chunks_text_tsvector → drop column transcript_chunks.text_tsvector
- [x] 1.6 SQLAlchemy models: `backend/app/models/tokenizer_term.py` + `backend/app/models/episode_description_chunk.py`; update `backend/app/models/transcript_chunk.py` (add text_tsvector column) + `backend/app/models/episode.py` (relationship)
- [x] 1.7 Run migration locally against fresh PG; alembic upgrade + downgrade both clean

## 2. Tokenizer service + DB-stored dictionary

Implements Requirement "Tokeniser service exposes tokenize() backed by jieba + custom dictionary" and Requirement "Seed dictionary builder script" (tokenizer-dictionary ADDED). Supports design Decision 2.

- [x] 2.1 `backend/requirements.txt`: add `jieba==0.42.1`
- [x] 2.2 Create `backend/app/services/tokenizer.py` exporting `tokenize(text: str) -> list[str]`, `reload_dictionary(db)`, internal `_load_from_db(db)` that runs at module import (lazy: first `tokenize()` call triggers load if not loaded)
- [x] 2.3 Implement `tokenize()` to strip whitespace, then `list(jieba.cut(text, cut_all=False))`, returning non-empty tokens only
- [x] 2.4 Implement `_load_from_db()`: query `tokenizer_custom_terms` rows, call `jieba.add_word(term, weight)` for each
- [x] 2.5 Implement `reload_dictionary()`: clear jieba's user-added words by iterating prior loaded terms and calling `jieba.del_word(term)`, then re-run `_load_from_db()`. Track loaded terms in a module-level set
- [x] 2.6 Unit tests in `backend/tests/test_tokenizer.py`: tokenize without dict baseline; tokenize "迪拉胖" splits into 3 chars without dict; after `add_word("迪拉胖")` it's 1 token; reload picks up new DB rows
- [x] 2.7 `backend/scripts/build_jieba_seed_dict.py`: scan all `transcript_segments.text` for substrings of length 2-5 that (a) appear ≥ 10 times across the corpus, (b) are not split by jieba's default tokeniser into a single token. Output CSV `docs/jieba_seed_candidates.csv` ordered by descending count, columns `[term, occurrences, sample_episode_titles]` (up to 3 titles)
- [x] 2.8 `backend/scripts/import_jieba_seed.py`: `--csv <path>` reads curated CSV, INSERTs rows with `source='seed_script'`, skips on duplicate without failing whole import, prints summary
- [x] 2.9 Tests for the seed scripts in `backend/tests/test_jieba_seed_scripts.py` (mock corpus, assert CSV ordering + duplicate-skip)

## 3. Overlap-aware chunk builder

Implements Requirement "Chunk builder aggregates Whisper segments" (rag-query MODIFIED). Supports design Decision 1.

- [x] 3.1 Modify `backend/app/services/chunking.py`: replace `MAX_SEGMENTS_PER_CHUNK = 5` / `MAX_CHUNK_DURATION_SECONDS = 60.0` with `MIN_MIDDLE_SEGMENTS = 5`, `MAX_MIDDLE_SEGMENTS = 10`, `MIN_MIDDLE_DURATION_SECONDS = 30.0`, `MAX_MIDDLE_DURATION_SECONDS = 60.0`, `NATURAL_GAP_SECONDS = 1.5`, `OVERLAP_BEFORE = 1`, `OVERLAP_AFTER = 1`
- [x] 3.2 Reshape `ChunkDraft` to carry a `middle_start_idx` and `middle_end_idx` referring to positions in the full segments list (so we can build text with overlap)
- [x] 3.3 Implement the new `build_chunks()` algorithm: walk segments, accumulate middle, close on (a) max-segments, (b) max-duration, (c) min-conditions met AND next gap > NATURAL_GAP_SECONDS, (d) end-of-input
- [x] 3.4 Implement `_build()` to produce `text` with one preceding + middle + one trailing overlap segment (clamped to corpus boundaries) joined by single space; `segment_ids` only for middle; `start_time/end_time` from middle bounds
- [x] 3.5 Unit tests in `backend/tests/test_chunking_overlap.py` covering each spec scenario: max-segments closure, max-duration closure, natural-gap closure, overlap context appended (Example block values), first chunk has no preceding overlap, last chunk has no trailing overlap, trailing partial flushed

## 4. Hybrid retrieval (RRF) SQL

Implements Requirement "Hybrid retrieval implemented as a single SQL CTE" (rag-query ADDED), Requirement "Semantic search endpoint returns ranked chunks" (rag-query MODIFIED), Requirement "Chat endpoint answers with citations using Tier 2 RAG" (rag-query MODIFIED), and Requirement "Description chunks participate in hybrid retrieval" (episode-description-index ADDED). Supports design Decision 3, Decision 4.

- [x] 4.1 Modify `backend/app/services/rag.py`: add named constants `RRF_K = 60`, `RRF_PER_SIDE = 50`. Keep `RETRIEVAL_TOP_K = 8`
- [x] 4.2 Replace `retrieve()` body with the single-CTE SQL from design D3 (semantic CTE, lexical CTE, FULL OUTER JOIN, RRF combine, ORDER BY rrf_score DESC LIMIT k)
- [x] 4.3 Build the lexical query string from the user question via `tokenizer.tokenize(question)` + `' & '.join(tokens)` + `to_tsquery('simple', ...)`. Strip jieba tokens that are pure punctuation or single-character non-Chinese
- [x] 4.4 Add a parallel `retrieve_descriptions()` function that runs the same RRF CTE against `episode_description_chunks` (filter by `episodes.show_id` via JOIN); same shape of results but with `source='description'` in `ChunkHit`
- [x] 4.5 Modify `ChunkHit` dataclass: add `source: Literal['transcript','description']` field, default `'transcript'`. Description hits SHALL set `start_time=0.0` and `end_time=0.0` and a flag clients can use to skip "play from this time" UI affordances
- [x] 4.6 Add a top-level `retrieve_hybrid()` that calls both `retrieve()` and `retrieve_descriptions()`, merges the two ranked lists by `rrf_score DESC`, deduplicates by `chunk_id`, returns top `RETRIEVAL_TOP_K`
- [x] 4.7 Modify the endpoint handlers in `backend/app/api/query.py` to call `retrieve_hybrid()` instead of `retrieve()`
- [x] 4.8 Modify `answer_with_chunks()` prompt builder: prefix transcript hits with `ep:<episode_id>@<start_time>` (existing) and description hits with `desc:<episode_id>` (new). Update the system prompt example to include both forms
- [x] 4.9 Unit tests in `backend/tests/test_rag_rrf.py`: mock DB, assert RRF math with the spec Example values; one-side-only result computed with placeholder rank 999; no-external-retrieval-lib import-scan check (grep `backend/` for forbidden imports)

## 5. Episode description indexer

Implements Requirement "Episode description index builder cleans HTML and boilerplate" and Requirement "Bulk indexer command processes all episodes" (both episode-description-index ADDED). Supports design Decision 4, Decision 6.

- [x] 5.1 Create `backend/app/services/description_indexer.py` exporting `build_description_index_for_episode(db, episode_id)` and module-level `BOILERPLATE_PATTERNS: list[str]`
- [x] 5.2 Implement HTML strip using `html.parser` (stdlib) — not a heavy library; flatten `<a>` to text content, drop script/style content, normalise whitespace
- [x] 5.3 Implement boilerplate strip: split text by newlines, drop lines matching any pattern (case-insensitive), rejoin with `\n`. Initial seed list: `[r'.*鼓勵.*贊助.*', r'.*按讚訂閱.*', r'.*歡迎收聽下集.*']`
- [x] 5.4 Log warning if strip removed > 50% of original chars (one log line per episode) for boilerplate audit
- [x] 5.5 Skip-and-delete branch: if cleaned text is empty/whitespace, delete any existing row for that episode
- [x] 5.6 UPSERT branch: jieba tokenize → text_tsvector, OpenAI embed (single API call), INSERT … ON CONFLICT DO UPDATE on `episode_id` UNIQUE, set `updated_at=now()`
- [x] 5.7 `backend/scripts/build_description_index.py`: CLI accepts `--all` or `--episode-id`, batches embedding calls in groups of 64, prints batch progress + final summary `inserts=N updates=M skips=K errors=E`
- [x] 5.8 Implement RateLimitError retry with exponential backoff (2s/4s/8s, max 3 attempts per batch)
- [x] 5.9 Unit tests in `backend/tests/test_description_indexer.py`: HTML strip with anchor flatten; boilerplate line removal; empty-after-clean deletes existing row; re-run UPSERTs not duplicates; > 50% strip warning logged

## 6. Admin tokenizer UI + endpoints

Implements Requirement "Admin CRUD endpoints for tokenizer_custom_terms" (tokenizer-dictionary ADDED). Supports design Decision 2.

- [x] 6.1 `backend/app/schemas/tokenizer.py`: Pydantic models for list / create / response
- [x] 6.2 `backend/app/api/admin/tokenizer.py`: GET / POST / DELETE / reload endpoints, all gated by `require_admin`
- [x] 6.3 Reload endpoint dispatches a Celery broadcast task `app.workers.tokenizer_reload.broadcast_reload` that calls `reload_dictionary()` in each consumer process
- [x] 6.4 Wire `tokenizer_reload` into `celery_app.py` include list
- [x] 6.5 Unit tests in `backend/tests/test_admin_tokenizer.py`: list / create / duplicate-409 / delete / non-admin-403 / reload-202
- [x] 6.6 Frontend: new `src/AdminTokenizerTab.jsx` element — list table with delete button, "add term" form, "reload now" button. Wire into `src/AdminPage.jsx` route `admin-tokenizer`

## 7. Backfill: rebuild transcript chunks + build description index

Supports design Decision 5 migration plan. Drives Requirement "Bulk indexer command processes all episodes" (episode-description-index ADDED) end-to-end against prod and prepares the new "Semantic search endpoint returns ranked chunks" / "Chat endpoint answers with citations using Tier 2 RAG" runtime path (rag-query MODIFIED).

- [x] 7.1 `backend/scripts/rebuild_chunks.py`: CLI accepts `--all` (every transcript) or `--transcript-id <UUID>`. For each transcript: read segments → run new chunking algorithm → DELETE existing chunks for that transcript_id → INSERT new chunks (with text_tsvector populated via tokenizer) inside one transaction → batch embed (64 chunks/call) and UPDATE embeddings
- [x] 7.2 Print batch progress + final `transcripts=N chunks_deleted=A chunks_inserted=B chunks_embedded=C errors=E`. Resilient to partial failure: log error and continue to next transcript
- [x] 7.3 Unit test in `backend/tests/test_rebuild_chunks.py` against a fixture transcript: assert old chunks deleted, new chunks have non-null text_tsvector, embeddings filled
- [x] 7.4 Manual prod run prep: review script invocations + estimate runtime + confirm openai key budget < $1
- [x] 7.5 Run `python -m backend.scripts.import_jieba_seed --csv <curated>.csv` against prod (after § 2.7-2.8 produces curated CSV)
- [x] 7.6 Run `python -m backend.scripts.rebuild_chunks --all` against prod (zeabur service exec)
- [x] 7.7 Run `python -m backend.scripts.build_description_index --all` against prod
- [x] 7.8 Verify counts: `transcript_chunks` row count is plausible (expect ~300K-450K with the new chunking); `episode_description_chunks` count equals episodes-with-non-empty-description count

## 8. Eval — three rounds + iterate

Supports design Decision 7. Validates that the new RRF retrieval (rag-query MODIFIED + ADDED) and description index (episode-description-index ADDED) produce the goal Recall@5 lift over the R1.2 baseline of 2.4%.

- [x] 8.1 Run R1.2 eval baseline against prod BEFORE deploying R3.1 (sanity recheck of 2.4% Recall@5; saves to `backend/eval/runs/r31-pre.jsonl`)
- [x] 8.2 Deploy R3.1 (sections 1-7 done) to prod via `git push` + redeploy 4 services
- [x] 8.3 Run R1.2 eval after deploy (no further dict curation): `backend/eval/runs/r31-post.jsonl`
- [x] 8.4 Inspect failure cases: for each Recall@5 = 0 question, check whether retrieval returned the expected chunk in any rank. Identify which OOV terms (if any) the question depends on
- [ ] 8.5 Curate ~10-30 additional dict terms based on §8.4, import + reload, then re-tokenize affected chunks (subset of `rebuild_chunks` scoped to those transcripts)
- [x] 8.6 Run R1.2 eval third time: `backend/eval/runs/r31-post-dict-iter.jsonl`
- [x] 8.7 Compare three runs: produce a diff report (counts, deltas, per-category breakdown) saved to `docs/research/r31-eval-results.md` (not committed per case-studies-no-commit rule but referenced from release log)

## 9. Stage gate / archive

- [x] 9.1 `cd backend && python -m pytest tests/test_tokenizer.py tests/test_chunking_overlap.py tests/test_rag_rrf.py tests/test_description_indexer.py tests/test_admin_tokenizer.py tests/test_rebuild_chunks.py tests/test_jieba_seed_scripts.py -v` all green
- [x] 9.2 Full backend pytest 全綠 (existing tests not broken by chunking signature change)
- [x] 9.3 Lint / format pass on new modules
- [x] 9.4 Gitleaks pre-check + commit + push to `main`
- [x] 9.5 Backend-tests CI workflow + gitleaks CI green
- [x] 9.6 Add release log v1.4 entry「混合檢索上線：抓到節目主寫的 entity」, summarise eval delta from §8.7
- [ ] 9.7 Archive `r3-1-hybrid-retrieval` via `spectra archive`; specs synced into `openspec/specs/`
