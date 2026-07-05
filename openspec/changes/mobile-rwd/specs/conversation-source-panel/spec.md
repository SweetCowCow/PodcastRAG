## ADDED Requirements

### Requirement: Source panel preserves content width on mobile

On mobile (`isMobile === true`), the chat source panel (ConversationSourcePanel and the SegmentCitationCard entries inside it) SHALL reduce nested horizontal padding and margins so that the innermost quoted-text region's width is at least 85% of the assistant message bubble's content width. The per-segment action row (播放此段 / play segment and 跳到逐字稿 / jump to transcript) SHALL render each action's label on a single line; when both actions do not fit side by side, they SHALL stack vertically as full single-line rows. Character-per-line vertical text SHALL NOT occur anywhere in the panel. Desktop rendering SHALL remain unchanged.

#### Scenario: Quoted text uses at least 85% of bubble width on mobile

- **GIVEN** a 375×667 mobile viewport and a chat answer with at least one cited segment
- **WHEN** the source panel renders expanded
- **THEN** the quoted-text region's measured width SHALL be at least 85% of the assistant bubble's content width

#### Scenario: Action labels render single-line on mobile

- **GIVEN** the same mobile viewport and cited segment
- **WHEN** the action row renders
- **THEN** 播放此段 and 跳到逐字稿 SHALL each render on one line (stacked as two rows if needed), never as one character per line

#### Scenario: Episode title truncates instead of squeezing

- **GIVEN** a cited segment whose episode title is longer than the available header width
- **WHEN** the episode group header renders on mobile
- **THEN** the title SHALL truncate with an ellipsis on a single line rather than force the content region narrower

#### Scenario: Desktop panel unchanged

- **GIVEN** a 1280 px desktop viewport with the same chat answer
- **WHEN** the source panel renders
- **THEN** the panel's layout SHALL be unchanged from the pre-change desktop rendering
