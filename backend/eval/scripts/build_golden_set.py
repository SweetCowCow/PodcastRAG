"""Anchor-first golden-set generation for a show (eval-loop-automation, D2).

Workflow (one question at a time, anchor BEFORE question):
1. Load the show profile (`show_profile.py` output) — quotas drive how many
   questions of each type to generate.
2. For each question: stratified-sample episode(s) (duration × publish time),
   sample anchor chunk(s) from them (cross_episode: embedding-neighbor group
   across ≥2 episodes), THEN ask the LLM to generate a question answerable
   from exactly those chunks, and bind those chunk ids as ground truth.
3. Write v2-schema items to a STAGING file for graded human review.

The old flow (LLM generates from show impressions → anchors attached
afterwards) produced ≥75% bad questions (2026-05-13 audit) — anchor
misalignment is structurally impossible when the anchor exists first.

STAGING DISCIPLINE (since r3-5-disable-routing audit, 2026-05-13):
Output SHALL be written to `backend/eval/datasets/_pending_review.json` by
default. To write directly to the main per-show dataset, all three of
`--target-main`, `--reviewed-by <id>`, and `--reviewed-at <ISO8601>` MUST
be supplied; absent any one of them the script exits with code 2.

Multi-turn items (`multi_turn_handcraft` quota) are NOT auto-generated —
they are co-drafted by a human; see
.claude/skills/golden-set-builder/SKILL.md for the full workflow.

Usage (staging, default):
    DATABASE_URL=postgresql://... python -m backend.eval.scripts.build_golden_set \
        --profile backend/eval/datasets/profiles/yi-jia-yi.json

Usage (write to main, requires review metadata):
    python -m backend.eval.scripts.build_golden_set \
        --profile backend/eval/datasets/profiles/yi-jia-yi.json \
        --target-main --reviewed-by jacky --reviewed-at 2026-07-03T10:00:00Z
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from dotenv import load_dotenv

from .show_profile import load_profile

REPO_ROOT = Path(__file__).resolve().parents[3]
DATASETS_DIR = REPO_ROOT / "backend" / "eval" / "datasets"

HUB_BASE_URL = "https://hnd1.aihub.zeabur.ai/v1"
# Generation model. Design said "reuse the summary-step config", but prod's
# summary step is now gemini-2.5-flash-lite — the SAME model as the pre-review
# judge, which would violate the "verifier ≠ generator" spec requirement.
# gpt-5.1 (prod answer-step model) is used instead; --model overrides.
DEFAULT_GEN_MODEL = "gpt-5.1"

# Question types that are auto-generated. multi_turn_handcraft is excluded:
# the profile quota only tells the human co-drafting pass how many to add.
AUTO_TYPES = (
    "fact",
    "deep_dive",
    "cross_episode",
    "summary_overview",
    "date_find",
    "negative",
    "code_switch",
    "guest_find",
    "playlist_enum",
)
HANDCRAFT_TYPES = ("multi_turn_handcraft",)

# Types whose single sampled chunk IS the must-tier GT (no LLM tiering).
SINGLE_CHUNK_TYPES = ("fact", "deep_dive", "code_switch", "date_find")
# Types anchored to a whole episode: chunks land in acceptable tier, the
# episode uuid is the must-level expectation.
EPISODE_SCOPED_TYPES = ("summary_overview", "guest_find", "playlist_enum")

MIN_ANCHOR_CHARS = 80  # skip tiny chunks as anchors


# ────────────────────────────────────────────────────────────────────
# Prompts (show-agnostic — zero per-show hardcode, D1 goal)
# ────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """你是 RAG 評測題庫的出題助手。你會拿到 podcast 逐字稿的「錨點片段」，任務是產生一個模擬真實聽眾提問的中文問題，且該問題必須「僅憑錨點片段的內容」就能完整回答。

【硬性品質要求】
1. 先自我驗證：只讀錨點片段，能否完整答出你出的題？不能就換一題。
2. 問題必須包含至少一個具體 entity（人名 / 歌名 / 事件 / 地名 / 數字 / 品牌 / 專輯名）。
3. 嚴禁「有提到 XX 嗎」「有討論 XX 嗎」這種空泛 yes/no 模板；問「誰／什麼／哪裡／為什麼／多少」。
4. 問題裡不能出現「這段」「該片段」「逐字稿」— 提問的聽眾沒看過逐字稿。
5. expected_answer_summary 用 1-3 句中文寫出正確答案的要點（給 LLM 判官比對用，不是關鍵字列表）。

回答僅以 JSON object 格式，不要有任何前後綴文字。"""

_TYPE_RULES: dict[str, str] = {
    "fact": (
        "答案必須是錨點片段裡可以直接讀到的具體事實（人物、時間、地點、數字、引用）。"
        "問「誰／什麼／何時／哪裡／多少」，不是 yes/no。"
    ),
    "deep_dive": (
        "需要從錨點片段歸納或解釋「動機/觀點/比喻/理由」，而非單純複述事實。"
        "嚴禁問句裡用『可能/是否/或許/也許』這類含糊詞 — 答案要有清楚立場。"
        "禁止只是把事實題加上問號。"
    ),
    "cross_episode": (
        "你會拿到來自不同集數的多個錨點片段。題目必須「綜合至少兩集的內容」才能回答 — "
        "問貫穿多集的人物、習慣、概念的對照或演變。"
        "在 must_chunk_ids 裡列出回答「必要」的片段 id（至少來自 2 個不同集數）；"
        "其餘片段視為佐證。若這些片段其實講不同主題、湊不出合理的跨集題，"
        "回傳 {\"skip\": true, \"reason\": \"...\"}。"
    ),
    "summary_overview": (
        "題目問「這一集主要在聊什麼 / 這集的重點是什麼」這類集數總覽題。"
        "問題必須包含集數標題或標題中的具體元素，讓人知道在問哪一集。"
        "expected_answer_summary 概括該集 2-4 個重點。"
    ),
    "date_find": (
        "題目問「哪一集 / 什麼時候聊到 X」— X 是錨點片段中的具體事件或主題。"
        "expected_answer_summary 要包含集數標題與發布日期。"
    ),
    "negative": (
        "根據提供的節目近期集數標題，問一個「節目鄰近領域、但清單裡看不出有講過」的具體問題。"
        "禁用『量子力學/區塊鏈/太空探索』這種明顯不相干的陳腔濫調 — 要像真實聽眾會誤以為節目聊過的題目。"
    ),
    "code_switch": (
        "問題必須中英夾雜：至少包含 1 個英文詞（樂風名 / 術語 / 人名 / 平台名 / 品牌），"
        "且該英文詞要跟錨點片段的內容相關。答案必須能從錨點片段讀出。"
    ),
    "guest_find": (
        "錨點片段來自某位來賓上節目的那一集。題目圍繞該來賓 — "
        "「XX 來上節目時聊了什麼 / 分享了什麼觀點 / 哪一集邀請了 XX」。"
        "問題必須點名來賓名字。"
    ),
    "playlist_enum": (
        "這是一集歌單特化集。題目問該集歌單的內容 — 放了哪些歌 / 誰的歌 / 幾首歌。"
        "若 description 有明確曲目清單，expected_count 填曲目數；否則填 null。"
        "問題必須包含集數標題或歌單主題，讓人知道在問哪一份歌單。"
    ),
}

_OUTPUT_SPEC_COMMON = (
    "輸出 JSON object，包含：question（字串）、expected_answer_summary（字串）、"
    "expected_answer_aliases（object，key 是答案中的專有名詞、value 是別名陣列；沒有就 null）"
)
_OUTPUT_SPEC_EXTRA: dict[str, str] = {
    "cross_episode": "、must_chunk_ids（字串陣列，從提供的片段 id 中挑）",
    "playlist_enum": "、expected_count（整數或 null）",
}


def _show_facts_block(show_facts: dict | None) -> str:
    """Render profile show_facts (hosts/aliases, human-confirmed) for the prompt."""
    if not show_facts:
        return ""
    lines = []
    for h in show_facts.get("hosts", []):
        alias = f"（{'、'.join(h['aliases'])}）" if h.get("aliases") else ""
        note = f" — {h['note']}" if h.get("note") else ""
        lines.append(f"- {h['name']}{alias}{note}")
    block = "【節目主持人 — 出題時用這些自然稱呼，不要用「主持人/講者」這種生硬稱謂；"
    block += "無法從片段確定是誰說的就用「他們/他/她」】\n" + "\n".join(lines)
    if show_facts.get("notes"):
        block += f"\n【注意】{show_facts['notes']}"
    return block


def build_generation_prompt(
    qtype: str,
    anchor_group: dict,
    negative_fewshot: str = "",
    show_facts: dict | None = None,
) -> str:
    """Assemble the user prompt for one question from its pre-sampled anchors."""
    parts = [f"題型：{qtype}", "", f"【本題型規則】\n{_TYPE_RULES[qtype]}"]
    facts_block = _show_facts_block(show_facts)
    if facts_block:
        parts.append(f"\n{facts_block}")
    if negative_fewshot:
        parts.append(f"\n【前輪被人審打槍的反面教材 — 不要再犯】\n{negative_fewshot}")

    if qtype == "negative":
        titles = "\n".join(f"- {t}" for t in anchor_group["episode_titles"])
        parts.append(f"\n【節目】{anchor_group['show_title']}")
        parts.append(f"【近期集數標題】\n{titles}")
    else:
        ep_lines = []
        for ch in anchor_group["chunks"]:
            ep_lines.append(
                f"[{ch['chunk_id']}]（{ch['episode_title']}"
                + (f"，發布於 {ch['published_at']:%Y-%m-%d}" if ch.get("published_at") else "")
                + f"）\n{ch['text']}"
            )
        parts.append("\n【錨點片段】\n" + "\n\n".join(ep_lines))
        if qtype == "summary_overview" and anchor_group.get("ai_summary"):
            parts.append(f"\n【該集 AI 摘要（輔助脈絡）】\n{anchor_group['ai_summary']}")
        if qtype == "guest_find":
            parts.append(f"\n【本集來賓】{anchor_group['guest']}")
        if qtype == "playlist_enum" and anchor_group.get("description"):
            parts.append(f"\n【該集 description】\n{anchor_group['description'][:2000]}")

    parts.append(
        "\n" + _OUTPUT_SPEC_COMMON + _OUTPUT_SPEC_EXTRA.get(qtype, "") + "。"
    )
    return "\n".join(parts)


# ────────────────────────────────────────────────────────────────────
# Validation (mechanical)
# ────────────────────────────────────────────────────────────────────

_BAD_TEMPLATES = (
    "有提到", "有討論", "是否提到過", "是否有提到", "是否有討論",
    "是否多次", "是否曾", "可能", "或許", "也許",
)
_META_LEAK = ("這段", "該片段", "逐字稿", "錨點")


def validate_candidate(
    cand: dict,
    qtype: str,
    anchor_ids: set[str],
    banned_topics: list[str] | None = None,
) -> tuple[bool, str]:
    """Return (ok, reason). Reason is empty if ok."""
    q = cand.get("question", "")
    if not q or len(q) > 500:
        return False, "empty or too long"
    if any(t in q for t in _BAD_TEMPLATES):
        return False, "uses banned yes/no template"
    if any(t in q for t in _META_LEAK):
        return False, "question leaks meta reference (這段/片段/逐字稿)"
    if not cand.get("expected_answer_summary"):
        return False, "missing expected_answer_summary"
    for topic in banned_topics or []:
        if topic and topic in q:
            return False, f"hits banned topic: {topic}"

    if qtype == "code_switch" and not re.search(r"[A-Za-z]", q):
        return False, "code-switch question must contain English"

    if qtype == "cross_episode":
        must = cand.get("must_chunk_ids") or []
        if not must:
            return False, "cross_episode must select must_chunk_ids"
        bad = [c for c in must if c not in anchor_ids]
        if bad:
            return False, f"must_chunk_ids outside sampled anchors: {bad[0]}"
        eps = {c.split("@")[0] for c in must}
        if len(eps) < 2:
            return False, f"cross_episode must span ≥2 episodes, got {len(eps)}"

    return True, ""


# ────────────────────────────────────────────────────────────────────
# Data access (direct SQL, same pattern as show_profile.py)
# ────────────────────────────────────────────────────────────────────

def _chunk_gt_id(episode_id: str, start_time: float) -> str:
    """Canonical GT chunk id (matches chunk_recall_grouped grader)."""
    return f"ep:{episode_id}@{start_time:.2f}"


async def fetch_show_data(conn, show_id: str) -> dict:
    from sqlalchemy import text

    show_title = (
        await conn.execute(
            text("SELECT title FROM shows WHERE id = :sid"), {"sid": show_id}
        )
    ).scalar_one()
    rows = (
        await conn.execute(
            text(
                """
                SELECT e.id::text AS id, e.title, e.duration_seconds, e.published_at,
                       e.guests, e.description, e.ai_summary, e.ai_summary_status,
                       t.id AS transcript_id
                FROM episodes e
                JOIN transcripts t ON t.episode_id = e.id AND t.status = 'completed'
                WHERE e.show_id = :sid
                """
            ),
            {"sid": show_id},
        )
    ).mappings().all()
    episodes = [dict(r) for r in rows]
    for ep in episodes:
        if isinstance(ep["guests"], str):
            ep["guests"] = json.loads(ep["guests"])
    return {"show_id": show_id, "show_title": show_title, "episodes": episodes}


async def fetch_chunks(conn, episode: dict) -> list[dict]:
    from sqlalchemy import text

    rows = (
        await conn.execute(
            text(
                """
                SELECT id::text AS db_id, start_time, text AS chunk_text
                FROM transcript_chunks
                WHERE transcript_id = :tid
                ORDER BY chunk_index
                """
            ),
            {"tid": episode["transcript_id"]},
        )
    ).mappings().all()
    return [
        {
            "db_id": r["db_id"],
            "chunk_id": _chunk_gt_id(episode["id"], r["start_time"]),
            "text": r["chunk_text"],
            "episode_id": episode["id"],
            "episode_title": episode["title"],
            "published_at": episode["published_at"],
        }
        for r in rows
    ]


async def fetch_neighbor_chunks(
    conn, show_id: str, seed: dict, k: int = 2
) -> list[dict]:
    """Embedding-nearest chunks from OTHER episodes of the same show."""
    from sqlalchemy import text

    rows = (
        await conn.execute(
            text(
                """
                SELECT c.id::text AS db_id, c.start_time, c.text AS chunk_text,
                       e.id::text AS episode_id, e.title AS episode_title, e.published_at
                FROM transcript_chunks c
                JOIN transcripts t ON c.transcript_id = t.id
                JOIN episodes e ON t.episode_id = e.id
                WHERE e.show_id = :sid
                  AND e.id != :seed_ep
                  AND c.embedding_v2 IS NOT NULL
                ORDER BY c.embedding_v2 <=> (
                    SELECT embedding_v2 FROM transcript_chunks WHERE id = :seed_id
                )
                LIMIT :k
                """
            ),
            {"sid": show_id, "seed_ep": seed["episode_id"], "seed_id": seed["db_id"], "k": k},
        )
    ).mappings().all()
    return [
        {
            "db_id": r["db_id"],
            "chunk_id": _chunk_gt_id(r["episode_id"], r["start_time"]),
            "text": r["chunk_text"],
            "episode_id": r["episode_id"],
            "episode_title": r["episode_title"],
            "published_at": r["published_at"],
        }
        for r in rows
    ]


# ────────────────────────────────────────────────────────────────────
# Sampling (anchor first — the whole point)
# ────────────────────────────────────────────────────────────────────

def stratified_episode_cycle(episodes: list[dict], rng: random.Random):
    """Yield episodes round-robin from duration × publish-time strata (D2)."""
    with_meta = [e for e in episodes if e["duration_seconds"] and e["published_at"]]
    pool = with_meta if len(with_meta) >= 4 else list(episodes)
    if not pool:
        return
    durations = sorted(e["duration_seconds"] or 0 for e in pool)
    times = sorted(e["published_at"] for e in pool if e["published_at"])
    d_med = durations[len(durations) // 2]
    t_med = times[len(times) // 2] if times else None

    strata: list[list[dict]] = [[], [], [], []]
    for e in pool:
        long_ = (e["duration_seconds"] or 0) >= d_med
        new_ = bool(t_med and e["published_at"] and e["published_at"] >= t_med)
        strata[long_ * 2 + new_].append(e)
    for s in strata:
        rng.shuffle(s)
    idx = [0, 0, 0, 0]
    while True:
        progressed = False
        for i, s in enumerate(strata):
            if idx[i] < len(s):
                progressed = True
                yield s[idx[i]]
                idx[i] += 1
        if not progressed:  # all strata exhausted → recycle
            idx = [0, 0, 0, 0]
            if not any(strata):
                return


def pick_anchor_chunk(chunks: list[dict], rng: random.Random, want_english: bool = False) -> dict | None:
    usable = [c for c in chunks if len(c["text"]) >= MIN_ANCHOR_CHARS]
    if want_english:
        en = [c for c in usable if re.search(r"[A-Za-z]{3,}", c["text"])]
        usable = en or usable
    return rng.choice(usable) if usable else None


async def sample_anchor_group(
    conn, qtype: str, show: dict, ep_cycle, rng: random.Random
) -> dict | None:
    """Sample the anchors for ONE question of qtype. None = nothing suitable."""
    episodes = show["episodes"]

    if qtype == "negative":
        titles = [e["title"] for e in rng.sample(episodes, min(10, len(episodes)))]
        return {"show_title": show["show_title"], "episode_titles": titles, "chunks": []}

    if qtype == "summary_overview":
        done = [e for e in episodes if e["ai_summary_status"] == "done" and e["ai_summary"]]
        if not done:
            return None
        ep = rng.choice(done)
        chunks = await fetch_chunks(conn, ep)
        if len(chunks) < 3:
            return None
        picks = [chunks[int(len(chunks) * p)] for p in (0.1, 0.5, 0.9)]
        return {"chunks": picks, "episode": ep, "ai_summary": ep["ai_summary"]}

    if qtype == "guest_find":
        with_guests = [e for e in episodes if e["guests"]]
        if not with_guests:
            return None
        ep = rng.choice(with_guests)
        guest = rng.choice(ep["guests"])
        chunks = await fetch_chunks(conn, ep)
        mentions = [c for c in chunks if guest in c["text"]][:3]
        picks = mentions or ([c for c in chunks if len(c["text"]) >= MIN_ANCHOR_CHARS][:2])
        if not picks:
            return None
        return {"chunks": picks, "episode": ep, "guest": guest}

    if qtype == "playlist_enum":
        playlist_eps = [e for e in episodes if "歌單" in e["title"]]
        if not playlist_eps:
            return None
        ep = rng.choice(playlist_eps)
        chunks = await fetch_chunks(conn, ep)
        usable = [c for c in chunks if len(c["text"]) >= MIN_ANCHOR_CHARS]
        if not usable:
            return None
        picks = rng.sample(usable, min(3, len(usable)))
        return {"chunks": picks, "episode": ep, "description": ep["description"] or ""}

    if qtype == "cross_episode":
        for _ in range(5):  # retry seeds until neighbors land in another episode
            ep = next(ep_cycle, None)
            if ep is None:
                return None
            chunks = await fetch_chunks(conn, ep)
            seed = pick_anchor_chunk(chunks, rng)
            if seed is None:
                continue
            neighbors = await fetch_neighbor_chunks(conn, show["show_id"], seed, k=2)
            if neighbors:
                return {"chunks": [seed] + neighbors, "episode": ep}
        return None

    # fact / deep_dive / code_switch / date_find — single-chunk anchor
    for _ in range(5):
        ep = next(ep_cycle, None)
        if ep is None:
            return None
        if qtype == "date_find" and not ep["published_at"]:
            continue
        chunks = await fetch_chunks(conn, ep)
        pick = pick_anchor_chunk(chunks, rng, want_english=(qtype == "code_switch"))
        if pick is not None:
            return {"chunks": [pick], "episode": ep}
    return None


# ────────────────────────────────────────────────────────────────────
# LLM call (AI Hub)
# ────────────────────────────────────────────────────────────────────

def call_llm(
    model: str,
    user_prompt: str,
    system_prompt: str = SYSTEM_PROMPT,
    temperature: float = 0.8,
) -> dict:
    """One LLM call → parsed JSON object."""
    from openai import OpenAI

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"], base_url=HUB_BASE_URL)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        max_tokens=2048,
    )
    raw = (response.choices[0].message.content or "").strip()
    if not raw:
        raise ValueError(f"empty content (finish={response.choices[0].finish_reason})")
    # some hub models wrap JSON in ```json fences regardless of instructions
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError(f"LLM did not return an object: {raw[:200]}")
    return parsed


# ────────────────────────────────────────────────────────────────────
# Pre-review grading (D3) — four checks, retrieval signal grades but
# never rejects; show-id guard is the ONLY automatic rejection.
# ────────────────────────────────────────────────────────────────────

# Judge model MUST differ from the generation model (anti-self-endorsement,
# spec: golden-set-pipeline). Enforced at startup.
DEFAULT_JUDGE_MODEL = "gemini-2.5-flash-lite"
RETRIEVAL_LIGHT_RANK = 20  # anchor found at rank ≤ this → light-grade signal
CHUNK_MATCH_WINDOW_S = 10.0  # same convention as chunk_recall_grouped grader

JUDGE_SYSTEM_PROMPT = """你是 RAG 評測題庫的預審判官。只根據提供的錨點片段內容，回答兩個判斷：

1. anchor_aligned：只讀這些片段，能否完整回答這個問題並得出附上的預期答案？
   注意「只共享關鍵字但語意不對齊」要判 false。
2. must_ok：answerability rubric — 標為 must 的片段是否符合「缺了就答錯」？
   acceptable 片段是佐證，缺了不影響答對。若本題沒有 must 片段（episode 總覽類），
   則判斷 acceptable 片段組是否足以支撐預期答案。
3. note：一句話說明主要疑慮，沒有疑慮就給空字串。

回答僅以 JSON object 格式：{"anchor_aligned": bool, "must_ok": bool, "note": str}"""


def judge_item(judge_model: str, item: dict) -> dict:
    """LLM checks 1+2 (anchor alignment + answerability rubric) in one call."""
    anchors = item.get("anchor_context") or []
    must = set(item.get("ground_truth_chunk_ids_must") or [])
    lines = []
    for a in anchors:
        tier = "must" if a["chunk_id"] in must else "acceptable"
        lines.append(f"[{tier}] [{a['chunk_id']}]（{a['episode_title']}）\n{a['text']}")
    prompt = (
        f"【問題】{item['question']}\n\n"
        f"【預期答案】{item.get('expected_answer_summary', '')}\n\n"
        f"【錨點片段】\n" + "\n\n".join(lines)
    )
    verdict = call_llm(judge_model, prompt, system_prompt=JUDGE_SYSTEM_PROMPT, temperature=0.0)
    return {
        "anchor_aligned": bool(verdict.get("anchor_aligned")),
        "must_ok": bool(verdict.get("must_ok")),
        "note": str(verdict.get("note", "")),
    }


def _search_hits(backend_url: str, show_id: str, question: str, auth_token: str, k: int) -> list[dict]:
    import urllib.request

    headers = {"Content-Type": "application/json"}
    if auth_token:
        headers["Cookie"] = f"session_id={auth_token}"
    req = urllib.request.Request(
        f"{backend_url}/shows/{show_id}/search",
        data=json.dumps({"question": question, "k": k}).encode(),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())["results"]


def retrieval_rank(
    backend_url: str, show_id: str, item: dict, auth_token: str, k: int = RETRIEVAL_LIGHT_RANK
) -> int | None:
    """1-based rank of the first hit matching any GT anchor (10s window), or None."""
    targets = (
        item.get("ground_truth_chunk_ids_must")
        or item.get("ground_truth_chunk_ids_acceptable")
        or []
    )
    parsed = []
    for gt in targets:
        m = re.match(r"^ep:([0-9a-f-]+)@(\d+\.?\d*)$", gt)
        if m:
            parsed.append((m.group(1), float(m.group(2))))
    if not parsed:
        return None
    hits = _search_hits(backend_url, show_id, item["question"], auth_token, k)
    for rank, hit in enumerate(hits, start=1):
        for ep_id, start in parsed:
            if str(hit["episode_id"]) == ep_id and abs(hit["start_time"] - start) <= CHUNK_MATCH_WINDOW_S:
                return rank
    return None


def compute_review_grade(qtype: str, anchor_aligned: bool, must_ok: bool, rank: int | None) -> str:
    """light|heavy. Checks 1/2 failing forces heavy; retrieval only grades."""
    if not anchor_aligned or not must_ok:
        return "heavy"
    if qtype == "negative":
        # "真的沒講過" can't be machine-verified — always full scrutiny.
        return "heavy"
    if rank is None or rank > RETRIEVAL_LIGHT_RANK:
        return "heavy"
    return "light"


def append_review_log(log_path: Path, entry: dict) -> None:
    """Append one JSONL line (schema: ts/show_slug/item_id/verdict/reason/note/round).

    Entries MAY additionally carry `question` (the rejected question text) —
    the reject-feedback loop uses it as a concrete negative few-shot example.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _read_review_log(log_path: Path) -> list[dict]:
    if not log_path.exists():
        return []
    entries = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            entries.append(json.loads(line))
    return entries


def build_negative_fewshot(log_path: Path, show_slug: str, cap: int = 5) -> str:
    """Reject-feedback loop (D5): most frequent reject reasons + concrete
    rejected examples (≤cap, target-show examples preferred) as a negative
    few-shot block for the generation prompt. Empty string when no rejects."""
    rejects = [e for e in _read_review_log(log_path) if e.get("verdict") == "reject"]
    if not rejects:
        return ""

    reason_counts: dict[str, int] = {}
    for e in rejects:
        reason_counts[e.get("reason", "other")] = reason_counts.get(e.get("reason", "other"), 0) + 1
    ranked_reasons = sorted(reason_counts, key=reason_counts.get, reverse=True)

    # pick examples by reason frequency, same-show entries first within a reason
    picked: list[dict] = []
    for reason in ranked_reasons:
        pool = [e for e in rejects if e.get("reason") == reason]
        pool.sort(key=lambda e: e.get("show_slug") != show_slug)  # same show first
        for e in pool:
            if len(picked) >= cap:
                break
            picked.append(e)
        if len(picked) >= cap:
            break

    lines = [
        f"歷史 reject 理由分布：{', '.join(f'{r}×{reason_counts[r]}' for r in ranked_reasons)}",
    ]
    for e in picked:
        q = e.get("question")
        example = f"「{q}」" if q else f"（item {e.get('item_id')}）"
        note = f" — {e['note']}" if e.get("note") else ""
        lines.append(f"- [{e.get('reason')}] {example}{note}")
    return "\n".join(lines)


def report_round_stats(log_path: Path, show_slug: str) -> None:
    """Per-round bad-question ratio (reject / total verdicts) vs prior round."""
    entries = [e for e in _read_review_log(log_path) if e.get("show_slug") == show_slug]
    if not entries:
        print("[rounds] no review history yet for this show", file=sys.stderr)
        return
    rounds = sorted({e.get("round", 1) for e in entries})
    prev_ratio: float | None = None
    for r in rounds:
        batch = [e for e in entries if e.get("round", 1) == r]
        rejects = [e for e in batch if e.get("verdict") == "reject"]
        ratio = len(rejects) / len(batch)
        reasons: dict[str, int] = {}
        for e in rejects:
            reasons[e.get("reason", "other")] = reasons.get(e.get("reason", "other"), 0) + 1
        delta = "" if prev_ratio is None else f"（上輪 {prev_ratio:.0%} → {'↓' if ratio < prev_ratio else '↑' if ratio > prev_ratio else '='}）"
        print(
            f"[rounds] r{r}: 壞題率 {ratio:.0%} ({len(rejects)}/{len(batch)}) {delta} reasons={reasons}",
            file=sys.stderr,
        )
        prev_ratio = ratio


def run_pre_review(
    items: list[dict],
    valid_episode_ids: set[str],
    show_id: str,
    show_slug: str,
    round_no: int,
    judge_model: str,
    backend_url: str,
    auth_token: str,
    review_log_path: Path,
    skip_retrieval: bool,
) -> list[dict]:
    """Attach pre_review to every item; drop (and log) show-id-guard violations."""
    kept: list[dict] = []
    for item in items:
        qtype = item["design_type"]
        gt_ids = (item.get("ground_truth_chunk_ids_must") or []) + (
            item.get("ground_truth_chunk_ids_acceptable") or []
        )

        # Check 3 — mechanical show-id guard: the ONLY automatic rejection
        # (2026-06-05 cross-show collision lesson).
        foreign = [
            gt for gt in gt_ids
            if gt.split("@")[0].removeprefix("ep:") not in valid_episode_ids
        ]
        if foreign:
            print(f"[auto-reject] {item['id']}: foreign-show anchor {foreign[0]}", file=sys.stderr)
            append_review_log(
                review_log_path,
                {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "show_slug": show_slug,
                    "item_id": item["id"],
                    "verdict": "reject",
                    "reason": "show_id_guard",
                    "note": f"auto: anchor outside target show: {foreign[0]}",
                    "round": round_no,
                },
            )
            continue

        # Checks 1+2 — LLM judge (vacuous for negative: no anchors to judge).
        if qtype == "negative" or not item.get("anchor_context"):
            judged = {"anchor_aligned": True, "must_ok": True, "note": "negative/no-anchor: vacuous"}
        else:
            try:
                judged = judge_item(judge_model, item)
            except Exception as exc:  # noqa: BLE001
                print(f"[warn] judge failed for {item['id']}: {exc} — forcing heavy", file=sys.stderr)
                judged = {"anchor_aligned": False, "must_ok": False, "note": f"judge error: {exc}"}

        # Check 4 — retrieval signal (grades, never rejects; b20 lesson:
        # anchors retrieval can't find are exactly where the ruler has value).
        rank: int | None = None
        if not skip_retrieval and qtype != "negative" and gt_ids:
            try:
                rank = retrieval_rank(backend_url, show_id, item, auth_token)
            except Exception as exc:  # noqa: BLE001
                print(f"[warn] search failed for {item['id']}: {exc} — rank=None", file=sys.stderr)

        item["pre_review"] = {
            "anchor_aligned": judged["anchor_aligned"],
            "answerability": {"must_ok": judged["must_ok"], "note": judged["note"]},
            "show_id_ok": True,
            "retrieval_rank": rank,
            "review_grade": compute_review_grade(
                qtype, judged["anchor_aligned"], judged["must_ok"], rank
            ),
        }
        kept.append(item)

    grades = [i["pre_review"]["review_grade"] for i in kept]
    print(
        f"[pre-review] {len(kept)} kept ({grades.count('light')} light / "
        f"{grades.count('heavy')} heavy), {len(items) - len(kept)} auto-rejected",
        file=sys.stderr,
    )
    return kept


# ────────────────────────────────────────────────────────────────────
# Item assembly (v2 schema)
# ────────────────────────────────────────────────────────────────────

def assemble_item(
    qtype: str,
    cand: dict,
    anchor_group: dict,
    slug: str,
    round_no: int,
    seq: int,
) -> dict:
    slug_short = slug.replace("-", "")[:6]
    anchor_ids = [c["chunk_id"] for c in anchor_group["chunks"]]

    item: dict[str, Any] = {
        "id": f"{slug_short}-r{round_no}-{qtype}-{seq:02d}",
        "design_type": qtype,
        "source": f"auto-anchor-first-r{round_no}",
        "is_multi_turn": False,
        "question": cand["question"],
        "expected_behavior": "refuse" if qtype == "negative" else "answer",
        "expected_answer_summary": cand.get("expected_answer_summary", ""),
        "expected_answer_aliases": cand.get("expected_answer_aliases") or None,
        "ground_truth_chunk_ids_must": None,
        "ground_truth_chunk_ids_either": None,
        "ground_truth_chunk_ids_acceptable": None,
        "expected_episode_uuids_must": None,
        "audit_status": "pending",
        "generation_round": round_no,
    }

    if qtype == "negative":
        pass  # GT stays null across the board
    elif qtype in SINGLE_CHUNK_TYPES:
        item["ground_truth_chunk_ids_must"] = anchor_ids
        if qtype == "date_find":
            item["expected_episode_uuids_must"] = [anchor_group["episode"]["id"]]
    elif qtype in EPISODE_SCOPED_TYPES:
        item["ground_truth_chunk_ids_acceptable"] = anchor_ids
        item["expected_episode_uuids_must"] = [anchor_group["episode"]["id"]]
        if qtype == "playlist_enum":
            item["expected_count"] = cand.get("expected_count")
    elif qtype == "cross_episode":
        must = list(cand["must_chunk_ids"])
        item["ground_truth_chunk_ids_must"] = must
        acceptable = [c for c in anchor_ids if c not in must]
        item["ground_truth_chunk_ids_acceptable"] = acceptable or None

    if anchor_group["chunks"]:
        item["source_episode_id"] = anchor_group["chunks"][0]["episode_id"]
        # carried in staging so human review can show anchor text without a DB
        # round-trip; stripped when writing to the main dataset.
        item["anchor_context"] = [
            {
                "chunk_id": c["chunk_id"],
                "episode_title": c["episode_title"],
                "text": c["text"],
            }
            for c in anchor_group["chunks"]
        ]
    return item


# ────────────────────────────────────────────────────────────────────
# Generation loop
# ────────────────────────────────────────────────────────────────────

async def generate_all(
    database_url: str,
    profile: dict,
    model: str,
    round_no: int,
    banned_topics: list[str],
    negative_fewshot: str,
    max_attempts_factor: int = 3,
    seed: int | None = None,
) -> tuple[list[dict], set[str]]:
    from sqlalchemy.ext.asyncio import create_async_engine

    rng = random.Random(seed)
    engine = create_async_engine(database_url)
    items: list[dict] = []
    valid_episode_ids: set[str] = set()
    try:
        async with engine.connect() as conn:
            show = await fetch_show_data(conn, profile["show_id"])
            if not show["episodes"]:
                raise SystemExit("[fatal] show has no completed transcripts")
            valid_episode_ids = {e["id"] for e in show["episodes"]}

            for qtype in AUTO_TYPES:
                quota = profile["quotas"].get(qtype, 0)
                if quota <= 0:
                    continue
                ep_cycle = stratified_episode_cycle(show["episodes"], rng)
                accepted = 0
                attempts = 0
                reject_counts: dict[str, int] = {}
                while accepted < quota and attempts < quota * max_attempts_factor:
                    attempts += 1
                    group = await sample_anchor_group(conn, qtype, show, ep_cycle, rng)
                    if group is None:
                        print(f"[warn] {qtype}: no suitable anchors, stopping type", file=sys.stderr)
                        break
                    prompt = build_generation_prompt(
                        qtype, group, negative_fewshot, profile.get("show_facts")
                    )
                    try:
                        cand = call_llm(model, prompt)
                    except Exception as exc:  # noqa: BLE001
                        print(f"[warn] {qtype} attempt {attempts} LLM failed: {exc}", file=sys.stderr)
                        continue
                    if cand.get("skip"):
                        reject_counts["llm_skip"] = reject_counts.get("llm_skip", 0) + 1
                        continue
                    anchor_ids = {c["chunk_id"] for c in group["chunks"]}
                    ok, reason = validate_candidate(cand, qtype, anchor_ids, banned_topics)
                    if not ok:
                        reject_counts[reason] = reject_counts.get(reason, 0) + 1
                        continue
                    accepted += 1
                    items.append(
                        assemble_item(qtype, cand, group, profile["slug"], round_no, accepted)
                    )
                print(
                    f"[done] {qtype}: {accepted}/{quota} accepted in {attempts} attempts"
                    + (f" (rejects: {reject_counts})" if reject_counts else ""),
                    file=sys.stderr,
                )

            for qtype in HANDCRAFT_TYPES:
                quota = profile["quotas"].get(qtype, 0)
                if quota > 0:
                    print(
                        f"[note] {qtype}: quota {quota} 題留待人工共草（handcraft），"
                        "本腳本不自動產 — 見 golden-set-builder skill",
                        file=sys.stderr,
                    )
    finally:
        await engine.dispose()
    return items, valid_episode_ids


async def dry_run_prompt(
    database_url: str, profile: dict, negative_fewshot: str, seed: int | None
) -> int:
    """Sample real anchors for the first quota'd type, print the exact prompt."""
    from sqlalchemy.ext.asyncio import create_async_engine

    qtype = next((t for t in AUTO_TYPES if profile["quotas"].get(t, 0) > 0), None)
    if qtype is None:
        print("[fatal] profile has no auto-generated quota > 0", file=sys.stderr)
        return 2

    rng = random.Random(seed)
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:
            show = await fetch_show_data(conn, profile["show_id"])
            ep_cycle = stratified_episode_cycle(show["episodes"], rng)
            group = await sample_anchor_group(conn, qtype, show, ep_cycle, rng)
    finally:
        await engine.dispose()
    if group is None:
        print(f"[fatal] no suitable anchors for {qtype}", file=sys.stderr)
        return 2

    print(f"───── SYSTEM PROMPT ─────\n{SYSTEM_PROMPT}\n")
    print(f"───── USER PROMPT ({qtype}) ─────")
    print(build_generation_prompt(qtype, group, negative_fewshot, profile.get("show_facts")))
    return 0


# ────────────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────────────

def _normalize_async_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Anchor-first golden-set generation")
    parser.add_argument(
        "--profile",
        type=Path,
        required=True,
        help="Show profile JSON from show_profile.py (drives quotas)",
    )
    parser.add_argument("--database-url", default=None, help="Override DATABASE_URL")
    parser.add_argument("--model", default=DEFAULT_GEN_MODEL, help="Hub model for generation")
    parser.add_argument(
        "--judge-model",
        default=DEFAULT_JUDGE_MODEL,
        help="Pre-review judge model — MUST differ from --model (anti-self-endorsement)",
    )
    parser.add_argument("--backend-url", default="http://localhost:8000", help="For the retrieval signal (/search)")
    parser.add_argument(
        "--auth-token",
        default=os.environ.get("EVAL_AUTH_TOKEN", ""),
        help="session_id cookie for /search (env EVAL_AUTH_TOKEN as fallback)",
    )
    parser.add_argument(
        "--skip-retrieval-signal",
        action="store_true",
        help="Skip the /search rank check — every item falls to heavy grade",
    )
    parser.add_argument(
        "--review-log",
        type=Path,
        default=DATASETS_DIR / "_review_log.jsonl",
        help="Review log JSONL (auto-rejects appended here)",
    )
    parser.add_argument("--round", type=int, default=1, help="Generation round (id + review log)")
    parser.add_argument(
        "--dry-run-prompt",
        action="store_true",
        help="Print the final generation prompt (with negative few-shot injected) "
             "for the first quota'd type, then exit — no LLM calls.",
    )
    parser.add_argument("--seed", type=int, default=None, help="RNG seed for reproducible sampling")
    parser.add_argument(
        "--ban-topics",
        type=str,
        default=None,
        help="JSON array of topic strings to ban from new questions",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DATASETS_DIR / "_pending_review.json",
        help="Staging output path (default enforces staging discipline)",
    )
    parser.add_argument(
        "--target-main",
        action="store_true",
        help="Write to backend/eval/datasets/{slug}.json — requires "
             "--reviewed-by and --reviewed-at, else exit 2.",
    )
    parser.add_argument("--reviewed-by", default=None)
    parser.add_argument("--reviewed-at", default=None)
    args = parser.parse_args(argv)

    profile = load_profile(args.profile)

    if args.judge_model == args.model:
        print(
            f"[fatal] judge model ({args.judge_model}) must differ from generation "
            "model — pre-review must not self-endorse (golden-set-pipeline spec).",
            file=sys.stderr,
        )
        return 2

    # Staging discipline gate (r3-5-disable-routing, 2026-05-13) — unchanged.
    if args.target_main:
        if not (args.reviewed_by and args.reviewed_at):
            print(
                "[fatal] --target-main requires both --reviewed-by <id> and "
                "--reviewed-at <ISO8601>. Refusing to write to main dataset "
                "without human review metadata.",
                file=sys.stderr,
            )
            return 2
        args.out = DATASETS_DIR / f"{profile['slug']}.json"

    database_url = args.database_url or os.environ.get("DATABASE_URL", "")
    if not database_url:
        load_dotenv(REPO_ROOT / "backend" / ".env")
        database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        print("[fatal] no DATABASE_URL (flag, env, or backend/.env)", file=sys.stderr)
        return 2

    banned_topics: list[str] = json.loads(args.ban_topics) if args.ban_topics else []
    negative_fewshot = build_negative_fewshot(args.review_log, profile["slug"])
    if negative_fewshot:
        print(f"[feedback] negative few-shot injected:\n{negative_fewshot}", file=sys.stderr)

    if args.dry_run_prompt:
        return asyncio.run(
            dry_run_prompt(
                _normalize_async_url(database_url), profile, negative_fewshot, args.seed
            )
        )

    items, valid_episode_ids = asyncio.run(
        generate_all(
            _normalize_async_url(database_url),
            profile,
            args.model,
            args.round,
            banned_topics,
            negative_fewshot,
            seed=args.seed,
        )
    )

    items = run_pre_review(
        items,
        valid_episode_ids,
        profile["show_id"],
        profile["slug"],
        args.round,
        args.judge_model,
        args.backend_url,
        args.auth_token,
        args.review_log,
        args.skip_retrieval_signal,
    )

    if args.target_main:
        for item in items:
            item.pop("anchor_context", None)
            item["reviewed_by"] = args.reviewed_by
            item["reviewed_at"] = args.reviewed_at

    doc = {
        "schema_version": "2.0",
        "show_id": profile["show_id"],
        "show_slug": profile["slug"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "generator": {"model": args.model, "round": args.round, "anchor_first": True},
        "items": items,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(f"[ok] wrote {len(items)} draft items → {args.out}", file=sys.stderr)
    report_round_stats(args.review_log, profile["slug"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
