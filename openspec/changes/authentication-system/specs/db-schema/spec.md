## ADDED Requirements

### Requirement: users table

The database SHALL contain a `users` table storing per-user identity, role, status, and quota counters.

#### Scenario: User record created on first Google login

- **WHEN** a user is inserted following a Google OAuth callback
- **THEN** the row SHALL be persisted with the following columns: `id` (UUID primary key), `email` (TEXT, unique, not null), `name` (TEXT, nullable), `avatar_url` (TEXT, nullable), `provider` (TEXT, not null, default `'google'`), `google_sub` (TEXT, unique, not null when provider is `google`), `role` (TEXT, not null, CHECK constraint in `('admin', 'member')`), `status` (TEXT, not null, CHECK constraint in `('active', 'pending', 'disabled')`), `total_queries` (BIGINT, not null, default 0), `quota_remaining` (INTEGER, not null, default 100), `quota_initial` (INTEGER, not null, default 100), `notes` (TEXT, nullable), `created_at` (TIMESTAMPTZ, not null, default `now()`), `last_login_at` (TIMESTAMPTZ, nullable)

#### Scenario: Duplicate email is rejected

- **WHEN** an insert is attempted with an `email` that already exists in the table
- **THEN** the database SHALL raise a unique constraint violation

#### Scenario: Invalid role rejected

- **WHEN** an insert or update sets `role` to a value other than `'admin'` or `'member'`
- **THEN** the database SHALL raise a check constraint violation

#### Scenario: Invalid status rejected

- **WHEN** an insert or update sets `status` to a value other than `'active'`, `'pending'`, or `'disabled'`
- **THEN** the database SHALL raise a check constraint violation

### Requirement: sessions table

The database SHALL contain a `sessions` table storing server-side session state for authenticated users.

#### Scenario: Session row created on login

- **WHEN** a user completes Google OAuth callback and a session is created
- **THEN** a row SHALL be inserted with: `id` (UUID primary key), `user_id` (UUID, foreign key to `users.id` ON DELETE CASCADE, not null), `session_token_hash` (TEXT, unique, not null, SHA-256 hex digest), `csrf_token_hash` (TEXT, not null), `created_at` (TIMESTAMPTZ, default `now()`), `expires_at` (TIMESTAMPTZ, not null), `last_seen_at` (TIMESTAMPTZ, default `now()`), `ip` (INET, nullable), `user_agent` (TEXT, nullable)

#### Scenario: Cascade delete on user removal

- **WHEN** a row in `users` is deleted
- **THEN** all rows in `sessions` whose `user_id` references that user SHALL also be deleted

#### Scenario: Session token is stored only as hash

- **WHEN** a session row is inspected
- **THEN** no plaintext session token cookie value SHALL be present in any column
- **AND** `session_token_hash` SHALL be the 64-character lowercase SHA-256 hex digest of the cookie value
