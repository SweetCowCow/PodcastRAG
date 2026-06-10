# rag-result-cache Specification

## Purpose

TBD - created by archiving change 'r4-rag-result-cache'. Update Purpose after archive.

## Requirements

### Requirement: Service-layer retrieval and embedding cache

The system SHALL cache retrieval and embedding results at the service layer so that the semantic search endpoint, the keyword search endpoint, and the chat agent's internal retrieval tools share a single cache. Embedding computation (`embed_texts` for a single query string) and hybrid retrieval (`retrieve_hybrid`) SHALL consult the cache before computing, and SHALL populate the cache on a miss. The cache SHALL be backed by Redis using the existing broker connection. The final LLM-generated chat answer SHALL NOT be cached.

#### Scenario: Repeated identical retrieval returns cached result

- **GIVEN** a query was previously executed for a show and its retrieval result was cached
- **WHEN** an identical query (same show, question, top_k, filters) is executed while corpus and config versions are unchanged
- **THEN** the cached ChunkHit list is returned without querying the database

#### Scenario: Repeated identical embedding skips the provider call

- **GIVEN** a query string was previously embedded and cached for an embedding model
- **WHEN** the same normalized string is embedded again with the same model
- **THEN** the cached vector is returned and no embedding provider call is made

#### Scenario: Chat agent internal tool searches share the cache

- **GIVEN** a chat agent tool issues a retrieval that was already cached by a prior request
- **WHEN** the tool runs
- **THEN** it returns the cached retrieval result rather than recomputing


<!-- @trace
source: r4-rag-result-cache
updated: 2026-06-10
code:
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640.md
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922.json
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640-answers.md
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640.json
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922-answers.md
  - backend/scripts/hyde_ab/results/calibrate-20260606T221058.json
  - skills-lock.json
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922.md
-->

---
### Requirement: Cache key composition

Cache keys SHALL be composed so that any input affecting the output changes the key. The retrieval key SHALL include show id, corpus version, retrieval config version, and a hash over the question text, the query embedding, top_k, the sorted episode id filter, and metadata filters. The embedding key SHALL include the embedding model and a hash of the normalized text. The keyword key SHALL include show id, corpus version, and a hash over the normalized question and the collapse threshold. Normalization SHALL trim, collapse runs of whitespace to a single space, and apply NFKC.

#### Scenario: Differing top_k produces a distinct key

- **GIVEN** two retrievals identical except for top_k
- **WHEN** their cache keys are computed
- **THEN** the keys differ and the two results are cached independently

#### Scenario: Normalization unifies whitespace variants

- **GIVEN** two query strings differing only by leading, trailing, or repeated whitespace
- **WHEN** their embedding keys are computed
- **THEN** the keys are equal


<!-- @trace
source: r4-rag-result-cache
updated: 2026-06-10
code:
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640.md
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922.json
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640-answers.md
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640.json
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922-answers.md
  - backend/scripts/hyde_ab/results/calibrate-20260606T221058.json
  - skills-lock.json
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922.md
-->

---
### Requirement: Version-based invalidation

The system SHALL invalidate cached retrieval and keyword results by version, not by explicit deletion. A per-show corpus version SHALL be stored as a Redis counter and SHALL be incremented when a transcription completes and when an ASR homophone correction is applied to existing episodes. A retrieval config version SHALL be computed per request from the settings that affect retrieval output, including the HyDE flag, RRF weights, the topic routing nudge flag, the two-layer routing flag, the embedding model, and the rerank flag. Cached entries SHALL also carry a fallback TTL.

#### Scenario: Corpus change invalidates only the affected show

- **GIVEN** cached results exist for show A and show B
- **WHEN** the corpus version for show A is incremented
- **THEN** subsequent identical queries for show A miss the cache while show B still hits

#### Scenario: Retrieval config change invalidates cached retrieval

- **GIVEN** a retrieval result is cached under the current config version
- **WHEN** an admin changes an RRF weight or toggles the HyDE flag
- **THEN** the next identical query misses the cache and reflects the new configuration


<!-- @trace
source: r4-rag-result-cache
updated: 2026-06-10
code:
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640.md
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922.json
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640-answers.md
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640.json
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922-answers.md
  - backend/scripts/hyde_ab/results/calibrate-20260606T221058.json
  - skills-lock.json
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922.md
-->

---
### Requirement: Fail-open behavior

The cache layer SHALL be fail-open. Any Redis error, serialization error, or deserialization error SHALL be caught and logged, and the caller SHALL fall back to the original computation path. A cache failure SHALL NOT cause a query to fail. A global setting SHALL allow disabling the exact-match cache entirely.

#### Scenario: Redis unavailable falls back to computation

- **GIVEN** Redis raises an error on a cache read or write
- **WHEN** a query executes
- **THEN** the query succeeds using the original retrieval path and the error is logged


<!-- @trace
source: r4-rag-result-cache
updated: 2026-06-10
code:
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640.md
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922.json
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640-answers.md
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640.json
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922-answers.md
  - backend/scripts/hyde_ab/results/calibrate-20260606T221058.json
  - skills-lock.json
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922.md
-->

---
### Requirement: cache_hit surfacing

The semantic search endpoint and the keyword search endpoint SHALL include a `cache_hit` boolean in their response indicating whether the result was served from cache. For the chat endpoint, per-tool cache hit information SHALL be exposed only through the existing admin debug trace gate and SHALL be omitted for non-admin callers.

#### Scenario: Semantic response reports cache hit

- **GIVEN** a semantic query whose retrieval was served from cache
- **WHEN** the response is returned
- **THEN** `cache_hit` is true

#### Scenario: Non-admin chat caller receives no per-tool cache info

- **GIVEN** a non-admin chat request without the admin debug trace parameter
- **WHEN** the response is returned
- **THEN** no per-tool cache hit fields are present


<!-- @trace
source: r4-rag-result-cache
updated: 2026-06-10
code:
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640.md
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922.json
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640-answers.md
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640.json
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922-answers.md
  - backend/scripts/hyde_ab/results/calibrate-20260606T221058.json
  - skills-lock.json
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922.md
-->

---
### Requirement: Cache prewarming for guided examples

After example prompts are generated for a show and for trending queries, the system SHALL prewarm the cache by executing those queries for the semantic and keyword modes so that the corresponding guided-example and trending requests hit the cache on first user access.

#### Scenario: Example prompt is warm on first click

- **GIVEN** example prompts were generated and prewarming ran for a show
- **WHEN** a user first clicks an example-prompt chip
- **THEN** the response reports `cache_hit` true


<!-- @trace
source: r4-rag-result-cache
updated: 2026-06-10
code:
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640.md
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922.json
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640-answers.md
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640.json
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922-answers.md
  - backend/scripts/hyde_ab/results/calibrate-20260606T221058.json
  - skills-lock.json
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922.md
-->

---
### Requirement: Semantic cache is flag-gated and disabled by default

The system SHALL provide a semantic cache as machinery that is disabled by default via a setting. The semantic cache SHALL apply only to the semantic mode. When enabled, after an exact-match retrieval miss it SHALL look up a prior result whose question embedding has cosine similarity at or above a configurable threshold (default 0.95), and SHALL record the matched similarity for auditing. It SHALL apply a query-quality filter that excludes overly short, punctuation-only, or whitespace-only queries from lookup and storage. When disabled, semantic lookup SHALL return no match with no added cost.

#### Scenario: Semantic cache disabled returns no match

- **GIVEN** the semantic cache setting is disabled (the default)
- **WHEN** a semantic-mode retrieval misses the exact-match cache
- **THEN** the semantic lookup returns no match and the original retrieval path runs

#### Scenario: Low-quality query is excluded

- **GIVEN** the semantic cache is enabled
- **WHEN** a query is shorter than the minimum length or is punctuation-only
- **THEN** the semantic cache neither serves nor stores a result for it

<!-- @trace
source: r4-rag-result-cache
updated: 2026-06-10
code:
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640.md
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922.json
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640-answers.md
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640.json
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922-answers.md
  - backend/scripts/hyde_ab/results/calibrate-20260606T221058.json
  - skills-lock.json
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922.md
-->