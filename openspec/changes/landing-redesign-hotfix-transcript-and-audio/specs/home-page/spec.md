## MODIFIED Requirements

### Requirement: HomePage renders show grid with real backend data

The `HomePage` SHALL include a section labelled 收錄節目 (`zh`) / Collected Shows (`en`) below the mode trio. This section SHALL render one card per show returned by `GET /shows` using a `<ShowCard>` component. Each card SHALL display: cover image (with fallback colored icon when `image_url` is missing), show title, language label, description rendered as **plain text only** (all HTML tags MUST be stripped, `<br>` `<br/>` `<br />` MUST be converted to newline characters, common HTML entities such as `&amp; &lt; &gt; &quot; &#39; &nbsp;` MUST be decoded to their character form, and clamped to 3 lines), total episode count, transcribed episode count, transcription progress bar with percentage, RSS feed URL, and an `進入節目` (`zh`) / `Open Show` (`en`) link. Clicking anywhere on a card SHALL navigate to the show's QueryPage. The grid SHALL use `repeat(auto-fill, minmax(320px, 1fr))` on desktop and 1 column on mobile.

#### Scenario: Show cards render in backend-returned order

- **GIVEN** `GET /shows` returns shows S1, S2, S3
- **WHEN** the show grid renders
- **THEN** the cards SHALL appear in the order S1, S2, S3

#### Scenario: Card click navigates to QueryPage for that show

- **WHEN** the visitor clicks anywhere on a show card
- **THEN** the application SHALL navigate to the QueryPage for that show

#### Scenario: Description containing raw HTML tags renders as plain text

- **GIVEN** a show with `description = "<p>各種生活中的小事隨便聊，<br />合作邀約｜<a href='mailto:x@y'>x@y</a></p>"`
- **WHEN** the card renders the description
- **THEN** the visible text SHALL NOT contain any `<` or `>` character
- **AND** the `<br />` SHALL be converted to a line break
- **AND** the visible text SHALL contain the substring `各種生活中的小事隨便聊，` followed by a newline followed by `合作邀約｜x@y`

#### Scenario: Description containing HTML entities renders with entities decoded

- **GIVEN** a show with `description = "Powered by &lt;Firstory&gt; &amp; co."`
- **WHEN** the card renders the description
- **THEN** the visible text SHALL be `Powered by <Firstory> & co.`

#### Scenario: Null or missing description does not throw

- **GIVEN** a show with `description = null` or `description` field absent
- **WHEN** the card renders
- **THEN** no exception SHALL be thrown
- **AND** the description region SHALL render as empty (or omitted entirely)
