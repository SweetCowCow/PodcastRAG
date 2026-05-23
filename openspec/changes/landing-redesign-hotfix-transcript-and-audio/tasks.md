## 1. Extend aggregateParagraphs util with two new split conditions

- [x] 1.1 Read `src/utils/aggregateParagraphs.js` end-to-end to confirm current loop structure (the `for (let i...)` block, the `flush()` helper, the `cur` accumulator). No edits yet.
- [x] 1.2 Add `max_paragraph_seconds` (default 45) and `min_paragraph_seconds` (default 15) to the `opts` parsing block at the top of `aggregateParagraphs`. Document each option in the JSDoc-style comment block at the file head.
- [x] 1.3 Inside the per-segment loop, after the existing `gap >= gapThreshold || speakerChanged` check, add condition (c): when `(cur.end_time - cur.start_time) >= max_paragraph_seconds`, flush and start a new paragraph using the current segment. Place this check BEFORE condition (d) so the hard ceiling wins ties.
- [x] 1.4 Add condition (d): when the last character of `cur.paragraph_text` is in the set `。！？.!?` AND `(cur.end_time - cur.start_time) >= min_paragraph_seconds`, flush and start a new paragraph. Use a single regex `/[。！？.!?]$/` test.
- [x] 1.5 Ensure the four split conditions are evaluated in order (a) → (b) → (c) → (d) with first-match-wins. Confirm no double-flush by code inspection.

## 2. Cover the new util behavior with a Node-runnable test fixture

- [x] 2.1 Create `src/utils/aggregateParagraphs.test.js` that `require`s the util (the file already has `module.exports = aggregateParagraphs` at line 95).
- [x] 2.2 Add Fixture A: 5 segments, all `speaker: null`, `end(prev) == start(next)` (gap=0), total 60 seconds, third segment ends with `。` at cumulative ~30 seconds. Assert paragraph count `>= 2` and the boundary lands after the `。`-ending segment.
- [x] 2.3 Add Fixture B: 3 segments with speaker transitions A → B → A. Assert exactly 3 paragraphs and each `segment_ids` array length === 1.
- [x] 2.4 Add Fixture C: 30 segments, total 200 seconds, all `speaker: null`, gap=0, no sentence-end punctuation. Assert paragraph count `>= 4` (200 / 45 ceiling).
- [x] 2.5 Add Fixture D: `aggregateParagraphs([])` returns `[]` without throwing; `aggregateParagraphs(null)` returns `[]`.
- [x] 2.6 Add Fixture E (regression for current bug): 2512 segments mimicking real Whisper output — all `speaker: null`, `end(prev) == start(next)`, total ≈ 4800 seconds. Assert paragraph count `>= 20`.
- [x] 2.7 At the top of the test file, add a one-line comment: `// run: node src/utils/aggregateParagraphs.test.js`. Use `node:assert/strict` for assertions (no external deps).
- [x] 2.8 Run `node src/utils/aggregateParagraphs.test.js` locally and confirm all 5 fixtures pass with exit code 0.

## 3. Create stripHtml plain-text sanitizer util

- [x] 3.1 Create `src/utils/stripHtml.js` following the same IIFE + `window.stripHtml` + `module.exports` export pattern used in `src/utils/aggregateParagraphs.js`.
- [x] 3.2 Implement `stripHtml(input)`:
  - Return `''` when input is `null` / `undefined` / not a string
  - Replace `/<br\s*\/?>/gi` with `\n`
  - Remove all remaining tags via `/<[^>]+>/g`
  - Decode common HTML entities: `&amp; &lt; &gt; &quot; &#39; &#x27; &nbsp; &apos;` → `& < > " ' ' (non-breaking space U+00A0) '`
  - Decode numeric entities `&#NNN;` and `&#xHEX;` via `String.fromCharCode`
- [x] 3.3 Add file-head comment block: purpose, "plain-text only, NOT XSS-safe", and example input/output.
- [x] 3.4 Register the new script in `index.html` immediately after the existing `<script src="src/utils/aggregateParagraphs.js?v=1"></script>` line.
- [x] 3.5 Add a sibling `src/utils/stripHtml.test.js` covering: null input → ''; `<p>hi<br />world</p>` → `hi\nworld`; `&amp;` → `&`; `&#39;` → `'`; nested `<a href='x'>link</a>` → `link`. Run `node src/utils/stripHtml.test.js` and confirm exit 0.

## 4. Fix TranscriptPage "從此處播放" button render condition

- [x] 4.1 Read `src/TranscriptPage.jsx` lines 25-30 (audio hook) and 135-147 (button JSX) to confirm current shape.
- [x] 4.2 Modify the button JSX so the render condition becomes `episode && episode.audio_url` (drop the `audio &&` guard). Add `disabled={!audio}` to the `<Btn>` props.
- [x] 4.3 Wrap the `onClick` body in a `if (!audio) return;` early-return so disabled state cannot trigger playback even if click somehow fires.
- [x] 4.4 Add a single `console.log('[transcript-play]', { hasAudio: !!audio, hasEpisode: !!episode, hasUrl: !!episode?.audio_url, paragraphsLen: paragraphs?.length })` at the start of the `onClick` handler for one prod deploy cycle. Plan to remove this log in the archive PR after root cause is captured.
- [x] 4.5 After deploy, open TranscriptPage in chrome-devtools, confirm the button is in the DOM via `document.querySelectorAll('button')` snapshot. If disabled, click once and capture the console line to identify which condition is falsy.

## 5. Fix HomePage ShowCard description raw HTML leak

- [x] 5.1 Locate the ShowCard component definition. Start with `grep -rn "const ShowCard\|function ShowCard" src/ index.html`. ShowCard is referenced as `<ShowCard>` in `src/HomePage.jsx:156` but its source file may be in a build-cached location — confirm whether a `src/PodcastSelect.jsx` still ships or whether ShowCard was inlined into another file during landing-redesign.
- [x] 5.2 In the ShowCard description render line (currently `{show.description}` per archived PodcastSelect.jsx history), replace with `{stripHtml(show.description)}`. If the ShowCard component cannot be located in current `src/`, recreate a minimal inline ShowCard inside `src/HomePage.jsx` matching the visual contract from `openspec/specs/home-page/spec.md` (cover image / title / language / description / counts / progress / RSS URL / 進入節目 link) and use `stripHtml` for description.
- [x] 5.3 Preserve `white-space: pre-wrap` (or equivalent) on the description container so `\n` from stripHtml's `<br />` conversion renders as a visible line break.

## 6. Verify B3 deep-link scroll auto-resolves after B1 fix

- [x] 6.1 With B1 (multi-paragraph aggregation) merged locally, run `node src/utils/aggregateParagraphs.test.js` and `node src/utils/stripHtml.test.js` — both must exit 0.
- [x] 6.2 Read `src/TranscriptPage.jsx:68-99` (the existing `deepLinkSecondsRef` + closest-segment + ±5 second window logic). Confirm the logic operates on `segments` (not `paragraphs`); if so, no code change is needed for B3 — verification only.
- [x] 6.2a Fix `parseInt(sid, 10)` UUID lookup bug in paragraph render. `src/TranscriptPage.jsx:268` currently uses `parseInt(sid, 10)` to convert `segment_ids` strings back to indices, but `sid` is a UUID string (per `aggregateParagraphs.js:44` + API response) — `parseInt('58552e0b...', 10)` returns `58552` (stops at 'e'), causing `segments[58552]` to be `undefined` and the per-segment `<span id="seg-{N}">` anchors to render with garbage indices. Replace with the same `segments.findIndex(s => String(s.id ?? segments.indexOf(s)) === sid)` pattern already used on line 246 for `containsActive`. Without this fix, B1's paragraph-split improvement renders mostly-empty paragraphs and B3 deep-link scroll cannot find `seg-{closest}` anchor.
- [x] 6.3 If verification step 7.4 below shows scroll still mis-aligned after B1 + 6.2a ship, add a follow-up subtask here to switch the scroll target from segment index to paragraph index. Do NOT prematurely refactor.

## 7. Prod chrome-devtools-mcp smoke verification

- [x] 7.1 After ship to prod and Zeabur deployment reaches RUNNING, open `https://app.podcastrag.app/` in chrome-devtools-mcp.
- [x] 7.2 On the home page, take a full snapshot and confirm none of the ShowCard descriptions contain `<` or `>` or `&amp;` or `&lt;` substrings (use `evaluate_script` to scan all `[class*="card"], section` text content). Capture screenshot.
- [x] 7.3 Click ShowCard for 曼報, switch to 語意 tab, search "AI 泡沫", click "跳到這段內容" on the first result. Confirm the URL contains `?show_id=...&episode_id=...&t=N`.
- [x] 7.4 On TranscriptPage, evaluate `[...document.querySelectorAll('*')].filter(el => el.children.length === 0 && /^\d{2}:\d{2}$/.test(el.textContent?.trim() || '')).filter(el => el.getBoundingClientRect().x > 280).length` and confirm result `>= 20` (right-side paragraph timestamps). Capture screenshot.
- [x] 7.5 Confirm the right-side scroller `scrollTop` is within ±200px of the y-offset of the paragraph closest to `t` query param (deep-link scroll worked).
- [x] 7.6 Confirm the top bar "從此處播放" button exists and is enabled (`document.querySelector('button:not([disabled])')` matches). Click it. Confirm the StickyAudioBar appears at the bottom of the page (audio element `currentTime > 0` and isPlaying true).
- [x] 7.7 Click back to QueryPage, confirm StickyAudioBar still visible and audio still playing (currentTime keeps advancing).
- [x] 7.8 Append the 4 confirmation screenshots and the DOM evaluate outputs to `docs/case-studies/landing-redesign-hotfix-2026-05-24.md` (per `feedback_case_studies_no_commit.md` this file is NOT git-tracked).

## 8. Remove instrumentation and archive

- [x] 8.1 Remove the `console.log('[transcript-play]', ...)` line added in task 4.4 once root cause has been captured in the case study.
- [x] 8.2 Update `src/TranscriptPage.jsx` script tag in `index.html` (bump `?v=N` cache-bust suffix). Same for `src/HomePage.jsx` if ShowCard was inlined there in task 5.2.
- [x] 8.3 Verify `node src/utils/aggregateParagraphs.test.js` and `node src/utils/stripHtml.test.js` both still pass locally.
- [x] 8.4 Open release log; draft an entry summarising "逐字稿閱讀體驗修復 + 音訊播放入口修復 + 節目簡介顯示乾淨" in user-facing language (per `feedback_release_log_style.md`). Wait for user confirmation before committing the release log entry.
- [x] 8.5 Run `/spectra-archive landing-redesign-hotfix-transcript-and-audio` only after task 7.8 evidence collection completes AND user approves release log draft.
