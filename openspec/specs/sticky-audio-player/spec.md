# sticky-audio-player Specification

## Purpose

TBD - created by archiving change 'landing-and-mode-orchestration-redesign'. Update Purpose after archive.

## Requirements

### Requirement: StickyAudioPlayer mounts once outside the page router

The `StickyAudioPlayer` component SHALL be mounted once at the top of the React tree, outside the page router used by `App.jsx`. The underlying HTML `<audio>` element SHALL NOT be unmounted or remounted as the user navigates between QueryPage and TranscriptPage; navigation between these pages SHALL NOT pause, seek, or reload audio playback.

#### Scenario: Audio playback continues across QueryPage to TranscriptPage navigation

- **GIVEN** the user has started playing episode E at time 120s while on QueryPage
- **WHEN** the user navigates to TranscriptPage for the same episode
- **THEN** the audio SHALL continue playing without a gap or reload
- **AND** the player's `currentTime` SHALL keep advancing monotonically across the navigation

#### Scenario: Player remains hidden when no episode is loaded

- **GIVEN** the user has not invoked any play action since app load
- **WHEN** any page renders
- **THEN** the StickyAudioPlayer SHALL render with no visible audio bar

---
### Requirement: AudioPlayerContext exposes a stable control interface

A React context named `AudioPlayerContext` SHALL expose the methods `playFromTime(episodeId: string, startSec: number)`, `pause()`, `seek(sec: number)`, and `setSpeed(rate: number)`, and the state values `currentEpisodeId`, `currentTime`, `isPlaying`, and `speed`. Both QueryPage and TranscriptPage SHALL trigger playback only through this context; neither page SHALL instantiate its own `<audio>` element.

#### Scenario: playFromTime starts the chosen episode at the chosen second

- **WHEN** any component calls `playFromTime("ep-42", 87)`
- **THEN** the StickyAudioPlayer SHALL load and play episode `ep-42` starting at the 87-second mark
- **AND** `currentEpisodeId` SHALL become `"ep-42"` and `isPlaying` SHALL become true

#### Scenario: setSpeed accepts 1.0, 1.25, and 1.5

- **WHEN** a component calls `setSpeed(1.25)`
- **THEN** the underlying `<audio>.playbackRate` SHALL be set to 1.25
- **AND** the context `speed` value SHALL become 1.25

---
### Requirement: Playback speed is restricted to three discrete values and persisted

The StickyAudioPlayer UI SHALL expose exactly three playback speed options: 1.0x, 1.25x, and 1.5x. The currently selected speed SHALL be persisted to `localStorage` under the key `audio_speed` and SHALL be restored on next app load. Speed values outside this set SHALL NOT be selectable through the UI.

#### Scenario: Speed selection survives reload

- **GIVEN** the user sets speed to 1.5x
- **WHEN** the user reloads the page
- **THEN** the StickyAudioPlayer SHALL restore the speed to 1.5x on next play

#### Scenario: UI offers exactly three speed buttons

- **WHEN** the StickyAudioPlayer renders with a loaded episode
- **THEN** the speed control SHALL expose exactly the values 1.0x, 1.25x, and 1.5x

##### Example: speed cycle

| Current Speed | Action | New Speed |
|---------------|--------|-----------|
| 1.0x | click speed control | 1.25x |
| 1.25x | click speed control | 1.5x |
| 1.5x | click speed control | 1.0x |

---
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
