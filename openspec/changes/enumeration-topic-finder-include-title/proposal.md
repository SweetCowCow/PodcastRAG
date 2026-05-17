## Why

R3.3 完成後，chat enumeration 路徑（`find_episodes_by_topic`）只查 `episode_description_chunks.text_tsvector`，沒查 `episodes.title_tsvector`。2026-05-17 q25 audit 發現 6 集（EP19 動漫歌單 / EP84 嘻哈歌單 / EP87 紀念歌單 / EP89 搖滾歌單 / EP96 夏日節拍歌單 / EP108 雷鬼歌單）的「歌單」二字只出現在標題、description 完全沒寫，導致這 6 集從 enumeration 結果整體漏掉。q25 episode_set_recall 因此停在 21/27 ≈ 0.78，無法拉到 1.0。

## What Changes

- 改寫 `find_episodes_by_topic` 的 SQL，從「只查 description chunks tsvector」改成「title_tsvector match OR description chunks tsvector match」（EXISTS-OR 形式）
- 兩個 tsvector 已經都走 jieba + simple analyzer，tsquery 共用安全
- 不引入 weight / source flag — 下游 `_compute_enumeration_episodes` 是純 set 操作，`format_enumeration_block` grounding 也不分來源
- Spec scenario 從「description tsvector @@」描述拓寬成「description OR title tsvector @@」

## Non-Goals

設計取捨已在 design.md「Alternatives / Rejected Approaches」記錄完整推理，這裡只列底線：

- 不納入 `episodes.ai_summary`（邊際救援 1/6 + 成本高 10 倍）
- 不抓 RSS 的 itunes:keywords / itunes:category（上游三個 show 全空，這條路在現實上不存在）
- 不動 `find_episodes_by_guest`（JSONB containment 獨立路徑）
- 不動 `find_episodes_by_date_range`（欄位過濾獨立路徑）
- 不動 search 路徑 / `retrieve_hybrid`（`_title_only_lexical` 已在 R3.3 三池 RRF）
- 不動 entity 抽取 / `format_enumeration_block` grounding

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `rag-query`: enumeration 路徑的 `find_episodes_by_topic` 查詢範圍從 description-only 拓寬到 description OR title；Chat endpoint 的 enumeration scenario 需同步更新

## Impact

- Affected specs: `rag-query`（modify 兩個既有 Requirement 的 scenario）
- Affected code:
  - Modified: backend/app/services/episode_finders.py（改 `_TOPIC_SQL` SQL 模板）
  - Modified: backend/tests/services/test_episode_finders.py（新增 title-only / description-only / both-match 三組測試案例）
- Affected data: 無 schema 變動、無 backfill；`episodes.title_tsvector` 已在 R3.3 Phase 8 建立並由 `sync.py:_title_tsv_expr` 同步維護
