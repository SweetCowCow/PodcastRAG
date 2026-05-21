# Golden Set Datasets — Manifest

> **Source of truth** for what eval datasets exist. Update this file whenever a
> dataset is added, audited, promoted, or retired. Memory entries about datasets
> point HERE, they don't store the facts themselves.

Last verified: **2026-05-15** (Claude session)

## Files

| File | n | Status | Format | Last verified |
|---|---|---|---|---|
| `this-not-that-cool.json` | **30** (v3, post-promote 2026-05-15) | **Main golden set** | retrieval-eval schema | 2026-05-15 |
| `extended-multi-turn-40.json` | **34 records / 40 turns** (30 single + 4 multi-turn) | **Multi-turn extended** — only dataset with multi-turn dialogs | bakeoff schema (is_multi_turn + turns array) | 2026-05-21 |
| `_pending_review.json` | 0 (cleared after promote) | **Staging buffer**, ready for next batch | retrieval-eval schema | 2026-05-15 |
| `_judge_minisset.json` | 40 | **Judge bake-off** hand-scored set | answer + chunks + human_score | 2026-05-06 |
| `_schema.json` | 0 | JSON schema (validator), not data | – | – |

## File details

### `this-not-that-cool.json` — main golden set

- **Show**: 這又沒有很屌（`show_slug=this-not-that-cool`、`show_id=45fc2462-17cf-42f5-98a7-68fe1a222228`）
- **Created**: 2026-05-07 (v2; v1 superseded)
- **Audit**: 2026-05-13 (per `r3-5-disable-routing` archive) — removed 36 LLM-auto-generated items (壞題率 ≥ 75%, validated 4/4 broken); patched `q05-uk-drill-features`
- **Promote**: 2026-05-15 — merged 20 items from `_pending_review.json` (co-drafted 5/13 + 5/14, user reviewed in chat 5/15). v2 → v3. Backup at `this-not-that-cool.json.bak-20260515T060258Z`
- **Current composition by type** (n=30): fact 10 · comprehension 8 · cross-episode 5 · code-switch 4 · negative 3
- **eval_mode breakdown**: chunk_id 27 · enumeration 2 (q25 歌單, q26 高雄美食) · open_set_lenient 1 (q24 Leo 王 演進弧)
- **Used by**: `eval/runners/run.py` retrieval baseline; `bakeoff_entity_extractor.py` (entity-extraction LLM inputs)
- **Recall@5 baseline (n=10, pre-promote 2026-05-14)**: 0.5625 — see `docs/case-studies/r33-baseline.md`. **n=30 baseline pending** — re-run after R3.3 Phase 8 ships

### `extended-multi-turn-40.json` — multi-turn extended set

- **Show**: 同 `this-not-that-cool.json`
- **Created**: 2026-05-19（framework bake-off 期間）
- **Origin**: `backend/scripts/agentic_bakeoff/golden_set/bakeoff_40.json`（原檔保留供舊 bake-off scripts 使用），2026-05-21 複製到標準位置改名
- **Composition**: 34 record / 40 turn（26 既有 single + 4 新 single + 4 multi-turn dialogs: mt01/mt02 各 2 turn、mt03/mt04 各 3 turn）
- **Schema 差異**：每個 item 含 `is_multi_turn` flag + `turns` array（每 turn 含 `question` + tool call `required`+`acceptable` 兩 tier），跟主 eval 的 retrieval schema **不相容**，eval runner 要另寫
- **唯一用途**：驗 multi-turn ordinal carry / focused_episode pin / context retention 失敗模式（mt01「歌單有哪幾集？→ 第三集是什麼？」是經典 ordinal carry 考題）
- **Used by**: `backend/scripts/agentic_bakeoff/runner/run_prototype.py`（已 archive 的 bake-off prototype runner）
- **未來用途**: 後續 `chat-multi-turn-trace-investigation` 等 change 主要 dataset

### `_pending_review.json` — staging buffer

- **Schema gate** (per `r3-5-disable-routing` 2026-05-13 spec): main set writes require `--target-main --reviewed-by --reviewed-at`. New items land here first.
- **Current state**: empty (cleared 2026-05-15 after 20-item promote → main). Ready for next batch.
- **Last promote**: 2026-05-15 by `ssweetcoww@gmail.com`, 20 items co-drafted on 2026-05-13/14
- **Promote workflow**:
  1. Co-draft items here (one at a time, per `feedback_golden_set_co_draft_flow.md`)
  2. User reviews each in chat session
  3. Merge into main via Python (no dedicated CLI yet — done inline; record `promote` metadata block on main file with `date`/`promoted_ids`/`reviewed_by`/`reviewed_at`)
  4. Bump main `version` (v2 → v3 etc.)
  5. Clear `_pending_review.json` items for next batch

### `_judge_minisset.json` — judge bake-off (different purpose)

- **Created**: 2026-05-06
- **What it is**: 40 questions with model-generated answers + retrieved chunks + human score (1-5) on grounding quality
- **Used by**: LLM judge bake-off (which judge model gives scores closest to human ground truth) — NOT used by retrieval eval runner
- **Why kept separate**: schema differs (no `type` / `eval_mode` / `ground_truth_chunk_ids`); judging answer quality ≠ measuring retrieval recall

### `_schema.json` — JSON schema

- Validator for the retrieval-eval format. Defined per `r3-5-disable-routing`. Required fields:
  `id` · `type` · `eval_mode` · `question` · `expected_answer_keywords` · `ground_truth_chunk_ids` · `sentinel` · `source_episode_id` · `notes` (optional)

## Drift check protocol

When a new Claude session starts and the conversation touches eval / datasets:
1. Read this README first (not memory)
2. Cross-check file counts via `wc -l` or `python -c "json.load..."`
3. If file count mismatches what's documented here → update this README, don't trust stale info

## Related artifacts

- Bake-off outputs index → `docs/research/README.md` (not in git)
- AI step inventory → `docs/ai-steps.md`
- Case studies referencing this set → `docs/case-studies/` (not in git)
