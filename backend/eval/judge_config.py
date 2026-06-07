"""Judge model configuration for RAG eval framework.

Production judge: gpt-5-nano (manually locked 2026-05-07).

Bake-off 2026-05-07 (GEval, 40-item mini-set, see
docs/research/r1-judge-bakeoff-2026-05-07.md):

    claude-haiku-4-5      Spearman 0.487  cost $0.198 / 40 items
    gpt-5-nano            Spearman 0.414  cost $0.012 / 40 items  ⭐ picked
    gemini-2.5-flash-lite Spearman 0.209  cost $0.016
    gpt-4o-mini           Spearman 0.100  cost $0.024

No candidate passed the 0.7 threshold — root cause is mini-set design
(human_score uses all-knowing-reader perspective; judge only sees
retrieved chunks). Picked gpt-5-nano for cost (16x cheaper than haiku
for ~0.07 Spearman delta, not significant). Calibration debt logged
for R1.3 (rebuild mini-set to "judge perspective" + re-bake).
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
