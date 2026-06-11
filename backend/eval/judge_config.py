"""Judge model configuration for RAG eval framework.

Production judge: gemini-2.5-flash-lite (evidence-selected 2026-06-11,
change `r1-3-j-judge-harness-align`).

Aligned bake-off 2026-06-11 — production-judge harness (judge_chat_v2 +
chat_judge_v2.md, refusal-aware scalar) over the field-complete 40-item
mini-set; pass threshold 0.7 set from the observed distribution. Results:
backend/eval/results/judge-bakeoff-aligned-20260611T150450Z.json, evidence
log: docs/case-studies/r1-3-j-judge-harness-align-2026-06-11.md.

    gemini-2.5-flash-lite Spearman 0.8365  $0.0186 / 40 items  PASS ⭐ picked
    gpt-5.1               Spearman 0.8004  $0.1031 / 40 items  PASS
    gpt-5-nano            Spearman 0.6914  $0.0304 / 40 items  fail
    gemini-3.5-flash      Spearman 0.6222  $0.5634 / 40 items  fail
    claude-haiku-4-5      SKIPPED (AI Hub + response_format=json_object
                          returns empty {} for claude models)

Selection rule: highest Spearman among threshold passers, lowest cost on
ties — gemini-2.5-flash-lite wins on both axes. The historical 0.414 number
(2026-05-07) measured a stand-in harness, not this judge; the old
comment/constant drift (comment said gpt-5-nano, constant said
gemini-2.5-flash-lite) is hereby reconciled from this re-run's evidence.
"""

PRODUCTION_JUDGE_MODEL = "gemini-2.5-flash-lite"
JUDGE_PROVIDER_BASE_URL = "https://hnd1.aihub.zeabur.ai/v1"

# 1M-token pricing snapshot (USD), 2026-05-05 from Zeabur AI Hub.
# Used by judge_bakeoff.py to estimate per-run cost.
HUB_PRICING_USD_PER_1M = {
    "gpt-5-nano":              {"input": 0.05, "output": 0.40},
    "gemini-2.5-flash-lite":   {"input": 0.10, "output": 0.40},
    "gpt-4o-mini":             {"input": 0.15, "output": 0.60},
    "claude-haiku-4-5":        {"input": 1.10, "output": 5.50},
    "gpt-4o":                  {"input": 2.50, "output": 10.00},
}
