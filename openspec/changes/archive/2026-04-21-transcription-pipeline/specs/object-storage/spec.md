## ADDED Requirements

### Requirement: R2 client configuration

The backend SHALL configure an S3-compatible boto3 client targeting Cloudflare R2 using `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`, and `R2_ENDPOINT` environment variables.

#### Scenario: Client initialised from settings

- **WHEN** the application starts with all R2 variables present
- **THEN** the client factory SHALL construct a boto3 S3 client pointing at `R2_ENDPOINT` with signature version `s3v4` and the provided credentials

#### Scenario: Missing credentials rejected

- **WHEN** the application starts without `R2_ACCOUNT_ID` or `R2_BUCKET`
- **THEN** configuration validation SHALL raise an error listing the missing variables before any transcription-related endpoint is served

### Requirement: Upload audio from URL

The object storage service SHALL provide `upload_from_url(source_url) -> storage_key` that downloads the audio into a temp file, uploads it to the configured bucket, and returns the generated object key.

#### Scenario: Upload succeeds

- **WHEN** `upload_from_url` is called with a reachable audio URL of 50 MB
- **THEN** the method SHALL return a non-empty `storage_key` and the object SHALL exist in the R2 bucket with matching size

#### Scenario: Remote fetch fails

- **WHEN** `upload_from_url` is called with a URL that returns HTTP 404
- **THEN** the method SHALL raise a `StorageError` with the underlying HTTP status

### Requirement: Download to temp file

The object storage service SHALL provide `download_to_temp(storage_key) -> local_path` that downloads the object to a temp file and returns its path; callers SHALL be responsible for deleting the file.

#### Scenario: Object exists

- **WHEN** `download_to_temp` is called with an existing `storage_key`
- **THEN** the method SHALL return a filesystem path pointing to a file whose byte size matches the R2 object

#### Scenario: Object missing

- **WHEN** `download_to_temp` is called with a non-existent `storage_key`
- **THEN** the method SHALL raise a `StorageError`

### Requirement: Presigned URL generation

The object storage service SHALL provide `get_presigned_url(storage_key, expires_in)` that returns a time-limited HTTPS URL usable to GET the stored object.

#### Scenario: URL generated

- **WHEN** `get_presigned_url` is called for an existing `storage_key` with `expires_in=3600`
- **THEN** the method SHALL return an HTTPS URL whose signature expires in approximately one hour
