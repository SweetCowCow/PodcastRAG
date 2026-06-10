## ADDED Requirements

### Requirement: Keyword search consults the result cache and reports cache_hit

The keyword search endpoint SHALL consult the service-layer keyword result cache before running its three-stage SQL, and SHALL include a `cache_hit` boolean in its response. On a cache hit it SHALL return the cached T1/T2/T3 result without re-running SQL. On a miss it SHALL run normally and populate the cache. The cache key SHALL include the show id, corpus version, the normalized question, and the collapse threshold. Cache failures SHALL fall back to the normal SQL path without failing the request.

#### Scenario: Cache hit returns sectioned result without re-running SQL

- **GIVEN** an identical keyword query was previously cached for a show with unchanged corpus version
- **WHEN** the query is sent again
- **THEN** the response returns the same T1/T2/T3 sections and `cache_hit` is true

#### Scenario: Collapse threshold change invalidates the cached result

- **GIVEN** a keyword result is cached under the current collapse threshold
- **WHEN** an admin changes the keyword collapse threshold
- **THEN** the next identical keyword query misses the cache and reflects the new threshold
