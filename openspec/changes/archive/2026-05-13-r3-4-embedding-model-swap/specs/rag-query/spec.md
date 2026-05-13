## MODIFIED Requirements

### Requirement: Embedding model is `text-embedding-3-large` with dual-write transition

The backend SHALL embed both queries and chunks using OpenAI `text-embedding-3-large` (3072 dim) once `RAG_USE_EMBEDDING_V2=true` is set. During the transition window, write paths SHALL dual-write to both `embedding` (legacy 1536-dim, `text-embedding-3-small`) and `embedding_v2` (new 3072-dim, `text-embedding-3-large`) columns. The model used for each column is resolved from the `ai_steps` config row for `embedding` step; legacy model stays static while v2 model is configurable. The read path SHALL pick the column based on `RAG_USE_EMBEDDING_V2`: when `true` it SHALL use `embedding_v2`; when `false` or unset it SHALL use `embedding`. Query embedding SHALL be produced with the same model that was used to populate the chosen column (no cross-model cosine comparison).

#### Scenario: env unset retains legacy embedding path

- **GIVEN** `RAG_USE_EMBEDDING_V2` is unset
- **WHEN** `/shows/{show_id}/search` is invoked
- **THEN** the query SHALL be embedded with `text-embedding-3-small`
- **AND** the candidate SQL SHALL ORDER BY `embedding <=> :query_embedding`
- **AND** the response SHALL be functionally identical to R3.2 baseline

#### Scenario: env true routes to v2 column

- **GIVEN** `RAG_USE_EMBEDDING_V2=true`
- **AND** every transcript/description chunk has a non-NULL `embedding_v2`
- **WHEN** `/shows/{show_id}/search` is invoked
- **THEN** the query SHALL be embedded with `text-embedding-3-large`
- **AND** the candidate SQL SHALL ORDER BY `embedding_v2 <=> :query_embedding`
- **AND** the embedding dim used SHALL be 3072

#### Scenario: dual-write during transition

- **GIVEN** `EMBEDDING_DUAL_WRITE=true`
- **WHEN** a new transcript or description chunk is created and embed step runs
- **THEN** both `embedding` (1536, legacy model) AND `embedding_v2` (3072, new model) SHALL be populated atomically
- **AND** if either embed call fails, the row SHALL still be inserted with the successful column populated and the failing column NULL plus a logged warning

#### Scenario: dim mismatch is a hard error

- **GIVEN** `RAG_USE_EMBEDDING_V2=true`
- **AND** the `ai_steps` config for `embedding` step is set to a model whose native dim != 3072
- **WHEN** the backend imports `app.services.rag`
- **THEN** a hard exception SHALL be raised at import time naming both the configured model and the expected dim
- **AND** the service SHALL NOT start

### Requirement: Description chunker max chars is reduced from 200 to 120

The description chunker SHALL emit chunks of at most 120 characters each. Sentence and paragraph boundaries (Chinese full-width punctuation `。！？，；` plus newlines) SHALL be preserved as primary split points. URLs, hashtags, and emoji clusters SHALL NOT be broken mid-token. Short descriptions (< 120 chars) SHALL emit a single chunk unchanged.

#### Scenario: short description emits one chunk

- **GIVEN** an episode description of 60 characters
- **WHEN** the chunker runs
- **THEN** exactly one chunk SHALL be emitted with the full text

#### Scenario: long description splits on punctuation

- **GIVEN** a description of 400 characters with sentence boundaries at positions 80, 150, 220, 290, 360
- **WHEN** the chunker runs
- **THEN** chunks SHALL each be ≤ 120 chars
- **AND** chunks SHALL begin / end at sentence-boundary positions whenever possible
- **AND** no chunk SHALL exceed 120 chars

#### Scenario: URL not split mid-token

- **GIVEN** a description containing a URL of length 90 that straddles the 120-char boundary
- **WHEN** the chunker runs
- **THEN** the URL SHALL be kept intact in a single chunk even if that chunk exceeds 120 chars by URL length

## ADDED Requirements

### Requirement: `embedding_v2` columns and ivfflat indexes exist on chunk tables

The DB SHALL have nullable `embedding_v2 vector(3072)` columns on both `transcript_chunks` and `episode_description_chunks`. Each column SHALL have an `ivfflat` cosine ANN index with `lists` parameter scaled to row count (transcript: 200, description: 50). Migration SHALL be applied via alembic; downgrade SHALL fully remove columns and indexes.

#### Scenario: post-migration columns exist

- **GIVEN** alembic upgrade head has run successfully
- **WHEN** `\d transcript_chunks` is inspected
- **THEN** `embedding_v2 vector(3072)` SHALL be present
- **AND** `idx_transcript_chunks_emb_v2_cosine` USING ivfflat SHALL be present

#### Scenario: downgrade is clean

- **GIVEN** alembic upgrade head then alembic downgrade -1 have run
- **WHEN** `\d transcript_chunks` is inspected
- **THEN** `embedding_v2` column SHALL NOT exist
- **AND** `idx_transcript_chunks_emb_v2_cosine` SHALL NOT exist
