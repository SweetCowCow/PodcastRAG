## MODIFIED Requirements

### Requirement: Semantic search endpoint returns ranked chunks

The backend SHALL expose `POST /shows/{show_id}/search` which SHALL be guarded by the `optional_auth_with_ip_limit` dependency (see auth-system + ip-rate-limit capabilities). The endpoint accepts body `{"question": "<non-empty string>", "k": <optional int 1-50, default 8>}`. The endpoint SHALL embed the question using the configured embedding step, jieba-tokenise the question for lexical matching using the current custom dictionary (see tokenizer-dictionary capability), and perform hybrid retrieval combining semantic (pgvector cosine distance) and lexical (PostgreSQL tsvector ts_rank) signals via Reciprocal Rank Fusion. Retrieval SHALL be performed against three lexical pools — `transcript_chunks.text_tsvector`, `episode_description_chunks.text_tsvector`, AND `episodes.title_tsvector` — combined with the semantic pool over `transcript_chunks` AND `episode_description_chunks`, with each pool weighted by a configurable Python-side constant `RRF_WEIGHTS` defined in `backend/app/services/rag.py`. The default values after this change SHALL be those selected by the weight sweep documented at `docs/case-studies/rrf-cross-episode-weight-sweep-2026-05-26.md`; the sweep procedure SHALL bump the `description` pool weight relative to the prior baseline (chunk × 1.0, description × 0.7, title × 0.5) to address cross-episode chunk_recall degradation, AND the chosen weights SHALL satisfy the acceptance gate defined in `Requirement: RRF weight changes SHALL satisfy a non-regression gate`. All pools SHALL be filtered to the specified `show_id`, ranked individually, then unioned by RRF score. Each result SHALL carry a `source` discriminator equal to `"transcript"`, `"description"`, or `"title"`. The endpoint SHALL NOT include any LLM-generated answer. The endpoint SHALL NOT decrement `quota_remaining` even for authenticated callers.

#### Scenario: RRF combines semantic and lexical ranks across three pools

- **GIVEN** chunk `A` ranks 3 in semantic, 25 in chunk-lexical, absent from description-lexical, absent from title-lexical
- **AND** the configured `RRF_WEIGHTS` are loaded from `backend/app/services/rag.py`
- **WHEN** the endpoint computes RRF scores with constant `k=60`
- **THEN** chunk `A`'s RRF score SHALL be `1/(60+3) + RRF_WEIGHTS["chunk"] × 1/(60+25) + RRF_WEIGHTS["description"] × 1/(60+999) + RRF_WEIGHTS["title"] × 1/(60+999)` (absent-side ranks are sentinel 999)

#### Scenario: Title-pool match contributes lexical signal

- **GIVEN** episode `E1` has title `"Ft. 馬世芳"` and the user query is `"馬世芳"`
- **WHEN** the title lexical pool is queried via jieba tokeniser
- **THEN** `E1`'s title SHALL match the tsquery and the corresponding result SHALL appear in the union with `source = "title"`
- **AND** all transcript chunks belonging to `E1` SHALL retain their original `source` discriminator

#### Scenario: Description and transcript results unified by RRF score

- **GIVEN** a transcript chunk with RRF score 0.020 and a description chunk with RRF score 0.025
- **WHEN** the endpoint constructs the final ranked list
- **THEN** the description chunk SHALL appear before the transcript chunk in the response
- **AND** each result SHALL include `source: "transcript"`, `"description"`, or `"title"` matching its origin

#### Scenario: Anonymous request under rate limit returns top-K hybrid results

- **GIVEN** an unauthenticated visitor whose IP counter is 5 and `ip_search_rate_limit_per_day=20`
- **WHEN** they POST `/shows/<id>/search` with a non-empty question
- **THEN** the endpoint SHALL return up to `k` hybrid-ranked chunks combining transcript and description sources
- **AND** the IP counter SHALL be incremented to 6

## ADDED Requirements

### Requirement: RRF weight changes SHALL satisfy a non-regression gate

Any change to the `RRF_WEIGHTS` constant in `backend/app/services/rag.py` SHALL pass a measurement gate before being merged. The gate is operationalised by a one-shot sweep harness at `backend/eval/scripts/rrf_weight_sweep.py` which, for each candidate weight tuple, computes:

- `cross_episode_recall_mean`: mean `chunk_recall_grouped` score across the cross-episode focused mini-set (item ids `b20`, `b21`, `b23`)
- `deep_dive_recall_mean`: mean `chunk_recall_grouped` score across the deep_dive items in the v2 dataset that carry chunk-level GT (item ids `b15`, `b16`, `b17`, `b19`)

A candidate weight tuple SHALL be accepted only if BOTH conditions hold:

1. `cross_episode_recall_mean` SHALL be strictly greater than the baseline measured under the prior weights (chunk × 1.0, description × 0.7, title × 0.5)
2. `deep_dive_recall_mean` SHALL NOT decrease by more than 0.05 absolute compared to the prior baseline (a small regression is permitted to reflect natural noise; >0.05 is treated as material regression and rejects the candidate)

The selected tuple, the full sweep table, and the prior baseline numbers SHALL be persisted in `docs/case-studies/rrf-cross-episode-weight-sweep-2026-05-26.md`.

#### Scenario: Candidate weights with cross-episode gain and no deep-dive regression are accepted

- **GIVEN** the prior baseline cross_episode_recall_mean is 0.33 and deep_dive_recall_mean is 0.75
- **AND** a candidate weight tuple yields cross_episode_recall_mean 0.55 and deep_dive_recall_mean 0.73
- **WHEN** the sweep harness evaluates the gate
- **THEN** the candidate SHALL be marked `accepted` in the sweep table
- **AND** the candidate SHALL be eligible for selection as the new `RRF_WEIGHTS` default

#### Scenario: Candidate weights with cross-episode gain but unacceptable deep-dive regression are rejected

- **GIVEN** the prior baseline deep_dive_recall_mean is 0.75
- **AND** a candidate weight tuple yields deep_dive_recall_mean 0.68 (regression of 0.07 absolute)
- **WHEN** the sweep harness evaluates the gate
- **THEN** the candidate SHALL be marked `rejected` in the sweep table regardless of cross_episode gain
- **AND** the candidate SHALL NOT be selected as the new `RRF_WEIGHTS` default

#### Scenario: Candidate weights with no cross-episode gain are rejected

- **GIVEN** the prior baseline cross_episode_recall_mean is 0.33
- **AND** a candidate weight tuple yields cross_episode_recall_mean 0.33 (no gain)
- **WHEN** the sweep harness evaluates the gate
- **THEN** the candidate SHALL be marked `rejected` (failing condition 1)
- **AND** the prior baseline weights SHALL remain the default

#### Scenario: Sweep result is persisted before merge

- **GIVEN** the sweep harness has been executed and produced a sweep table
- **WHEN** the RRF_WEIGHTS constant in rag.py is updated
- **THEN** the commit changing rag.py SHALL include or reference `docs/case-studies/rrf-cross-episode-weight-sweep-2026-05-26.md`
- **AND** that file SHALL contain the full sweep table with at least 3 candidate tuples evaluated plus the baseline row
