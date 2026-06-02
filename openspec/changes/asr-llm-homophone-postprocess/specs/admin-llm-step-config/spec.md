## ADDED Requirements

### Requirement: asr_homophone AI step is configurable

The system SHALL register an `asr_homophone` AI step whose model and prompt are resolvable through the centralized AI step configuration, consistent with existing steps. The transcription homophone detection SHALL read its model and prompt from this step.

#### Scenario: Step model and prompt resolved

- **WHEN** homophone detection runs during transcription
- **THEN** it SHALL obtain its model and prompt from the `asr_homophone` step configuration

#### Scenario: Step appears in admin AI step config

- **WHEN** an admin views the AI step configuration
- **THEN** the `asr_homophone` step SHALL be present and editable
