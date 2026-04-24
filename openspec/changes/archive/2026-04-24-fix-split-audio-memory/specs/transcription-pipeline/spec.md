## MODIFIED Requirements

### Requirement: OpenAI provider handles oversized audio by chunking

The `OpenAIWhisperProvider` SHALL compare the input audio file size against a configurable threshold `OPENAI_WHISPER_CHUNK_SIZE_MB` (default 24). When the file size exceeds the threshold, the provider SHALL split the audio into sequential time-based chunks, transcribe each chunk via the Whisper API, and merge the results into a single `TranscriptionResult`. When the file size is at or below the threshold, the provider SHALL upload the file in a single request as before. The splitting procedure SHALL NOT load the full decoded audio waveform into process memory; it SHALL operate via streaming tools (e.g. `ffmpeg` subprocess with stream copy) so that peak memory usage is bounded independent of audio duration.

#### Scenario: Small audio uses single request

- **WHEN** `OpenAIWhisperProvider.transcribe()` is called with an audio file whose size is at or below `OPENAI_WHISPER_CHUNK_SIZE_MB * 1024 * 1024` bytes
- **THEN** the provider SHALL issue exactly one `audio.transcriptions.create` call with the full file and SHALL return a `TranscriptionResult` with segments whose `start` and `end` values equal the API response values

#### Scenario: Oversized audio split and merged

- **WHEN** `OpenAIWhisperProvider.transcribe()` is called with an audio file whose size exceeds `OPENAI_WHISPER_CHUNK_SIZE_MB * 1024 * 1024` bytes
- **THEN** the provider SHALL split the audio into `ceil(file_size_bytes / threshold_bytes)` sequential chunks of approximately equal duration (individual chunk boundaries MAY be aligned to the nearest audio frame or keyframe, with a tolerance of up to 2 seconds relative to a perfectly equal split), SHALL call `audio.transcriptions.create` once per chunk, and SHALL return a single `TranscriptionResult` whose `text` is the concatenation of each chunk's text separated by single spaces, whose `language` equals the first non-null language returned by any chunk, and whose `segments` are the union of all chunk segments with `start` and `end` offset by the cumulative start time of each chunk (as requested from the splitter) so the timeline is continuous with the original audio

#### Scenario: Chunk upload failure surfaces as exception

- **WHEN** any chunk's `audio.transcriptions.create` call raises an exception during oversized audio transcription
- **THEN** `OpenAIWhisperProvider.transcribe()` SHALL propagate the exception to the caller and SHALL NOT return a partial `TranscriptionResult`

#### Scenario: Temporary chunk files cleaned up

- **WHEN** `OpenAIWhisperProvider.transcribe()` finishes for an oversized audio file, whether it succeeded or raised an exception
- **THEN** all chunk files the provider wrote to disk SHALL be deleted before the method returns or re-raises

#### Scenario: Splitting does not decode full waveform

- **WHEN** `OpenAIWhisperProvider.transcribe()` splits an audio file that is N minutes long
- **THEN** the peak additional resident memory used by the splitting step SHALL be bounded by a constant that does not scale with N (i.e. SHALL NOT load the entire uncompressed PCM waveform into memory)
