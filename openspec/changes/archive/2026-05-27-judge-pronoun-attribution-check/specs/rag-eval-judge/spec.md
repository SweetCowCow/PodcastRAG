## MODIFIED Requirements

### Requirement: chat-rag LLM judge prompt SHALL incorporate agent tool I/O for grounding

The chat-rag LLM judge SHALL be invoked via a dedicated prompt template at `backend/eval/prompts/chat_judge_v2.md`. The judge input SHALL be a structured JSON payload containing:

- `question`: the user prompt (turn-level for multi-turn)
- `expected_answer_summary`: natural-language expected answer
- `expected_answer_aliases`: optional alias mapping for ASR / synonym handling
- `expected_must_contradict_check`: optional natural-language statement of what the answer MUST NOT contain
- `agent_answer`: the agent's NL answer text
- `tool_calls`: array of objects, each containing `name` (tool name), `args` (argument dict), and `result_full` (the tool's complete result string, capped at `agentic_tool_result_max_chars` which defaults to 8000 characters; the truncation suffix `... (truncated, <N> chars omitted)` SHALL be preserved when present)

The judge SHALL be a single LLM call that returns a strict JSON object with four top-level keys:

- `factual_correctness`: `{"score": float in [0.0, 1.0], "rationale": string}` — semantic comparison of `agent_answer` against `expected_answer_summary` with alias substitution applied before comparison
- `refusal_appropriateness`: `{"verdict": "appropriate" | "should_refuse" | "should_answer", "is_refusal_with_correction": boolean, "rationale": string}` — three-state refusal judgment; `is_refusal_with_correction` is true when the agent refuses the primary question AND volunteers correct context (e.g., b27 declines the championship claim but identifies the guest as a competition judge)
- `answer_contradict_check`: `{"passed": boolean, "rationale": string}` or `null` — only populated when the input includes a non-null `expected_must_contradict_check`; `passed: false` means the answer contains content matching the contradiction pattern
- `pronoun_attribution_check`: `{"verdict": "grounded" | "inferred" | "hallucinated", "rationale": string}` or `null` — only populated when the agent answer mentions at least one specific person name AND the expected answer involves a relationship or interaction between two or more named entities; verdict semantics:
  - `grounded` — at least one `tool_calls.result_full` chunk text directly contains the person name that appears in `agent_answer`
  - `inferred` — chunks contain pronouns (e.g., 「他」「她」「我」) without explicit name, but the surrounding text establishes a clear anchor pointing to the named person in `agent_answer` (e.g., the chunk says "Leo 王 來當暖場 / 他唱了一首歌" — the second-sentence pronoun anchors to Leo 王 in the first sentence)
  - `hallucinated` — chunks contain pronouns whose nearest anchor in the chunk text is a DIFFERENT person than the one the `agent_answer` attributes the action to (e.g., chunk discusses 呂安 and uses 「他」, but `agent_answer` claims Leo 王 performed those actions); OR the chunks contain no anchor at all and the agent_answer attribution is unsupported

The judge prompt SHALL include at least three few-shot examples drawn from the audited items (b14 contradiction case + b15 alias case + b23 pronoun_attribution_check `hallucinated` case) to anchor the rubric. The judge prompt SHALL be cache-friendly: the static prefix (rules + few-shot examples) SHALL be at least 1024 tokens to qualify for Anthropic prompt-cache eligibility.

The judge SHALL be invoked via the same OpenAI-compatible client used by existing graders (Zeabur AI Hub `https://hnd1.aihub.zeabur.ai/v1`). The judge model identifier SHALL be read from `backend/eval/judge_config.py`'s `PRODUCTION_JUDGE_MODEL` constant (set by the existing bake-off selection rule).

#### Scenario: judge returns four structured verdicts in a single call

- **GIVEN** an audited item (e.g., b23) and the corresponding agent response with tool_calls containing `result_full` populated
- **WHEN** the chat-rag judge is invoked with the v2 prompt
- **THEN** the response SHALL be valid JSON containing top-level keys `factual_correctness`, `refusal_appropriateness`, `answer_contradict_check`, and `pronoun_attribution_check`
- **AND** `factual_correctness.score` SHALL be a float between 0.0 and 1.0 inclusive
- **AND** `refusal_appropriateness.verdict` SHALL be one of `"appropriate"`, `"should_refuse"`, `"should_answer"`

#### Scenario: judge sees full tool result text via the tool_calls payload

- **GIVEN** an item with `expected_tool_calls_required: ["search_with_topic_prefilter"]`
- **AND** the agent's response contains the tool call with a non-empty `result_full` of length 6500 characters
- **WHEN** the judge prompt is rendered
- **THEN** the input payload's `tool_calls` array SHALL contain one entry whose `result_full` value is the complete 6500-character tool result
- **AND** when the original result exceeded `agentic_tool_result_max_chars` (default 8000) the value SHALL preserve the literal suffix `... (truncated, <N> chars omitted)` from the agent loop's truncation
- **AND** the field name SHALL be `result_full` (NOT `result_summary`)

#### Scenario: answer_contradict_check is null when the item lacks a contradiction directive

- **GIVEN** an item without `expected_must_contradict_check` set (e.g., b15)
- **WHEN** the judge is invoked
- **THEN** the response's `answer_contradict_check` field SHALL be `null`

#### Scenario: refusal_with_correction bonus is recognized

- **GIVEN** the b27 item with `expected_behavior: "refusal_with_correction"`
- **AND** the agent's answer declines the championship premise AND identifies the guest as a "大嘻哈評審" (competition judge)
- **WHEN** the judge is invoked
- **THEN** `refusal_appropriateness.verdict` SHALL be `"appropriate"`
- **AND** `refusal_appropriateness.is_refusal_with_correction` SHALL be `true`

#### Scenario: pronoun_attribution_check detects hallucinated person attribution

- **GIVEN** the b23 item with `agent_answer` claiming Leo 王 was the audience-of-two protagonist
- **AND** `tool_calls.result_full` contains EP129 chunk text where the audience-of-two story is told via pronouns (「他說觀眾席裡就兩個人 一個是他一個是國蛋」) and the nearest narrative anchor in the chunk is 呂安 (introduced earlier as 茉莉書房 主持人), NOT Leo 王
- **WHEN** the judge is invoked
- **THEN** `pronoun_attribution_check.verdict` SHALL be `"hallucinated"`
- **AND** the rationale SHALL reference the chunk's actual pronoun anchor (e.g., "呂安" or "chunk 內 anchor 非 Leo 王" or equivalent ≤ 80 繁體中文 phrasing)

#### Scenario: pronoun_attribution_check accepts legitimate pronoun inference

- **GIVEN** an item where `agent_answer` mentions a person by name (e.g., "Leo 王 唱了一首歌")
- **AND** `tool_calls.result_full` contains chunks where the person's full name appears in the preceding sentence and the action is described in a following sentence using a pronoun ("Leo 王 來當暖場 / 他唱了一首歌")
- **WHEN** the judge is invoked
- **THEN** `pronoun_attribution_check.verdict` SHALL be `"inferred"`

#### Scenario: pronoun_attribution_check is null when the item does not involve multi-person attribution

- **GIVEN** an item like b04 ("節目大概多久更新一集？") where the expected answer does not involve attributing actions to specific named persons
- **WHEN** the judge is invoked
- **THEN** `pronoun_attribution_check` SHALL be `null`

#### Scenario: judge call retries once on malformed JSON

- **GIVEN** the judge model returns a non-JSON or invalid-shape response
- **WHEN** the runner receives the response
- **THEN** the runner SHALL retry the judge call exactly once with identical input
- **AND** if the retry also fails the runner SHALL record `factual_correctness`, `refusal_appropriateness`, `answer_contradict_check` (when applicable), and `pronoun_attribution_check` (when applicable) as the literal string `"error"` for this item
- **AND** the failure SHALL NOT abort the eval run for remaining items
