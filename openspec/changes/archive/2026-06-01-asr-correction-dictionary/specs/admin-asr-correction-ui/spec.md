## ADDED Requirements

### Requirement: Admin tab manages correction rules

The admin panel SHALL provide an ASR correction tab that lists existing rules showing `wrong`, `correct`, `scope`, the bound show, and the enabled state, and SHALL allow creating, editing, enabling or disabling, and deleting rules. The tab SHALL be bilingual (Traditional Chinese and English) and SHALL use the shared TOKEN design system.

#### Scenario: List and create rule

- **WHEN** an admin opens the ASR correction tab
- **THEN** the tab SHALL display existing rules and SHALL provide a form to create a new rule with `wrong`, `correct`, `scope`, a bound show when scope is `show`, and an optional note

#### Scenario: Toggle enabled

- **WHEN** an admin disables a rule
- **THEN** the rule SHALL be marked disabled and SHALL stop being applied

### Requirement: Match-count preview before save

Before a rule is saved, the tab SHALL display how many existing transcript segments the rule's `wrong` value currently matches within its scope, so the admin can detect an over-broad rule before applying it.

#### Scenario: Preview shows match count

- **WHEN** an admin enters a `wrong` value and a scope
- **THEN** the tab SHALL show the number of currently matching segments before the rule is saved

### Requirement: Trigger backfill with progress feedback

The tab SHALL allow triggering a backfill for a chosen scope and SHALL surface its progress and completion, including affected segments, affected chunks, and failures. The tab SHALL inform the admin that newly added rules require a manual backfill to correct existing transcripts.

#### Scenario: Trigger backfill

- **WHEN** an admin triggers a backfill from the tab
- **THEN** the tab SHALL start the backfill and SHALL display its progress and final counts

#### Scenario: Manual backfill notice

- **WHEN** an admin adds a new rule
- **THEN** the tab SHALL indicate that existing transcripts require a manual backfill to reflect the rule
