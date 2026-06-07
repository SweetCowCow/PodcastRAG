# Answer-model bake-off — 2026-06-07T11:59:22.305654+00:00

- subset: b23, b20, b11, b14, b15, b27, b29, b33, mt01 (all human-verified)
- original answer.model: `gpt-4o` (restored after run)
- b23 routing HARD GATE: first tool == `search_with_topic_prefilter` + EP107 cited

## Per-arm summary

| model | total cost (USD) | factual mean | chunk_recall mean | b23 first_tool | b23 EP107 | errors |
|---|---|---|---|---|---|---|
| gpt-4o (baseline) | 0.249029 | 0.739 | 0.55 | `search_across_episodes` | ✓ | 0 |
| gpt-4.1 | 0.241898 | 0.661 | 0.4 | `search_with_topic_prefilter` | ✓ | 0 |
| gpt-5.1 | 0.173334 | 0.861 | 0.5 | `search_with_topic_prefilter` | ✗ | 0 |
| gemini-2.5-flash | 0.0392 | 0.511 | 0.3 | `search_with_topic_prefilter` | ✗ | 0 |
| gemini-2.5-pro | 0.279385 | 0.769 | 0.6 | `search_with_topic_prefilter` | ✓ | 0 |

## Per-item × arm detail

| id | type | gpt-4o | gpt-4.1 | gpt-5.1 | gemini-2.5-flash | gemini-2.5-pro |
|---|---|---|---|---|---|---|
| b23 | cross_episode | f=0.5 r=0.25 search_across_episodes | f=0.4 r=0.0 prefilter | f=0.95 r=0.0 prefilter | f=0.7 r=0.0 prefilter | f=1.0 r=0.5 prefilter |
| b20 | cross_episode | f=1.0 r=0.5 prefilter | f=1.0 r=0.0 prefilter | f=1.0 r=0.5 prefilter | f=1.0 r=0.5 prefilter | f=0.92 r=0.5 prefilter |
| b11 | date_find | f=0.8 r=None find_episodes_by_date | f=0.4 r=None find_episodes_by_date | f=0.75 r=None prefilter | f=0.8 r=None prefilter | f=0.4 r=None prefilter |
| b14 | deep_dive | f=0.5 r=0.5 find_episode_by_ref | f=0.25 r=0.5 find_episode_by_ref | f=0.75 r=0.5 find_episode_by_ref | f=0.3 r=0.5 find_episode_by_ref | f=0.8 r=0.5 search_within_episode |
| b15 | deep_dive | f=1.0 r=1.0 find_episode_by_ref | f=1.0 r=1.0 find_episode_by_ref | f=1.0 r=1.0 find_episode_by_ref | f=0.0 r=0.0 search_within_episode | f=1.0 r=1.0 find_episode_by_ref |
| b27 | negative | f=1.0 r=None find_episode_by_ref | f=1.0 r=None find_episode_by_ref | f=1.0 r=None find_episode_by_ref | f=1.0 r=None search_within_episode | f=1.0 r=None find_episode_by_ref |
| b29 | leading_question_yes | f=0.85 r=None search_across_episodes | f=0.9 r=None prefilter | f=0.9 r=None prefilter | f=0.0 r=None prefilter | f=0.8 r=None prefilter |
| b33 | deep_dive | f=1.0 r=0.5 prefilter | f=1.0 r=0.5 search_across_episodes | f=1.0 r=0.5 prefilter | f=0.8 r=0.5 prefilter | f=1.0 r=0.5 prefilter |
| mt01 | multi_turn_ordinal | f=0.0 r=None find_episodes_by_topic | f=0.0 r=None find_episodes_by_topic | f=0.4 r=None prefilter | f=0.0 r=None prefilter | f=0.0 r=None prefilter |
