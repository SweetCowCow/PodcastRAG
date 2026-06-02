## MODIFIED Requirements

### Requirement: Detection uses centralized AI step configuration

The LLM detection SHALL resolve its model and prompt from a centralized AI step named `asr_homophone`, consistent with other AI steps. Response parsing SHALL be tolerant of provider formatting variation so that swapping the configured model does not silently yield zero pairs: it SHALL accept a JSON payload wrapped in a markdown code block, a bare JSON array, an object wrapping the array under a key such as `pairs`/`corrections`, and a response with surrounding non-JSON text by extracting the first JSON array or object. Entries with case- or whitespace-variant `wrong`/`correct` keys SHALL be accepted. When parsing fails despite tolerance, detection SHALL fail open and return an empty list.

#### Scenario: Step config resolved

- **WHEN** detection runs
- **THEN** it SHALL use the model and prompt configured for the `asr_homophone` step

#### Scenario: Object-wrapped payload parsed

- **WHEN** the LLM returns an object wrapping the pair list under a `pairs` key (with or without a surrounding code block)
- **THEN** the pairs SHALL be parsed rather than treated as empty

#### Scenario: Payload with surrounding prose parsed

- **WHEN** the LLM returns a JSON array preceded or followed by explanatory text
- **THEN** the embedded JSON array SHALL be extracted and parsed
