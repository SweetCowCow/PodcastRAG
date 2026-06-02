"""LLM homophone detection — first correction layer (EQ2b).

Part of change `asr-llm-homophone-postprocess`. After Whisper produces an
episode transcript and before segments are persisted, this module asks an LLM
to find homophone mis-transcriptions (unknown proper nouns the recogniser
heard as same-sounding wrong characters) and returns word-level
`CorrectionRule` pairs.

Design contract (see design.md):
- D1: the LLM judges over the WHOLE episode for context but only ever outputs
  word-level `{wrong, correct}` pairs — never rewritten text — so the existing
  `apply_corrections` literal substitution keeps segment timestamps intact.
- D2: returned pairs are applied to the current episode immediately AND
  persisted as pending candidates; the two paths are independent.
- D3/D4: candidates are persisted `status='pending'`, `enabled=false`,
  `scope='show'`; a `(wrong, scope, show_id)` collision with any existing rule
  (any status) is skipped without insert or status change.
- D5: model + prompt resolve from the `asr_homophone` AI step. AI Hub does not
  guarantee `response_format=json_object`, so parsing strips a markdown code
  block before `json.loads`.
- D6: fail-open — any LLM/parse error logs a warning and yields an empty pair
  list so transcription proceeds with dictionary-only correction.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import UUID

from openai import OpenAI
from sqlalchemy import and_, func, or_, select

from app.models.asr_correction_term import AsrCorrectionTerm
from app.services.ai_step_resolver import get_step_config
from app.services.asr_correction import CorrectionRule

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

ASR_HOMOPHONE_STEP_KEY = "asr_homophone"

# Detection instruction (the rules half of the prompt). The other half — the
# per-show candidate-entity list — is appended at call time by
# build_detection_prompt. This is the RAGEC (Retrieval-Augmented Generative
# Error Correction) framing: instead of asking the model to FREELY hunt for
# typos (which over-corrects on weak models and hallucinates on strong ones —
# see the EQ2b pilot), we GROUND it with the show's known correct names and ask
# it to map ASR mis-hearings back onto that closed list. This is the dominant
# 2024-2026 best practice for ASR named-entity correction.
#
# Stored here as the single source of truth; an admin may override just this
# instruction via the step's extra_config['prompt'] (the candidate list is still
# appended in code).
DEFAULT_HOMOPHONE_INSTRUCTION = (
    "你是中文 podcast 逐字稿的專有名詞校對員。語音辨識（ASR）常把人名 / 樂團名 / "
    "藝名聽成同音或近音的錯字。下面會給你「本節目已知的正確專有名詞清單」。\n\n"
    "你的任務：在逐字稿中找出「原意應該是清單裡某個名字、卻被聽成別的同音 / 近音字」"
    "的地方，輸出『錯字 → 正字』的詞級替換。\n\n"
    "嚴格規則：\n"
    "1. correct 必須是清單裡的某個名字；不在清單上的詞一律不回。\n"
    "2. wrong 必須原樣出現在逐字稿中，且與 correct 同音或極近音；只是字不同但讀音差很多的不回。\n"
    "3. 清單裡的名字若在逐字稿中已經拼寫正確，不要回（不是錯字）。\n"
    "4. 不確定就不回（寧缺勿濫，避免誤改）。\n"
    "5. 嚴格只輸出 JSON 陣列：[{\"wrong\": \"錯字\", \"correct\": \"正字\"}]；沒有則回 []。\n"
    "範例：清單含「方品融」，逐字稿出現「方品龍」 → [{\"wrong\": \"方品龍\", \"correct\": \"方品融\"}]"
)

# Kept as an alias so the seeded migration value / any importer does not break.
DEFAULT_HOMOPHONE_PROMPT = DEFAULT_HOMOPHONE_INSTRUCTION


def build_detection_prompt(
    candidate_entities: list[str], instruction: str | None = None
) -> str:
    """Compose the full system prompt: the instruction + the candidate list.

    `instruction` overrides DEFAULT_HOMOPHONE_INSTRUCTION (e.g. from the step's
    extra_config['prompt']). The candidate list is always appended in code so
    the grounding cannot be accidentally dropped by an admin edit.
    """
    base = instruction or DEFAULT_HOMOPHONE_INSTRUCTION
    names = "、".join(candidate_entities)
    return f"{base}\n\n[本節目已知正確專有名詞清單]\n{names}"


async def load_candidate_entities(
    session: "AsyncSession", show_id: UUID, *, extra: list[str] | None = None
) -> list[str]:
    """Build the RAGEC candidate-entity list for a show: the union of

    - every distinct guest name across the show's episodes (`episodes.guests`),
    - the correct-forms of approved correction rules applicable to the show
      (global + this show), and
    - any `extra` names the caller supplies (e.g. hosts, which have no
      structured source yet).

    Deduplicated, blank-stripped, stable-ordered (longest first so a longer name
    is offered before a substring of it).
    """
    from app.models.episode import Episode

    names: set[str] = set()

    # Distinct guests across the show's episodes.
    guest_rows = (
        await session.execute(
            select(func.jsonb_array_elements_text(Episode.guests)).where(
                Episode.show_id == show_id,
                Episode.guests.isnot(None),
            )
        )
    ).scalars().all()
    for g in guest_rows:
        if g and g.strip():
            names.add(g.strip())

    # Approved correction-rule correct-forms (global ∪ this show).
    dict_rows = (
        await session.execute(
            select(AsrCorrectionTerm.correct).where(
                AsrCorrectionTerm.status == "approved",
                or_(
                    AsrCorrectionTerm.scope == "global",
                    and_(
                        AsrCorrectionTerm.scope == "show",
                        AsrCorrectionTerm.show_id == show_id,
                    ),
                ),
            )
        )
    ).scalars().all()
    for c in dict_rows:
        if c and c.strip():
            names.add(c.strip())

    for x in extra or []:
        if x and x.strip():
            names.add(x.strip())

    return sorted(names, key=lambda s: (-len(s), s))

# Rough dry-run cost heuristic (label it an estimate to the operator; the
# provider bill is the source of truth). Chinese: ~1 char ≈ 1 token. The system
# prompt + JSON overhead per call is small relative to a full episode, folded in
# as a flat per-episode token surcharge. Output is short (a pair list), so the
# estimate is dominated by input.
_EST_TOKENS_PER_CHAR = 1.0
_EST_PROMPT_OVERHEAD_TOKENS = 600
# Default per-1M-token price for the estimate when the step model is unknown.
# gpt-4o-mini class input pricing (~$0.15/1M) as a conservative default.
_EST_USD_PER_1M_TOKENS = 0.15


@dataclass
class DetectionCostEstimate:
    """Dry-run estimate for running homophone detection over a set of episodes.

    Rough by design — label it an estimate to the operator; the provider bill is
    the source of truth. No LLM call, no DB write, no transcript change is made
    to produce it.
    """

    episode_count: int = 0
    total_chars: int = 0
    estimated_input_tokens: int = 0
    estimated_cost_usd: float = 0.0
    # episode_ids that had no transcript text (skipped from the estimate)
    missing_transcript_ids: list[str] = field(default_factory=list)


async def estimate_detection_cost(
    session: "AsyncSession",
    episode_ids: list[UUID],
    *,
    usd_per_1m_tokens: float = _EST_USD_PER_1M_TOKENS,
) -> DetectionCostEstimate:
    """Estimate the token usage + cost of running detection over the given
    episodes WITHOUT invoking the LLM, writing candidates, or touching any
    transcript.

    Detection sends one call per episode whose input is the full transcript
    text plus the system prompt. The estimate = sum over episodes of
    (transcript_chars * tokens_per_char + per-episode prompt overhead).
    """
    from app.models.transcript import Transcript

    report = DetectionCostEstimate()
    for ep_id in episode_ids:
        content = (
            await session.execute(
                select(Transcript.content).where(Transcript.episode_id == ep_id)
            )
        ).scalar_one_or_none()
        if not content:
            report.missing_transcript_ids.append(str(ep_id))
            continue
        report.episode_count += 1
        report.total_chars += len(content)
        report.estimated_input_tokens += (
            int(len(content) * _EST_TOKENS_PER_CHAR) + _EST_PROMPT_OVERHEAD_TOKENS
        )

    report.estimated_cost_usd = round(
        report.estimated_input_tokens / 1_000_000 * usd_per_1m_tokens, 6
    )
    return report


def _strip_code_block(content: str) -> str:
    """Strip a leading/trailing markdown code fence from an LLM JSON payload.

    AI Hub gpt-4o ignores response_format=json_object and still wraps the JSON
    in ```json ... ``` (see memory: aihub_response_format_ignored), so we peel
    the fence before json.loads. A plain (unfenced) payload passes through
    unchanged.
    """
    text = content.strip()
    if not text.startswith("```"):
        return text
    # Drop the opening fence line (``` or ```json) and the closing fence.
    text = re.sub(r"^```[a-zA-Z0-9_-]*\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()


def _parse_pairs(content: str) -> list[CorrectionRule]:
    """Parse an LLM response into word-level CorrectionRule pairs.

    Accepts either a bare JSON array ``[{"wrong","correct"}]`` (the requested
    shape) or an object wrapping it under a ``pairs``/``corrections`` key (some
    models / json_object mode return an object). Invalid entries are skipped;
    a no-op pair (``wrong == correct`` or empty ``wrong``) is dropped so it can
    never become a meaningless rule.
    """
    raw = _strip_code_block(content)
    if not raw:
        return []
    data: Any = json.loads(raw)
    if isinstance(data, dict):
        for key in ("pairs", "corrections", "result", "data"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            return []
    if not isinstance(data, list):
        return []

    pairs: list[CorrectionRule] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        wrong = item.get("wrong")
        correct = item.get("correct")
        if not isinstance(wrong, str) or not isinstance(correct, str):
            continue
        wrong = wrong.strip()
        correct = correct.strip()
        if not wrong or wrong == correct:
            continue
        pairs.append(CorrectionRule(wrong=wrong, correct=correct))
    return pairs


def _call_llm(client: OpenAI, *, model: str, prompt: str, transcript_text: str) -> str:
    """Single chat completion returning the raw message content.

    Isolated so tests can monkeypatch a fake LLM and so the fail-open wrapper
    in `detect_homophones` has one well-defined failure surface.
    """
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": transcript_text},
        ],
        temperature=0.0,
        response_format={"type": "json_object"},
    )
    return (resp.choices[0].message.content or "") if resp.choices else ""


async def detect_homophones(
    session: "AsyncSession",
    transcript_text: str,
    *,
    show_id: UUID | None = None,
    candidate_entities: list[str] | None = None,
    client: OpenAI | None = None,
    model: str | None = None,
    instruction: str | None = None,
) -> list[CorrectionRule]:
    """Detect ASR mis-hearings of the show's known proper nouns (RAGEC).

    Grounds the LLM with a candidate-entity list (built from `show_id` unless
    `candidate_entities` is passed) and asks it to map mis-heard tokens back onto
    that list — far more reliable than open-ended typo hunting (EQ2b pilot).

    Returns word-level `{wrong, correct}` pairs (as `CorrectionRule`s) suitable
    for `apply_corrections`. NEVER raises — fail-open per D6: any failure (step
    not configured, no candidates, LLM error, malformed JSON) logs a warning and
    returns ``[]`` so transcription falls back to dictionary-only correction.

    `client`/`model`/`instruction` are injectable for tests and model A/B runs;
    when omitted they resolve from the `asr_homophone` AI step.
    """
    if not transcript_text or not transcript_text.strip():
        return []
    try:
        if candidate_entities is None:
            if show_id is None:
                raise ValueError("detect_homophones needs show_id or candidate_entities")
            candidate_entities = await load_candidate_entities(session, show_id)
        if not candidate_entities:
            # No known entities to ground on → nothing to map; skip the LLM call.
            logger.info("asr_homophone: no candidate entities for show; skipping")
            return []

        if client is None or model is None:
            cfg = await get_step_config(session, ASR_HOMOPHONE_STEP_KEY)
            if client is None:
                client = OpenAI(base_url=cfg.base_url, api_key=cfg.api_key)
            if model is None:
                model = cfg.model
            if instruction is None:
                instruction = cfg.extra_config.get("prompt") or None

        prompt = build_detection_prompt(candidate_entities, instruction)
        # Run the blocking sync OpenAI call in a thread so it doesn't stall the
        # worker's event loop (consistent with topic_segmentation).
        raw = await asyncio.to_thread(
            _call_llm,
            client,
            model=model,
            prompt=prompt,
            transcript_text=transcript_text,
        )
        pairs = _parse_pairs(raw)
        # Safety net: keep only pairs whose correct-form is actually in the
        # candidate list and that genuinely appear in the transcript. This caps
        # any residual model over-reach to the grounded vocabulary.
        allowed = set(candidate_entities)
        filtered = [
            p
            for p in pairs
            if p.correct in allowed and p.wrong in transcript_text
        ]
        dropped = len(pairs) - len(filtered)
        logger.info(
            "asr_homophone: detected %d pair(s) (%d dropped: off-list or absent)",
            len(filtered),
            dropped,
        )
        return filtered
    except Exception:
        logger.warning(
            "asr_homophone: detection failed; falling back to dictionary-only "
            "correction (fail-open)",
            exc_info=True,
        )
        return []


async def persist_candidates(
    session: "AsyncSession",
    pairs: list[CorrectionRule],
    *,
    show_id: UUID,
) -> int:
    """Persist detected pairs as pending, disabled, show-scoped LLM candidates.

    Each pair is written `source='llm'`, `status='pending'`, `enabled=false`,
    `scope='show'` bound to `show_id`. Before inserting, a `(wrong, scope=show,
    show_id)` collision with an EXISTING rule of ANY status is skipped — the
    existing row's status is never overwritten (D4), so a previously rejected
    candidate is not resurrected and an approved rule is not demoted. Returns
    the number of NEW candidates inserted.

    Commits once at the end. The current-episode correction (D2) is applied
    separately and does not depend on this persistence succeeding.
    """
    if not pairs:
        return 0

    # Resolve existing wrongs for this show in one query (dedup is per-show).
    existing = set(
        (
            await session.execute(
                select(AsrCorrectionTerm.wrong).where(
                    AsrCorrectionTerm.scope == "show",
                    AsrCorrectionTerm.show_id == show_id,
                )
            )
        )
        .scalars()
        .all()
    )

    inserted = 0
    seen_this_batch: set[str] = set()
    for pair in pairs:
        if pair.wrong in existing or pair.wrong in seen_this_batch:
            continue
        seen_this_batch.add(pair.wrong)
        session.add(
            AsrCorrectionTerm(
                wrong=pair.wrong,
                correct=pair.correct,
                scope="show",
                show_id=show_id,
                enabled=False,
                source="llm",
                status="pending",
            )
        )
        inserted += 1

    if inserted:
        await session.commit()
    logger.info(
        "asr_homophone: persisted %d new candidate(s) for show %s (%d skipped as "
        "duplicates)",
        inserted,
        show_id,
        len(pairs) - inserted,
    )
    return inserted
