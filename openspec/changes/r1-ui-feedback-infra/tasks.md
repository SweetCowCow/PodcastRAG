# Implementation Tasks

## 1. Database & Models

- [x] 1.1 Implements requirement `qa_feedback table` and requirement `events table` (db-schema spec) and design decision `events 表用「通用 schema + 指定 event_type」設計`. Create Alembic migration `add_qa_feedback_and_events.py` with both tables (qa_feedback append-only with `ix_qa_feedback_query_user_created`; events with JSONB `event_payload` and `ix_events_type_created`). Include downgrade dropping both tables.
- [x] 1.2 Add `backend/app/models/qa_feedback.py` (`QAFeedback` model) and `backend/app/models/event.py` (`Event` model). Register both in `backend/app/models/__init__.py`. The QAFeedback model SHALL be append-only per design decision `qa_feedback 同 query_id 可改投，不刪舊 row` (no UPDATE method).

## 2. Backend Schemas & APIs

- [x] 2.1 Add `backend/app/schemas/qa_feedback.py` with `QAFeedbackCreate` (query_id 1–64, vote Literal["up","down"], optional comment ≤2000 chars) and `QAFeedbackStats` (up_7d, down_7d, total_7d, ratio Optional[float]). Implements requirements `qa_feedback API accepts authenticated thumbs vote with optional comment` and `qa-feedback admin stats endpoint returns 7-day thumbs ratio`.
- [x] 2.2 Add `backend/app/schemas/event.py` with `CitationClickPayload` (query_id, chunk_id, position int ≥0) and `EventCreate` whose `event_type` is `Literal["citation_click"]` and `payload` is `CitationClickPayload`. Other event_type values raise 422. Implements requirement `events ingestion endpoint accepts citation_click payloads`.
- [x] 2.3 Add `backend/app/api/qa_feedback.py` exposing `POST /qa-feedback` (require_user, append-only insert, 201 response) per requirement `qa_feedback API accepts authenticated thumbs vote with optional comment`. Also expose `GET /qa-feedback/stats` per design decision `7 日 thumbs ratio endpoint at GET /qa-feedback/stats admin 限定` and requirement `qa-feedback admin stats endpoint returns 7-day thumbs ratio`. Stats SQL SHALL use a CTE selecting LATEST vote per (user_id, query_id) within 7 days then aggregating, so re-votes are not double-counted.
- [x] 2.4 Add `backend/app/api/events.py` exposing `POST /events` per design decision `POST /events 公開但 IP rate limit 60/min/IP` and requirement `events ingestion endpoint accepts citation_click payloads`. Use the existing `optional_auth_with_ip_limit` dependency configured for 60 req/min/IP (extend or wrap if needed). On valid payload insert one row (user_id from session if present else NULL). Return 202.
- [x] 2.5 Wire both routers in `backend/app/main.py` (`include_router` with prefixes `/qa-feedback` and `/events`). Confirm CORS allow-list does not block them.

## 3. RAG Query: query_id

- [x] 3.1 Implements requirement `RAG query response includes stable query_id`. In `backend/app/api/query.py` generate `query_id = uuid.uuid4().hex[:32]` server-side per request and include it in the JSON response payload. Update `backend/app/schemas/query.py` to add the `query_id` str field on the response model.

## 4. Backend Tests

- [x] 4.1 Add `backend/tests/test_qa_feedback_api.py` covering all scenarios from requirement `qa_feedback API accepts authenticated thumbs vote with optional comment`: anonymous returns 401; up-vote inserts row and returns 201; same user re-voting inserts a NEW row (assert table count grows); invalid `vote` returns 422.
- [x] 4.2 Add `backend/tests/test_qa_feedback_stats.py` covering all scenarios from requirement `qa-feedback admin stats endpoint returns 7-day thumbs ratio` plus design decision `qa_feedback 同 query_id 可改投，不刪舊 row` (re-vote counted only as latest): admin gets stats; rolling 7-day excludes 8-day-old rows; insert up then down for same (user, query) → expect down_7d=1 up_7d=0; empty stats returns ratio=null; non-admin returns 403; anonymous returns 401.
- [x] 4.3 Add `backend/tests/test_events_api.py` covering all scenarios from requirement `events ingestion endpoint accepts citation_click payloads`: anonymous insert returns 202 with user_id NULL; logged-in sets user_id; unknown event_type returns 422 (no row inserted); missing chunk_id returns 422; per-IP rate limit returns 429 after 60 reqs in 60s.

## 5. Frontend: QueryPage thumbs + citation beacon

- [x] 5.1 Implements requirement `QueryPage renders thumbs vote UI for AI answers` (anonymous disabled state). In `src/QueryPage.jsx` render thumbs-up and thumbs-down buttons immediately below each AI answer block using the answer's `query_id`. When `user` is null show disabled state with tooltip `登入後可投票` / `Sign in to vote`; clicks SHALL NOT trigger network requests.
- [x] 5.2 Implements requirement `QueryPage renders thumbs vote UI for AI answers` (logged-in up-vote path). Wire thumbs-up click → `apiFetch('/qa-feedback', { method:'POST', body: { query_id, vote:'up', comment:null } })`. On 201 set local state `voted={query_id: 'up'}`, change up button to accent color, render `已收到 ✓` / `Recorded ✓` next to buttons.
- [x] 5.3 Implements requirement `QueryPage renders thumbs vote UI for AI answers` (down-vote + comment + re-vote path). Wire thumbs-down click → expand inline textarea with `送出` button. Send button → POST with `vote:'down'` and `comment` (or null if empty). On success update colors. Re-clicking opposite button SHALL fire a new POST and flip `voted`.
- [x] 5.4 Implements requirement `SourceCard fires citation_click event on user click` and design decision `citation 點擊用 navigator.sendBeacon`. Refactor the citation/source card click handler in `src/QueryPage.jsx` to first call `sendCitationBeacon(query_id, chunk_id, position)` then perform navigation. Implement `sendCitationBeacon` as a tiny helper that prefers `navigator.sendBeacon` and falls back to `fetch('/events', {method:'POST', keepalive:true, body: JSON.stringify({event_type:'citation_click', payload:{...}}), headers:{'Content-Type':'application/json'}})`. Navigation SHALL fire regardless of beacon outcome.
- [x] 5.5 Implements requirement `QueryPage shows admin debug thumbs ratio`. When `user.role === 'admin'` and at least one AI answer is present, fetch `GET /qa-feedback/stats` once on first AI answer render. Render a small line near the top of the conversation area: `[admin] 7d thumbs: {up_7d}↑ {down_7d}↓ ({Math.round(ratio*100)}%)` or `[admin] 7d thumbs: no data` when ratio is null. Non-admin SHALL not fetch and SHALL not render.

## 6. Frontend: LandingPage polish (bundled)

- [x] 6.1 Implements design decision `LandingPage 節目卡片改用 PodcastSelect 的 ShowCard` (export step). Confirm `src/PodcastSelect.jsx` exports `ShowCard` via the file's `Object.assign(window, ...)` line so it is reachable from LandingPage.
- [x] 6.2 Implements requirement `Landing Page lists collected shows with real data` and design decision `LandingPage 節目卡片改用 PodcastSelect 的 ShowCard` (consume step). In `src/LandingPage.jsx` render show cards by mapping over the `/shows` response and rendering `<ShowCard show={show} lang={lang} hovered={...} onMouseEnter={...} onMouseLeave={...} onClick={() => onSelectShow(show)} />` inside a CSS grid `repeat(auto-fill, minmax(320px, 1fr))` (1 column on mobile). Remove the inline simplified card rendering and the `truncate` helper.
- [x] 6.3 Implements requirement `Landing Page paywall band explains the freemium boundary and offers login` (heading). Confirm the paywall band heading is `登入解鎖：30 次 AI 統整回答` (zh) / `Log in to unlock: 30 free AI summary answers` (en) — without the parenthetical.
- [x] 6.4 Implements requirement `Landing Page paywall band explains the freemium boundary and offers login` (body). Confirm the paywall body is `瀏覽逐字稿、看相關段落都不用登入。只有「請 AI 統整回答」需要登入使用額度。` (zh) / `Browsing transcripts and matched segments needs no login. Only "Ask AI to summarize" requires login and uses your quota.` (en).
- [x] 6.5 Confirm `index.html` loads `src/PodcastSelect.jsx` BEFORE `src/LandingPage.jsx`. Bump cache versions on the changed files (`PodcastSelect.jsx?v=3`, `LandingPage.jsx?v=2`, `QueryPage.jsx?v=3`).

## 7. Verify & Ship

- [x] 7.1 Run full backend test suite (`pytest backend/`) and confirm zero regressions plus all new tests pass.
- [x] 7.2 Manually exercise locally via curl on dev backend: POST /qa-feedback (logged-in cookie), POST /events (anonymous + logged-in), GET /qa-feedback/stats (admin). Confirm rows in DB.
- [ ] 7.3 Commit and push. Wait for Zeabur frontend + backend redeploy. Use chrome-devtools-mcp on `https://app.podcastrag.app` (per `feedback_browser_verification.md` rule) to verify: (a) AI query as logged-in user → click thumbs-down → submit comment → reload → verify row in DB; (b) click a citation card → confirm `events` row inserted; (c) anonymous visit landing → confirm new ShowCard layout + new paywall copy renders; (d) admin role → confirm `[admin] 7d thumbs: ...` debug line appears.
