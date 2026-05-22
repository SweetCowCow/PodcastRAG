## ADDED Requirements

### Requirement: Public search endpoint SHALL detect episode references in the query and filter retrieval to those episodes

The `POST /shows/{show_id}/search` endpoint SHALL run an episode-reference detector against the incoming `question` before invoking `retrieve_hybrid`. The detector is implemented by `backend/app/services/episode_ref.py::extract_episode_ids_from_query(db, show_id, query) -> list[uuid.UUID]` and SHALL:

- Use a case-insensitive regex matching the literal token `EP` followed by optional whitespace and one or more digits (pattern equivalent to `EP\s*(\d+)`) to extract every episode number mentioned in the query.
- For each extracted number, look up the episode UUID in the `episodes` table scoped to the given `show_id`, matching by `title` regex `^EP<N>(\D|$)` so that `EP1` does not collide with `EP10` / `EP143`.
- Skip numbers without a matching episode row and emit a `logger.warning` so operators can spot user typos (`EP999`) or schema drift, without surfacing the failure to the caller.
- Return the matching UUIDs deduplicated, preserving the order in which they first appear in the query (so the caller can reason about which reference came first).

When the detector returns a non-empty list, the endpoint SHALL pass it as `episode_id_filter` to `retrieve_hybrid`, overriding `routed_eps` from the two-layer router (which is currently default-off but kept as a kill-switch). When the detector returns an empty list, the endpoint SHALL preserve its prior behavior unchanged (use `routed_eps` if the router activated, otherwise no filter).

#### Scenario: Query with single EP reference filters retrieval to that episode

- **GIVEN** a `POST /shows/{show_id}/search` call with `question` `"迪拉胖在 EP134 為什麼不挑振奮的開工歌"`
- **AND** the show has an episode titled `EP134｜馬力全開的開工歌單`
- **WHEN** the endpoint processes the request
- **THEN** the detector SHALL return a one-element list containing that episode's UUID
- **AND** every chunk in the response SHALL belong to that episode

#### Scenario: Query with multiple EP references filters to the union

- **GIVEN** a query `"比較 EP134 跟 EP143 的開工歌單觀念差異"`
- **AND** both episodes exist on the show
- **WHEN** the endpoint processes the request
- **THEN** the detector SHALL return a two-element list with both UUIDs in `[EP134, EP143]` order
- **AND** every chunk in the response SHALL belong to one of those two episodes

#### Scenario: Query without EP reference behaves as before

- **GIVEN** a query `"歌單那幾集"` (no `EP<N>` token)
- **WHEN** the endpoint processes the request
- **THEN** the detector SHALL return an empty list
- **AND** the endpoint SHALL invoke `retrieve_hybrid` with `episode_id_filter = routed_eps` (the pre-existing behavior)

#### Scenario: Query references a non-existent episode

- **GIVEN** a query `"EP999 講了什麼"` on a show with no `EP999` episode
- **WHEN** the endpoint processes the request
- **THEN** the detector SHALL return an empty list
- **AND** a `logger.warning` SHALL be emitted indicating the missing episode number
- **AND** the endpoint SHALL invoke `retrieve_hybrid` without an episode-id filter (fall through, not an error)

#### Scenario: Number boundary disambiguation

- **GIVEN** the show has both `EP1` and `EP143`
- **AND** the query is `"EP1 講了什麼"`
- **WHEN** the detector runs
- **THEN** the returned UUID list SHALL contain only `EP1`'s UUID (NOT `EP143`'s)
