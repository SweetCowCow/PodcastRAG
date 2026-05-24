## MODIFIED Requirements

### Requirement: System prompt instructs tool-eager grounded behaviour

The agent's system prompt (`chat_agent.prompts.SYSTEM_PROMPT`) SHALL contain sections that enforce tool-eager grounded behavior. The relative ordering of grounding-related sections SHALL be determined by the documented root-cause distribution (recorded in `backend/eval/results/hallucination_root_cause_distribution.json`) as follows:

1. **Role description** identifying the agent as PodcastRAG's chat agent SHALL always appear first.
2. **Tool-eager instruction** stating that the agent MUST call at least one tool before refusing or answering whenever the user asks about specific information (episode numbers, hosts, guests, content, show overview, theme, vibe) SHALL appear second. The instruction MUST explicitly include "show overview / 節目主題 / 節目在講什麼"类型查詢 as cases that require a tool call before answering — agents MUST NOT answer such queries from prior knowledge.
3. **Grounded-refusal instruction** stating that when all relevant tools return empty, the agent MUST explicitly say it cannot find X rather than fabricate, and when input schema is invalid, the agent MUST ask the user to clarify rather than guess.
4. **Fact-grounding rule** listing the six categories that MUST NEVER be fabricated (show title, host/guest name, EP number, episode title, guest quotes, statistical numbers). The relative position of this rule SHALL be:
   - If `tool_call_empty` ≥ 60% of severe hallucinations in the diagnose distribution: this rule SHALL appear immediately after the tool-eager instruction (i.e., before the tool-error-handling rule).
   - If `noise_induced` ≥ 60% of severe hallucinations: this rule SHALL include at least two `Example` blocks pairing a fabricated answer with the correct refusal template.
   - In all other cases: both the position change AND the example blocks SHALL be applied.
5. **Tool-error-handling rule** and **tool-routing hints** SHALL remain unchanged in content; only their relative position MAY shift to accommodate the grounding rule reordering.

#### Scenario: Specific-information query triggers tool call

- **GIVEN** the user asks "馬世芳上過哪一集？" (a specific information query about a guest)
- **WHEN** the agent processes the request
- **THEN** the agent SHALL call at least one tool (e.g., `find_episodes_by_guest`) before producing the final answer
- **AND** the answer SHALL NOT be a flat refusal without any tool invocation

#### Scenario: Show-overview query triggers tool call

- **GIVEN** the user asks "這節目在講什麼？" or "這個 podcast 主題是什麼？" (a show-overview / theme query)
- **WHEN** the agent processes the request
- **THEN** the agent SHALL call at least one tool (e.g., `list_episodes` to retrieve a recent episode description, or `find_show_by_name`) before producing the final answer
- **AND** the agent SHALL NOT answer from prior knowledge of the show title or theme

##### Example: show-overview tool-first behavior

- **GIVEN** the prompt explicitly lists show-overview as a tool-required category
- **WHEN** the user asks "也好吃這個 podcast 在講什麼？" (where "也好吃" does not exist in the database)
- **THEN** the agent SHALL call `find_show_by_name(name="也好吃")` (or equivalent listing tool)
- **AND** the tool SHALL return empty
- **AND** the agent SHALL reply "查不到「也好吃」這個節目" rather than fabricating a description

#### Scenario: Six-category fact grounding holds under noise

- **GIVEN** the user asks about a fact in one of the six grounded categories (show title, host/guest, EP number, episode title, quote, statistic)
- **AND** tool results return chunks that are topic-related but do not contain the specific fact
- **WHEN** the agent composes its answer
- **THEN** the agent SHALL respond with "資料不足，無法確認" or an equivalent grounded refusal
- **AND** the agent SHALL NOT infer or fabricate any value in the six categories from the noise chunks

##### Example: noise-induced refusal

- **GIVEN** the user asks "嘻哈饒舌歌唱比賽的冠軍是誰？" (chasing a guest name)
- **AND** the retrieval returns chunks about "大嘻哈時代" judges but no winner identity
- **WHEN** the agent composes its answer
- **THEN** the agent SHALL reply "節目未提及嘻哈饒舌歌唱比賽冠軍的資訊" rather than naming any judge as the winner

## ADDED Requirements

### Requirement: Hallucination regression SHALL trigger root-cause classification before prompt modification

When `extended-multi-turn-40.json` LLM-judge results show `hallucination_severe_count / n_turns_scored > 0.20` (i.e., regression past the baseline gate), the team SHALL run `backend/eval/scripts/classify_hallucination_root_cause.py` to produce `backend/eval/results/hallucination_root_cause_distribution.json` BEFORE modifying `SYSTEM_PROMPT`. Direct prompt edits without a corresponding distribution file SHALL be rejected at code review.

The distribution file SHALL classify each severe and mild turn into exactly one of: `tool_call_empty`, `noise_induced`, `wrong_tool_chosen`, `tool_returned_partial`. Every classified turn SHALL include an `evidence` field referencing tool_calls, tool_results, or final_answer content. No turn MAY have `root_cause = null` or an out-of-enum value.

#### Scenario: Regression triggers diagnose

- **GIVEN** a fresh LLM-judge run produces `hallucination_severe_count = 9` over 40 turns (0.225, exceeding 0.20 baseline)
- **WHEN** an engineer plans to edit `SYSTEM_PROMPT`
- **THEN** the engineer SHALL first run `classify_hallucination_root_cause.py`
- **AND** the resulting distribution JSON SHALL contain all 9 severe + all mild turns with non-null `root_cause`
- **AND** the prompt edit SHALL cite which root-cause cluster the change targets

#### Scenario: Distribution file rejects incomplete classification

- **GIVEN** the classifier returns `root_cause = null` for any turn
- **WHEN** the script writes the output JSON
- **THEN** the script SHALL exit with non-zero status
- **AND** SHALL NOT overwrite an existing distribution file with partial data

### Requirement: Hallucination gate for chat-agentic prompt changes

Any change that modifies `SYSTEM_PROMPT` grounding behavior SHALL re-run the agent evaluation against `extended-multi-turn-40.json` followed by the LLM judge using the same `judge_model = "gpt-4o"` and dataset. The change MAY be archived only if all three conditions hold against the new judge result:

- `hallucination_severe_count / n_turns_scored ≤ 0.10`
- `hallucination_mild_count / n_turns_scored ≤ 0.275`
- `answer_quality_mean ≥ 0.5375`

The judge result JSON SHALL include `meta.judge_model`, `meta.dataset_file`, and `meta.run_at` fields to permit later reproducibility.

#### Scenario: Gate passes

- **GIVEN** a re-judge run produces `hallucination_severe_count = 3` over 40 turns (0.075)
- **AND** `hallucination_mild_count = 9` (0.225)
- **AND** `answer_quality_mean = 0.58`
- **WHEN** the engineer requests archive
- **THEN** the change SHALL be eligible to archive

#### Scenario: Gate fails on severe

- **GIVEN** a re-judge run produces `hallucination_severe_count = 6` over 40 turns (0.15, exceeds 0.10)
- **WHEN** the engineer requests archive
- **THEN** the archive SHALL be blocked
- **AND** the team SHALL either revisit the diagnose branch or schedule a follow-up round

#### Scenario: Gate fails on quality regression

- **GIVEN** a re-judge run produces `hallucination_severe_count = 2` (passes severe gate)
- **AND** `answer_quality_mean = 0.50` (below 0.5375 baseline)
- **WHEN** the engineer requests archive
- **THEN** the archive SHALL be blocked because grounding cannot come at the cost of useful answers
