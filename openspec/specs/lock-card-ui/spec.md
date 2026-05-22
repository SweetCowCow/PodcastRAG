# lock-card-ui Specification

## Purpose

TBD - created by archiving change 'landing-and-mode-orchestration-redesign'. Update Purpose after archive.

## Requirements

### Requirement: LockCard covers Chat tab answer area for two states

The `LockCard` component SHALL fully cover the Chat tab's answer area in two states: (a) when the visitor is unauthenticated (`anonymous` variant), and (b) when the authenticated user's remaining chat quota equals zero (`quota_exhausted` variant). The Chat tab's input field and mode tab strip SHALL remain visible and interactive in both states. The Semantic tab and Index tab SHALL NOT display the LockCard regardless of auth or quota state.

#### Scenario: Anonymous visitor sees anonymous LockCard on Chat tab

- **GIVEN** an unauthenticated visitor on a show's QueryPage
- **WHEN** the visitor activates the Chat tab
- **THEN** the answer area SHALL be covered by a LockCard with variant `anonymous`
- **AND** the tab strip and input SHALL remain interactive

#### Scenario: Quota-exhausted user sees quota LockCard on Chat tab

- **GIVEN** an authenticated user whose remaining chat quota is 0
- **WHEN** the user activates the Chat tab
- **THEN** the answer area SHALL be covered by a LockCard with variant `quota_exhausted`

#### Scenario: LockCard does not appear on Semantic tab

- **GIVEN** an unauthenticated visitor
- **WHEN** the visitor activates the Semantic tab
- **THEN** no LockCard SHALL render on the Semantic tab

---
### Requirement: Anonymous LockCard renders exact bilingual copy and login CTA

The `anonymous` variant of `LockCard` SHALL render: the icon 🔒, a headline 不想花時間重聽找答案？ (`zh`) / Tired of scrubbing through podcasts to find an answer? (`en`), a body line 登入後直接針對節目內容發問，自動為你交叉比對，整理重點回覆 (`zh`) / After signing in, you can ask questions directly about the show and get cross-referenced, summarized answers automatically. (`en`), a primary CTA labelled 以 Google 登入 (`zh`) / Sign in with Google (`en`), and a secondary link labelled 或先用語意搜尋找找看相關片段 (`zh`) / Or try semantic search to find relevant segments first (`en`). The anonymous variant SHALL NOT contain the words 免費 (`zh`) / free (`en`) nor any reference to a quota number nor any reset time wording.

#### Scenario: Primary CTA opens LoginModal

- **WHEN** the visitor clicks 以 Google 登入 on the anonymous LockCard
- **THEN** the existing `LoginModal` component SHALL open

#### Scenario: Secondary link switches to Semantic tab

- **WHEN** the visitor clicks the secondary "semantic search" link on the anonymous LockCard
- **THEN** the QueryPage SHALL switch the active tab to Semantic

#### Scenario: Anonymous copy contains no forbidden marketing words

- **WHEN** the anonymous LockCard renders in `zh`
- **THEN** the rendered text SHALL NOT contain the substring 免費
- **AND** the rendered text SHALL NOT contain any numeric quota reference
- **AND** the rendered text SHALL NOT contain any reset time phrasing

---
### Requirement: Quota-exhausted LockCard renders exact bilingual copy and apply CTA

The `quota_exhausted` variant of `LockCard` SHALL render: the icon ⏳, a headline 已達使用上限 (`zh`) / You have reached the usage limit (`en`), a body line 如果還需要繼續用，可以說明用途申請額度 (`zh`) / If you still need to use it, you can apply for more by describing your use case. (`en`), a primary CTA labelled 申請更多次數 (`zh`) / Apply for more (`en`), and a secondary link labelled 或先用語意搜尋找找看相關片段 (`zh`) / Or try semantic search to find relevant segments first (`en`). The variant SHALL NOT contain any wording that implies an automatic reset time or schedule.

#### Scenario: Primary CTA opens existing QuotaApplyModal

- **WHEN** the user clicks 申請更多次數 on the quota_exhausted LockCard
- **THEN** the existing `QuotaApplyModal` component SHALL open
- **AND** submitting that modal SHALL post to the existing `POST /quota-requests` endpoint

#### Scenario: Secondary link switches to Semantic tab

- **WHEN** the user clicks the secondary "semantic search" link on the quota_exhausted LockCard
- **THEN** the QueryPage SHALL switch the active tab to Semantic

#### Scenario: Quota copy contains no reset time wording

- **WHEN** the quota_exhausted LockCard renders in `zh`
- **THEN** the rendered text SHALL NOT contain the substrings 每月, 每週, 重置, 重新計算, or 自動恢復
