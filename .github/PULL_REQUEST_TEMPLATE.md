<!-- PR template — keep concise. Strike out sections that don't apply. -->

## What changed

<!-- One sentence: 系統觀感 / 使用者影響。 -->

## Why

<!-- Linked issue / case study / Spectra change name -->

---

## Retrieval change checklist

> Run these when this PR touches `backend/app/services/rag.py`, `episode_finders.py`,
> `episode_ref.py`, RRF weights, retrieval SQL templates, or any code path that
> influences `retrieve_hybrid` ranking. Background: 2026-05-28 step1-idf-and-prefilter
> shipped & regressed because show-wide DB probe was a false-positive validator.
> See `docs/case-studies/retrieve-quality-step1-idf-and-prefilter-2026-05-28.md`.

- [ ] Ran `retrieve_probe.py` against calibration set:
  ```
  python -m backend.eval.scripts.retrieve_probe \
    --show-id 45fc2462-17cf-42f5-98a7-68fe1a222228 \
    --episode-id <ep> --query "<q>" --top-k 20 \
    --dataset backend/eval/datasets/_calibration_8.json --item-id <id>
  ```
- [ ] Paste probe output for at least one **deep_dive (b18)** + one **cross_episode (b20)** item.
- [ ] Confirm `← GT` marker still appears in top-K for items where it appeared at baseline.

<details><summary>Probe output (paste here)</summary>

```
<paste retrieve_probe.py stdout>
```

</details>

---

## Prompt change checklist

> Run these when this PR touches `backend/app/services/chat_agent/system_prompt.*`,
> tool docstrings, or any prompt example. Background: prompt changes are NEVER
> orthogonal to retrieval — agent rephrases `search_*(query: str)` and `ts_rank`
> follows. See same case study above.

- [ ] Ran `prompt_fingerprint_diff.py` between current prod backend and PR preview:
  ```
  python -m backend.eval.scripts.prompt_fingerprint_diff \
    --old-backend https://podcastrag-api.zeabur.app \
    --new-backend <preview URL> \
    --dataset backend/eval/datasets/_calibration_8.json \
    --session-cookie-file /tmp/podcastrag_session.txt \
    --me-json /tmp/me_resp.json \
    --output /tmp/prompt-fingerprint.md
  ```
- [ ] Reviewed each `❗ changed` row. Drift is **expected & intended** for items <list>, **not expected** for items <list>.
- [ ] If any unexpected drift: paused, re-examined prompt, or accepted with rationale.

<details><summary>Fingerprint diff output (paste here)</summary>

```markdown
<paste prompt_fingerprint_diff.py output>
```

</details>

---

## Tests

- [ ] Unit tests pass
- [ ] Manual smoke pass

## Risks / rollback

<!-- How to roll back if this breaks prod -->
