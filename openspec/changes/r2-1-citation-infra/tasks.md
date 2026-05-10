## 1. Backend response shape

- [x] 1.1 Add a SQL helper that returns the up to two preceding and two following `transcript_segments` for a given chunk's middle region — implements Decision 1: before/after_text 採前後各 2 個 segment 的 text 拼接
- [x] 1.2 Add a `ts_headline()` call against the same jieba-backed tsvector configuration used by RRF retrieval, returning a fragment with `<mark>` tags only — implements Decision 2: highlights 用 PostgreSQL ts_headline()
- [x] 1.3 Extend the search/query response serialiser so every result entry carries `before_text`, `after_text`, `highlights`, and `ai_summary_excerpt` — fulfils requirement "Search and query responses include context, highlights, and AI summary excerpt"
- [x] 1.4 Add the top-level `sources_schema_version: 1` field to both `/search` and `/query` responses
- [x] 1.5 Ensure description-source entries return empty `before_text`/`after_text` and that highlights are computed against the description text
- [x] 1.6 Ensure `ai_summary_excerpt` truncates to 60 characters with a single `…` suffix and returns empty string when the episode has no `ai_summary`
- [x] 1.7 Write `backend/tests/test_rag_query_response_shape.py` covering the response-shape scenarios from the rag-query delta spec (transcript context, first chunk empty before_text, description empty context, highlight wrapping, ai_summary truncation, schema version)

## 2. LLM prompt and citation contract

- [x] 2.1 Rewrite the answer prompt in `backend/app/services/llm_prompts.py` to enumerate sources as `[1] [2] [3]…` and to require a bracketed reference token at the end of every factual sentence — implements Decision 4: LLM citation 用 ref id 編號 + 後端嚴格 strip
- [x] 2.2 Add the bilingual refusal directive (zh: 找不到相關內容，請改用其他關鍵字 / en: No relevant content was found. Please try different keywords.) and the no-fabrication clause — fulfils requirement "LLM answer prompt enforces citation, faithfulness, and refusal"
- [x] 2.3 Update the JSON schema instruction to keep `answer` and `used_chunk_ids` fields exactly as before (no breaking change to existing parser)
- [x] 2.4 Add a unit test that snapshots the rendered prompt template for a fixture of three sources with both `lang=zh` and `lang=en` so future prompt drift is caught in review

## 3. Citation parser

- [ ] 3.1 Implement `backend/app/services/citation_parser.py` with `parse(answer_text: str, num_sources: int)` returning `(cleaned_answer, citations_meta)` — implements Decision 4 (the strip half)
- [ ] 3.2 Implement bracket-token extraction supporting both single `[N]` and multi `[N,M,...]` forms; tokens whose every component is in `1..num_sources` are kept, otherwise the whole token is removed — fulfils requirement "Citation parser strips invalid refs and degrades gracefully"
- [ ] 3.3 Implement sentence splitting on `。 ！ ？ . ! ?` and produce `citations_meta` mapping each sentence's `sentence_index` to the list of valid `ref_ids` that appeared inside it
- [ ] 3.4 Wire the parser into `/query` immediately after the answer model returns, before the response is serialised; ensure the `citations` array (built from `used_chunk_ids`) is unchanged so the frontend can still render source cards even when `citations_meta` ref_ids are all empty
- [ ] 3.5 Write `backend/tests/test_citation_parser.py` covering: valid single ref, out-of-range ref stripped, multi-ref with one invalid component dropped entirely, empty input yields empty meta, no brackets at all yields per-sentence empty meta

## 4. TranscriptPage deep-link receiver

- [ ] 4.1 In `src/TranscriptPage.jsx`, parse `window.location.search` for `t=<seconds>` on mount — implements Decision 3: deep-link 採純秒數 URL（?t=252.6）+ 不自動播放
- [ ] 4.2 Implement closest-segment search within ±5 seconds of the parsed `t`; scroll the matched segment into view and apply a 3-second highlighted background that fades out — fulfils requirement "Citation click navigates to transcript with highlight"
- [ ] 4.3 When no segment falls in the ±5 second window, scroll to the top of the transcript and skip the highlight; do not emit an error
- [ ] 4.4 Update QueryPage's `<SourceCard>` (in `src/Shared.jsx` if shared, or inline) so the jump button writes `?t=<seconds>` into the navigation URL when the page changes to TranscriptPage
- [ ] 4.5 Set the jump button label to `跳到這段內容` when `lang === 'zh'` and `Jump to transcript` when `lang === 'en'` — implements Decision 6: 雙語 UI 文字採內嵌 i18n key 模式

## 5. SourceCard rendering

- [ ] 5.1 Update `<SourceCard>` to render the new `highlights` field via React `dangerouslySetInnerHTML` after a strict whitelist sanitiser that rejects every tag other than `<mark>`
- [ ] 5.2 Render `before_text` and `after_text` as muted-colour spans surrounding the chunk's main text, visually conveying the `…前句…[hit]…後句…` layout
- [ ] 5.3 Render `ai_summary_excerpt` on its own row with a `「展開」/`Show more` link that toggles the full summary; respect bilingual labels per Decision 6: 雙語 UI 文字採內嵌 i18n key 模式
- [ ] 5.4 Ensure rendering is graceful when any of the four new fields is missing or empty (older cached responses or description sources)

## 6. R1.2 evaluation gate

- [ ] 6.1 Run the R1.2 evaluation runner against the mini-set `backend/eval/datasets/this-not-that-cool.json` BEFORE deploying the prompt change, capturing baseline Faithfulness (GEval) and Answer Relevancy medians
- [ ] 6.2 Apply the prompt change in a feature branch, redeploy backend only, then rerun the runner against the same mini-set — implements Decision 5: Faithfulness 退步即不合 archive
- [ ] 6.3 Compare medians: archive is permitted only when post-change Faithfulness ≥ pre-change Faithfulness AND post-change Answer Relevancy ≥ pre-change minus 0.05; otherwise rollback the prompt change and re-evaluate adding few-shot examples (Non-Goal escape hatch)
- [ ] 6.4 Save both runs' output JSON to `backend/eval/runs/r2-1-pre/` and `backend/eval/runs/r2-1-post/` (NOT committed, per case-studies-no-commit rule); summarise the comparison in the case study `docs/case-studies/r21-citation-infra-rollout.md`

## 7. Bilingual UI text audit

- [ ] 7.1 Walk every new or modified UI string in `src/QueryPage.jsx`, `src/TranscriptPage.jsx`, and `src/Shared.jsx`, verifying each has a `lang === 'zh' ? ... : ...` ternary
- [ ] 7.2 Cover at minimum: jump button label, refusal answer fallback display, source card `「展開」/`Show more` toggle, before/after context labels — confirms compliance with CLAUDE.md bilingual rule
- [ ] 7.3 Smoke check by switching language toggle in QueryPage and TranscriptPage and confirming no English string leaks into the zh view nor vice versa

## 8. Backwards compatibility and rollback

- [ ] 8.1 Confirm older clients that ignore unknown response fields still render correctly (load latest prod frontend before backend deploy and verify queries work)
- [ ] 8.2 Document rollback procedure in the case study: revert prompt change first (Decision 5: Faithfulness 退步即不合 archive escape path), keep response shape additions (backwards-compat additive)
- [ ] 8.3 Note in case study that R4 cache (when implemented) MUST key on `sources_schema_version` to avoid serving stale entries after future shape changes

## 9. Scope confirmation and open question follow-ups

- [ ] 9.1 Confirm tasks 1-8 cover every entry under design Goals (response shape extension, prompt strengthening, citation parser strip, SourceCard upgrade, deep-link receiver, eval gate)
- [ ] 9.2 Confirm Non-Goals stay out of scope: no inline `[N]` rendering, no hover ↔ source interaction, no few-shot examples in prompt, no Redis cache integration, no mobile bottom sheet, no `citation_match_rate` dashboard
- [ ] 9.3 Decide on `[multi]` vs `[1,2,...]` notation; the spec already mandates `[N,M,...]`, but during implementation re-confirm the prompt and parser are aligned
- [ ] 9.4 Decide whether to jieba-highlight `before_text` and `after_text`; default is no per design; if R1.3 thumbs-down data later motivates it, file a follow-up change

## 10. Validation and archive readiness

- [ ] 10.1 Run `pytest backend/` and ensure all new tests in `test_citation_parser.py` and `test_rag_query_response_shape.py` pass
- [ ] 10.2 Run lint / typecheck if configured; otherwise verify backend service starts without import errors locally via `docker compose up`
- [ ] 10.3 Manual end-to-end on staging: anonymous search returns highlights + before/after; logged-in query returns answer with `[N]` refs that resolve to source cards; clicking a source jump button lands on TranscriptPage scrolled to the right segment with highlight
- [ ] 10.4 Compose Release Log v1.6 entry draft (use, what changed, why, how to use) per `feedback_release_log_style.md`; do NOT commit yet — that happens at archive time
