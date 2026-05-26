## ADDED Requirements

### Requirement: chat-rag LLM judge prompt SHALL incorporate agent tool I/O for grounding

The chat-rag LLM judge SHALL be invoked via a dedicated prompt template at `backend/eval/prompts/chat_judge_v2.md`. The judge input SHALL be a structured JSON payload containing:

- `question`: the user prompt (turn-level for multi-turn)
- `expected_answer_summary`: natural-language expected answer
- `expected_answer_aliases`: optional alias mapping for ASR / synonym handling
- `expected_must_contradict_check`: optional natural-language statement of what the answer MUST NOT contain
- `agent_answer`: the agent's NL answer text
- `tool_calls`: array of objects, each containing `name` (tool name), `args` (argument dict), and `result_summary` (the tool's response truncated to the first 800 characters, with `[truncated]` appended if longer)

The judge SHALL be a single LLM call that returns a strict JSON object with three top-level keys:

- `factual_correctness`: `{"score": float in [0.0, 1.0], "rationale": string}` — semantic comparison of `agent_answer` against `expected_answer_summary` with alias substitution applied before comparison
- `refusal_appropriateness`: `{"verdict": "appropriate" | "should_refuse" | "should_answer", "is_refusal_with_correction": boolean, "rationale": string}` — three-state refusal judgment; `is_refusal_with_correction` is true when the agent refuses the primary question AND volunteers correct context (e.g., b27 declines the championship claim but identifies the guest as a competition judge)
- `answer_contradict_check`: `{"passed": boolean, "rationale": string}` or `null` — only populated when the input includes a non-null `expected_must_contradict_check`; `passed: false` means the answer contains content matching the contradiction pattern

The judge prompt SHALL include at least two few-shot examples drawn from the audited 7 items (e.g., b14 contradiction case + b15 alias case) to anchor the rubric. The judge prompt SHALL be cache-friendly: the static prefix (rules + few-shot examples) SHALL be at least 1024 tokens to qualify for Anthropic prompt-cache eligibility.

The judge SHALL be invoked via the same OpenAI-compatible client used by existing graders (Zeabur AI Hub `https://hnd1.aihub.zeabur.ai/v1`). The judge model identifier SHALL be read from `backend/eval/judge_config.py`'s `PRODUCTION_JUDGE_MODEL` constant (set by the existing bake-off selection rule).

#### Scenario: judge returns three structured verdicts in a single call

- **GIVEN** an audited item (e.g., b14) and the corresponding agent response with tool_calls
- **WHEN** the chat-rag judge is invoked with the v2 prompt
- **THEN** the response SHALL be valid JSON containing top-level keys `factual_correctness`, `refusal_appropriateness`, and `answer_contradict_check`
- **AND** `factual_correctness.score` SHALL be a float between 0.0 and 1.0 inclusive
- **AND** `refusal_appropriateness.verdict` SHALL be one of `"appropriate"`, `"should_refuse"`, `"should_answer"`

#### Scenario: judge sees tool I/O via the tool_calls payload

- **GIVEN** an item with `expected_tool_calls_required: ["find_episode_by_ref", "search_within_episode"]`
- **AND** the agent's response contains both tool calls with non-empty result_full
- **WHEN** the judge prompt is rendered
- **THEN** the input payload's `tool_calls` array SHALL contain one entry per tool call, each with `name`, `args`, and `result_summary` populated
- **AND** every `result_summary` value SHALL be no longer than 800 characters, with `[truncated]` appended when the original result exceeded that length

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

#### Scenario: judge call retries once on malformed JSON

- **GIVEN** the judge model returns a non-JSON or invalid-shape response
- **WHEN** the runner receives the response
- **THEN** the runner SHALL retry the judge call exactly once with identical input
- **AND** if the retry also fails the runner SHALL record `factual_correctness`, `refusal_appropriateness`, and `answer_contradict_check` (when applicable) as the literal string `"error"` for this item
- **AND** the failure SHALL NOT abort the eval run for remaining items

---

### Requirement: judge prompt template SHALL be version-pinned and externalised

The chat-rag judge prompt SHALL live at `backend/eval/prompts/chat_judge_v2.md` as a markdown file outside the Python source tree. The runner SHALL load the prompt text at startup and SHALL pin the prompt content's SHA-256 hash to each eval run report so prompt changes are auditable in baseline diffs.

#### Scenario: prompt hash appears in eval report

- **GIVEN** a completed eval run
- **WHEN** the markdown report at `backend/eval/results/<run-id>/report.md` is read
- **THEN** the report SHALL contain a line of the form `judge_prompt_sha256: <64-hex-chars>`
- **AND** the hash SHALL match the SHA-256 of the on-disk `chat_judge_v2.md` content at run time
