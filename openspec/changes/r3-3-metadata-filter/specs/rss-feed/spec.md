## MODIFIED Requirements

### Requirement: RSS feed parser

The backend SHALL provide an async function that accepts an RSS feed URL and returns structured show metadata plus a list of episode metadata, supporting RSS 2.0 with iTunes extensions. For each parsed episode, the parser SHALL apply a guests-extraction regex against the episode title and populate the resulting `guests` field as a list of strings (empty list when no pattern matches).

#### Scenario: Valid RSS feed parsed

- **WHEN** the parser is called with a URL returning a valid RSS 2.0 feed
- **THEN** it SHALL return a show object (title, description, image_url, language) and a list of episode objects (title, description, audio_url, duration_seconds, published_at, guid, guests)

#### Scenario: Invalid feed URL rejected

- **WHEN** the parser is called with a URL returning HTTP 404, non-XML content, or XML without a channel element
- **THEN** it SHALL raise a descriptive parser error identifying the failure reason

#### Scenario: Feed without iTunes extensions parsed

- **WHEN** the parser is called with a plain RSS 2.0 feed lacking iTunes tags
- **THEN** it SHALL still return show and episode data, leaving iTunes-specific fields (duration_seconds, image_url) as null when absent

#### Scenario: Episode title with Ft. pattern populates guests

- **WHEN** the parser processes an entry whose title contains `"Ft. 馬世芳 / 裴社長"`
- **THEN** the returned ParsedEpisode object MUST have `guests = ["馬世芳", "裴社長"]`

#### Scenario: Episode title without guest pattern populates empty guests

- **WHEN** the parser processes an entry whose title is `"EP100｜年終回顧"`
- **THEN** the returned ParsedEpisode object MUST have `guests = []` (NOT None, NOT missing field)
