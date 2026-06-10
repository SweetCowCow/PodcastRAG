## ADDED Requirements

### Requirement: Semantic search consults the result cache and reports cache_hit

The semantic search endpoint SHALL consult the service-layer retrieval cache before computing embeddings and running hybrid retrieval, and SHALL include a `cache_hit` boolean in its response. On a cache hit the endpoint SHALL return the cached ranked chunks without recomputing. On a miss it SHALL compute normally and populate the cache. Cache failures SHALL fall back to the normal retrieval path without failing the request.

#### Scenario: Cache hit returns ranked chunks without recomputation

- **GIVEN** an identical semantic query was previously cached for a show with unchanged corpus and config versions
- **WHEN** the query is sent again
- **THEN** the response returns the same ranked chunks and `cache_hit` is true

#### Scenario: Cache miss computes and reports cache_hit false

- **GIVEN** no cached result exists for a semantic query
- **WHEN** the query is sent
- **THEN** the endpoint runs hybrid retrieval, returns ranked chunks, and `cache_hit` is false
