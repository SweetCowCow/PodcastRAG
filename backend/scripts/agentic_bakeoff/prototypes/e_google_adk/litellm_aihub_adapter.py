"""Task 4.1 spike — verify LiteLLM can talk to AI Hub OpenAI-compatible endpoint.

Acceptance criterion (design.md Risks):
  Within 30 min: one `litellm.completion(model="openai/gemini-2.5-flash",
  api_base=<aihub>, api_key=<aihub_key>, messages=[...])` returns a legal response.

Per memory `reference_env_openai_key.md`: env `OPENAI_API_KEY` is actually the
AI Hub key (real OpenAI key lives in DB api_keys table).

Run:
  cd backend && python -m scripts.agentic_bakeoff.prototypes.e_google_adk.litellm_aihub_adapter
"""
from __future__ import annotations

import os
import sys
import time


AIHUB_BASE = "https://hnd1.aihub.zeabur.ai/v1"
DEFAULT_MODEL = "openai/gemini-2.5-flash"


def get_aihub_key() -> str:
    """Pull AI Hub key. env OPENAI_API_KEY is the AI Hub key (not real OpenAI)."""
    key = os.environ.get("OPENAI_API_KEY") or os.environ.get("AIHUB_API_KEY")
    if not key:
        raise SystemExit(
            "Set OPENAI_API_KEY env var (per memory: env var is AI Hub key, "
            "not real OpenAI). For local: source backend/.env or export manually."
        )
    return key


def spike(model: str = DEFAULT_MODEL) -> dict:
    import litellm

    key = get_aihub_key()
    t0 = time.perf_counter()
    resp = litellm.completion(
        model=model,
        api_base=AIHUB_BASE,
        api_key=key,
        messages=[
            {"role": "system", "content": "You are a brief assistant."},
            {"role": "user", "content": "Reply with exactly: OK"},
        ],
        max_tokens=20,
        temperature=0.0,
    )
    latency_ms = (time.perf_counter() - t0) * 1000

    msg = resp.choices[0].message
    content = getattr(msg, "content", None) or ""
    usage = getattr(resp, "usage", None)

    out = {
        "model": model,
        "endpoint": AIHUB_BASE,
        "latency_ms": round(latency_ms, 1),
        "response_excerpt": content[:200],
        "usage": {
            "prompt_tokens": getattr(usage, "prompt_tokens", None) if usage else None,
            "completion_tokens": getattr(usage, "completion_tokens", None) if usage else None,
        },
        "ok": bool(content.strip()),
    }
    return out


def main():
    try:
        result = spike()
    except Exception as e:
        print(f"SPIKE FAILED: {type(e).__name__}: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)

    print("=== 4.1 LiteLLM AI Hub Spike ===")
    for k, v in result.items():
        print(f"  {k}: {v}")
    print()
    print("VERDICT:", "PASS — Framework E (ADK + LiteLLM) viable" if result["ok"]
          else "FAIL — Framework E swap required")


if __name__ == "__main__":
    main()
