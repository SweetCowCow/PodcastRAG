# AI Steps Inventory

> **Source of truth** for what AI steps exist in the system, what model each is
> currently configured to use, and **why** that model was chosen. Updated by
> Claude whenever user instructs a model swap through chat (since user controls
> models via Claude rather than directly via the admin UI).
>
> Memory entries about AI steps point HERE, they don't store the facts
> themselves. **Drift check happens at session start** — see protocol below.

Last verified against prod: **2026-05-15 (post entity_extraction swap)** (via `GET /admin/ai-steps`)

## Current steps (6 total)

| step_key | step_type | When it runs | Model | base_url | API key | Reason for current choice |
|---|---|---|---|---|---|---|
| `transcription` | whisper | RSS → audio fetched → whisper transcribes | `whisper-1` | api.openai.com/v1 | OpenAI official | Only viable mass-market option for zh-TW transcription quality; no bake-off run |
| `embedding` | embedding | Each chunk → vector for pgvector store | `text-embedding-3-large` | api.openai.com/v1 | OpenAI official | Swapped from `-small` per `r3-4-embedding-model-swap` (archive 2026-05-13); -large gave meaningful retrieval recall improvement on Chinese, justified the 6.5x cost |
| `summary` | chat | Each episode → 60-char AI summary (also drives topic_seg) | `gemini-2.5-flash-lite` | hnd1.aihub.zeabur.ai/v1 (AI Hub) | AI Hub | Swapped from `gpt-5-mini` on 2026-05-10 — Azure content filter triggered on Chinese transcripts. Gemini-flash-lite is ~10x cheaper than gpt-5-mini and clears the filter. Also drives `topic_segmentation` (shares this config; see `app/services/topic_segmentation.py:299`) |
| `rewrite` | chat | User query → rewritten for retrieval | `gpt-4o-mini` | hnd1.aihub.zeabur.ai/v1 (AI Hub) | AI Hub | Cheap, fast, sufficient for query rewriting; never formally bake-off'd |
| `answer` | chat | Retrieved chunks → final answer | `gpt-4o` | hnd1.aihub.zeabur.ai/v1 (AI Hub) | AI Hub | Default since `admin-llm-step-config` (2026-05-03 archive); quality vs cost balance for production answering; user-facing latency acceptable |
| `entity_extraction` | chat | User query → `{date_range, guests, topics}` for metadata filter | `gemini-2.5-flash-lite` | hnd1.aihub.zeabur.ai/v1 (AI Hub) | AI Hub | **Swapped from gpt-4o-mini on 2026-05-15** per R3.3 phase 7.3 bake-off (n=30, F1 0.923 vs 0.857; cost 2.7x lower; no host-as-guest FP). See `docs/case-studies/r33-metadata-filter.md` Stage 2 |

## Notes on shape

- **No separate `topic_seg` row** — topic segmentation reads `summary`'s config at runtime. If summary swaps, topic_seg follows.
- **`embedding` and `transcription` must stay on OpenAI official** — AI Hub doesn't expose Whisper, and embedding vectors are stored long-term so swapping providers means re-embedding the whole corpus (~$expensive).
- **AI Hub gateway** (`hnd1.aihub.zeabur.ai/v1`) is OpenAI-protocol-compatible front-door to multiple providers (gpt-4o/gpt-4o-mini through OpenAI relay, gemini-2.5-flash-lite through Google relay, claude-haiku-4-5 through Anthropic relay). One key (`OPENAI_API_KEY` in backend env, despite the misleading name) covers all of them.

## Drift check protocol

**Every session-resume conversation that touches AI steps**, Claude SHALL:

1. Read this file
2. Run:
   ```bash
   # via E2E backdoor (per feedback_browser_verification.md SOP)
   curl -s -b /tmp/_c.txt https://api.podcastrag.app/admin/ai-steps | python3 -m json.tool
   ```
3. Compare prod `model` field per `step_key` against the table above
4. **If any drift detected**: alert user immediately with a diff table, ask which side is correct, then update either the doc or prod (via admin API or this chat)

This file's "Last verified against prod" timestamp at the top should be refreshed each time the protocol runs clean.

## Change log

| Date | step_key | From | To | Reason | Driver |
|---|---|---|---|---|---|
| 2026-05-03 | initial 5 steps seeded | – | (current) | `admin-llm-step-config` archive | – |
| 2026-05-10 | `summary` | `gpt-5-mini` | `gemini-2.5-flash-lite` | Azure content filter on zh transcripts | user instruction |
| 2026-05-13 | `embedding` | `text-embedding-3-small` | `text-embedding-3-large` | `r3-4-embedding-model-swap` archive | retrieval recall gain |
| 2026-05-14 | `entity_extraction` | (new) | `gpt-4o-mini` | R3.3 phase 6.5 added 6th step | migration default |
| 2026-05-15 | `entity_extraction` | `gpt-4o-mini` (OpenAI official) | `gemini-2.5-flash-lite` (AI Hub) | R3.3 phase 7.3 bake-off n=30: F1 0.923 vs 0.857, cost 2.7x lower | user instruction via chat |

## Related artifacts

- Dataset manifest → `backend/eval/datasets/README.md`
- Bake-off outputs → `docs/research/README.md` (local-only)
- Past archives that shaped these defaults: `admin-llm-step-config` · `r3-4-embedding-model-swap` · `r3-5-disable-routing`
