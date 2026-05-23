## ADDED Requirements

### Requirement: TranscriptPage "從此處播放" entry button renders whenever the episode has an audio_url

`TranscriptPage` SHALL render the "從此處播放" (`zh`) / "Play here" (`en`) button in its top bar whenever the loaded `episode.audio_url` is a non-empty string. The button's render condition SHALL NOT depend on whether the `AudioPlayerContext` is currently available — if the audio context is null at render time, the button SHALL still render but in a disabled state (`disabled={!audio}`) and its `onClick` handler SHALL be a no-op. When the audio context is available, clicking the button SHALL invoke `audio.playFromTime(episode.id, startSec, { title, audio_url })` where `startSec` is the currently active paragraph's `start_time` (or 0 when no paragraph is active), and the `StickyAudioBar` SHALL become visible to reflect the playback state.

#### Scenario: Button renders when audio_url is present even before AudioPlayerContext is ready

- **GIVEN** `TranscriptPage` mounts with `episode.audio_url = "https://cdn.example.com/ep.mp3"` and `useAudioPlayer()` returns `null` on first render
- **WHEN** the top bar renders
- **THEN** the "從此處播放" button SHALL be present in the DOM
- **AND** the button SHALL be in disabled state

#### Scenario: Button is enabled and triggers playback when context is ready

- **GIVEN** `TranscriptPage` is mounted with `episode.audio_url = "https://cdn.example.com/ep.mp3"` and `useAudioPlayer()` returns a context with `playFromTime` available
- **WHEN** the user clicks "從此處播放"
- **THEN** `audio.playFromTime(episode.id, 0, { title: episode.title, audio_url: episode.audio_url })` SHALL be invoked
- **AND** the `StickyAudioBar` SHALL become visible

#### Scenario: Button hides only when audio_url is missing or empty

- **GIVEN** `TranscriptPage` is mounted with `episode.audio_url = ""` (empty string) or `null`
- **WHEN** the top bar renders
- **THEN** the "從此處播放" button SHALL NOT be present in the DOM

#### Scenario: Button uses active paragraph start_time when a paragraph is selected

- **GIVEN** `TranscriptPage` has loaded paragraphs and the user has activated the paragraph starting at 120.5 seconds
- **WHEN** the user clicks "從此處播放" with audio context available
- **THEN** `audio.playFromTime` SHALL be called with `startSec = 120.5`
