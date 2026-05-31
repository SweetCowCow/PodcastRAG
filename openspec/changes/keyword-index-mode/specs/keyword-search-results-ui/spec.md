## ADDED Requirements

### Requirement: Index tab renders sectioned T1 / T2 / T3 layout

The `src/QueryPage.jsx` index (keyword) tab SHALL render a `<KeywordResults>` component that displays up to three vertically stacked sections in fixed order: T1 (same-chunk AND chunks), T2 (cross-pool episode AND), and T3 (OR fallback). The T3 section SHALL be rendered only when the response contains a non-null `t3` object. Each section SHALL show a section header with its match count (e.g., "段內全部命中 · 12 段", "全集跨欄位命中 · 5 集"). When the response indicates zero matches across all sections, the component SHALL render an empty state instead of empty section frames.

#### Scenario: T3 hidden when T1 or T2 has hits

- **WHEN** the response has `t1.total = 3` and `t3 = null`
- **THEN** the T3 section frame SHALL NOT render

#### Scenario: Section headers show counts

- **WHEN** the response has `t1.total = 12, t2.total = 5`
- **THEN** the T1 header text SHALL include "12" and the T2 header text SHALL include "5"

### Requirement: T1 chunk card shows hit context and expand control

Each T1 chunk card SHALL by default render only the sentence containing the first hit plus one sentence before and one sentence after (three sentences total). The card SHALL provide an inline "展開上下文 / Show context" toggle button that expands the card to reveal the full text of the matched chunk (the 30–60s segment already returned in the response — no extra endpoint call). The card SHALL provide a "跳播 / Jump" button that triggers the existing sticky audio player to seek to the chunk's `start_time`.

> 2026-05-31 apply 校正：原 Requirement 要求展開顯示「5 個相鄰 `transcript_chunks`」，但本 change 未提供 episode-scoped 取相鄰 chunk 的 endpoint。改為展開顯示「完整命中 chunk 的全文」（已在回應中、無需再打 API）。顯示相鄰 chunk 留作 follow-up（需新 episode-transcript-chunks endpoint）。

#### Scenario: Default render shows three sentences

- **WHEN** a T1 chunk card first renders for a chunk with 8 sentences and a hit in sentence 4
- **THEN** the card SHALL display sentences 3, 4, and 5 by default and the "展開上下文" button SHALL be visible

#### Scenario: Jump triggers audio player seek

- **WHEN** the user clicks the "跳播" button on a chunk with `start_time = 145.3`
- **THEN** the sticky audio player SHALL receive a seek instruction for 145.3 seconds

### Requirement: Two-color highlight for matched terms

The component SHALL highlight every occurrence of each `terms` entry inside any rendered text (T1 chunk text, T2 expanded chunk text, T3 chunk text) using `<mark>` wrappers. Color assignment SHALL be deterministic by term order: terms at even index in the `terms` array SHALL receive orange (`#f97316`), terms at odd index SHALL receive cyan (`#06b6d4`). The same term SHALL always receive the same color within a single render. To remain accessible to color-vision-deficient users, the orange highlight SHALL also carry a solid underline and the cyan highlight SHALL also carry a dashed underline.

#### Scenario: Two-term query gets two colors

- **WHEN** `terms = ["馬世芳", "滅火器"]` and a chunk text contains both terms
- **THEN** "馬世芳" SHALL render with orange background and solid underline, "滅火器" SHALL render with cyan background and dashed underline

##### Example: color rotation with three terms

- **GIVEN** `terms = ["A", "B", "C"]`
- **WHEN** a chunk contains all three terms
- **THEN** A SHALL render orange (index 0), B SHALL render cyan (index 1), C SHALL render orange (index 2)

### Requirement: T2 episode card pool distribution and inline expand

Each T2 episode card SHALL display the episode title and a "命中分佈 / Hit distribution" line showing the per-pool counts from `pool_counts` (e.g., "標題 1 · 描述 2 · 逐字稿 7"). The card SHALL provide an inline "展開查看各段 / Expand to view segments" toggle that, when clicked, fetches and displays the matching `transcript_chunks` for that episode using the existing transcript endpoint or a same-endpoint follow-up call. Expansion SHALL be inline; the card SHALL NOT navigate away from the results page.

#### Scenario: Pool distribution rendering

- **WHEN** a T2 episode card has `pool_counts = { "title": 1, "description": 2, "transcript": 7 }`
- **THEN** the card SHALL render text containing "1", "2", and "7" alongside their pool labels

### Requirement: T2 collapsed presentation when threshold exceeded

When the response has `t2.collapsed == true`, the T2 section SHALL render as a single compact chip showing the text "+{t2.total} 集亦有命中 / +{t2.total} episodes also match" instead of the full list of episode cards. The chip SHALL be clickable; clicking it SHALL expand the section in place to show the full episode card list (using the already-returned `t2.items` data without an extra network request).

#### Scenario: Collapsed chip expands on click

- **WHEN** the response has `t2.collapsed = true, t2.total = 8` and the user clicks the chip
- **THEN** the chip SHALL be replaced inline by the full list of 8 episode cards

### Requirement: T3 fallback section UI

When the T3 section renders, it SHALL display compact (reduced-padding) chunk cards, a prominent mode-switcher chip near the section header offering switches to semantic and chat modes, and a warning text "段內全部命中與全集命中皆無，以下為任一關鍵字的鬆散結果 / No strict matches; below are loose hits for any keyword".

#### Scenario: T3 renders warning and mode switcher

- **WHEN** the response has `t1.total = 0, t2.total = 0, t3.total = 4`
- **THEN** the T3 section SHALL render 4 compact chunk cards, a visible mode-switcher chip, and the warning text

### Requirement: Incremental pagination per section

The component SHALL display a "顯示更多 5 段 / Show 5 more" button at the bottom of the T1 section (text "5 段") and the T2 section (text "5 集") whenever the locally accumulated item count is less than `total` for that section. Clicking the button SHALL call the keyword-search endpoint with `offset_t1` or `offset_t2` advanced by 5 (and `limit = 5`) and SHALL merge the returned items into the existing list. The button SHALL be hidden once the accumulated count reaches 100 or equals `total`, whichever comes first.

#### Scenario: Show more button advances offset

- **WHEN** the initial response returned 25 T1 items with `t1.total = 40` and the user clicks "顯示更多 5 段"
- **THEN** the component SHALL fetch with `offset_t1 = 25, limit = 5` and append the resulting items to the existing list

#### Scenario: Button hides at hard cap

- **WHEN** the accumulated T1 item count reaches 100
- **THEN** the "顯示更多 5 段" button SHALL be hidden regardless of `t1.total`

### Requirement: Bottom mode switcher chip always visible

The `<KeywordResults>` component SHALL render a mode-switcher chip at the bottom of the results area on every render path (with results, with zero results, while loading once the first response arrives). The chip SHALL offer switches to semantic mode and chat mode and SHALL preserve the current query string across the switch.

#### Scenario: Mode switcher preserves query

- **WHEN** the user has searched "馬世芳" in index mode and clicks the bottom switcher chip to switch to semantic
- **THEN** the semantic tab SHALL activate with the query input pre-populated to "馬世芳"

### Requirement: Zero-result empty state with examples

When the response contains zero items across all sections (`t1.total + t2.total + (t3?.total ?? 0) == 0`), the component SHALL render an empty-state block containing a mode-switcher chip and three example query suggestions. The example suggestions SHALL be sourced from `GET /shows/{id}/trending-queries` when that endpoint is available; otherwise the component SHALL fall back to a built-in static list of three example queries.

#### Scenario: Empty state shows three examples

- **WHEN** the response is entirely empty
- **THEN** the empty-state block SHALL render exactly 3 example query suggestion buttons and a mode-switcher chip

#### Scenario: Fallback to static examples when trending endpoint absent

- **WHEN** the trending-queries endpoint returns 404 or is not yet deployed
- **THEN** the empty-state block SHALL render 3 hardcoded example queries instead
