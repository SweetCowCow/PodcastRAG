"""Helper script to synthesise core golden-set items for a show.

Workflow:
1. Load show + N episodes' transcript chunks via the running backend.
2. Sample 5 episodes (longest transcripts win, with a small random factor).
3. For each (type, quota) pair, prompt an LLM with few-shot examples
   to generate questions anchored to specific chunk_ids.
4. Write JSON to a STAGING file for human audit.

STAGING DISCIPLINE (since r3-5-disable-routing audit, 2026-05-13):
Output SHALL be written to `backend/eval/datasets/_pending_review.json` by
default. The main dataset (`backend/eval/datasets/{show_slug}.json`) SHALL
NOT be overwritten by this script directly. The 2026-05-13 audit of this
script's prior output (36 `thisno-core-*` items) showed a verified bad-
question rate of ≥75% — single-keyword-triggered deep questions, anchors
not aligned with question semantics, cross-episode anchors with episodes
unrelated to the question.

To write directly to the main dataset (e.g. after a human review pass),
all three of `--target-main`, `--reviewed-by <id>`, and `--reviewed-at
<ISO8601>` MUST be supplied. Absent any one of them, the script exits with
code 2 to prevent accidental main-dataset corruption.

NOTE: This script generates *core* items only. The 10 sentinel items must
be hand-crafted by a human with verified ground-truth chunk_ids — see
.claude/skills/golden-set-builder/SKILL.md for the full workflow.

Usage (staging, default):
    python -m backend.eval.scripts.build_golden_set \
        --show-id <uuid> \
        --backend-url http://localhost:8000 \
        --auth-token $EVAL_AUTH_TOKEN \
        --n-core 40

Usage (write to main, requires review metadata):
    python -m backend.eval.scripts.build_golden_set \
        --show-id <uuid> --show-slug this-not-that-cool \
        --target-main \
        --reviewed-by reviewer-id \
        --reviewed-at 2026-05-13T10:00:00Z \
        ...
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from pathlib import Path
from typing import Iterable

# Type quotas for core items (sentinel handled separately).
# Sums to 40 by default.
DEFAULT_TYPE_QUOTAS = {
    "fact": 16,
    "comprehension": 10,
    "cross-episode": 8,
    "negative": 4,
    "code-switch": 2,
}

REPO_ROOT = Path(__file__).resolve().parents[3]


# ────────────────────────────────────────────────────────────────────
# LLM prompt templates (Chinese / Code-switched, few-shot)
# ────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """你是 RAG 評測題庫的出題助手。針對給定的 podcast 逐字稿片段，產生符合指定題型的中文問句，模擬真實使用者向這個 podcast 提問的行為。

【節目背景】
本節目是嘻哈/podcast/生活向的台灣中文 podcast。主持人迪拉胖是「顏色唱片公司」(yanse) 創辦人兼老闆，也是大嘻哈時代評審；常聊嘻哈音樂、節目幕後、餐飲與生活。共同主持人有方品融、杜忠祐、阿鳴。常邀台灣嘻哈圈、podcast 圈、美食/作家圈來賓。

【硬性品質要求】
1. 問題必須包含至少一個具體 entity（人名 / 歌名 / 樂風 / 餐廳 / 地名 / 數字 / 品牌 / 專輯名）。
2. 嚴禁「有提到 XX 嗎」「有討論 XX 嗎」這種空泛 yes/no 模板。問題要問「誰／什麼／哪裡／為什麼／多少」這類具體問句。
3. ground_truth_chunk_ids 必須從提供的片段中挑，不能編造。

回答僅以 JSON 格式，不要有任何前後綴文字。"""


_TYPE_RULES = {
    "fact": (
        "答案必須是片段裡可以直接讀到的具體事實（人物、時間、地點、數字、引用）。"
        "Question 應該問『誰／什麼／何時／哪裡／多少』而非 yes/no。"
        "**嚴禁**問題裡只用「主持人/節目/某人」這種泛指 — 必須點名具體 entity（迪拉、Leo、馬世芳、特定歌名/餐廳名）。"
        "**嚴禁**多題問同一個主題（例：兩題都問臘腸、兩題都問油條）。"
    ),
    "comprehension": (
        "需要從片段內容歸納或解釋「動機/觀點/比喻」，而非單純複述事實。"
        "例：『迪拉為什麼選 X 而不是 Y？』『馬世芳如何形容 X 的特色？』"
        "**嚴禁**問句裡用『可能/是否/或許/也許』這類含糊詞 — 答案要有清楚立場。"
        "禁止只是把 fact 加上問號當 comprehension。"
    ),
    "cross-episode": (
        "ground_truth_chunk_ids 必須來自至少 2 個不同 episode_id（ep: 前綴後的 UUID）。"
        "題目應該問**明確**貫穿多集的人物、習慣、概念，不是隨機抽兩段引文硬扯關聯。"
        "好例：『迪拉在多集裡多次提到他跟某位前輩的相處模式是什麼？』『節目中常討論的某個飲食習慣是什麼？』"
        "**嚴禁**用『是否多次提到』『是否曾』『多集裡是不是』這類含糊問法。"
    ),
    "negative": (
        "問『show 鄰近領域但這 5 集沒講』的事 — 例如此 show 是嘻哈/生活向，"
        "可問特定饒舌歌手是否曾上節目（除非真的有）、特定城市嘻哈場景是否提過、"
        "某個音樂類型的某面向。**禁用**過於明顯的『量子力學/區塊鏈/太空探索/AI 趨勢』陳腔濫調。"
        "ground_truth_chunk_ids 要是空陣列。"
    ),
    "code-switch": (
        "Question 必須包含至少 1 個英文詞（樂風名 / 術語 / 人名 / 平台名 / 品牌），"
        "並且夾雜中文。"
        "例：『他怎麼看 mainstream 跟 underground 嘻哈的差別？』『他在 Spotify 上推薦了哪首歌？』"
    ),
}


def _build_fewshot_block(qtype: str, sentinel_examples: list[dict]) -> str:
    """Build few-shot examples: 1 hardcoded type-template + up to 2 from sentinel."""
    hardcoded = {
        "fact": '{"question": "馬芳在《也好吃》裡寫的家族百年菜餚是哪一道？", "expected_answer_keywords": ["百頁包肉", "家族", "百年"], "ground_truth_chunk_ids": ["ep:6c5ce32f-fb37-4aa0-b72c-7d14a7c1c163@2270.00"]}',
        "comprehension": '{"question": "迪拉怎麼形容中老年人不需要振奮型開工歌的理由？", "expected_answer_keywords": ["平時皮繃比較緊", "不需要", "安身之處"], "ground_truth_chunk_ids": ["ep:c1d87278-7dba-4fb1-930d-c2bd3a3461d2@2017.76"]}',
        "cross-episode": '{"question": "節目主持人陣容從第一集到 EP134 有什麼變化？", "expected_answer_keywords": ["三人", "四人", "阿鳴", "加入"], "ground_truth_chunk_ids": ["ep:9359c207-1970-4ab4-acce-bf8d44967b68@0.00", "ep:c1d87278-7dba-4fb1-930d-c2bd3a3461d2@24.88"]}',
        "negative": '{"question": "節目裡有提到 Drake 來過台灣演唱會嗎？", "expected_answer_keywords": [], "ground_truth_chunk_ids": []}',
        "code-switch": '{"question": "節目裡他們怎麼形容英國 Drill 音樂的 quick out 特色？", "expected_answer_keywords": ["口氣", "Pop Smoke", "口腔"], "ground_truth_chunk_ids": ["ep:c1d87278-7dba-4fb1-930d-c2bd3a3461d2@990.68"]}',
    }
    examples = [hardcoded[qtype]]
    for s in sentinel_examples:
        if s.get("type") == qtype:
            examples.append(json.dumps({
                "question": s["question"],
                "expected_answer_keywords": s["expected_answer_keywords"][:5],
                "ground_truth_chunk_ids": s["ground_truth_chunk_ids"],
            }, ensure_ascii=False))
        if len(examples) >= 3:
            break
    return "\n".join(f"範例 {i+1}：{e}" for i, e in enumerate(examples))


def _build_user_prompt(
    qtype: str,
    n: int,
    chunks: list[dict],
    sentinel_examples: list[dict],
    banned_topics: list[str],
) -> str:
    """Build prompt asking LLM to generate n questions of qtype from chunks."""
    chunk_blocks = "\n".join(
        f"[{c['chunk_id']}] {c['text']}" for c in chunks
    )
    rule = _TYPE_RULES[qtype]
    fewshot = _build_fewshot_block(qtype, sentinel_examples)
    ban_block = ""
    if banned_topics:
        ban_block = (
            f"\n【🚫 禁用主題】（這些主題已經有題目了，**不要**再生這些）："
            f"\n{', '.join(banned_topics)}\n"
        )
    return (
        f"題型：{qtype}\n"
        f"需要生成 {n} 個高品質題目。\n\n"
        f"【本題型規則】\n{rule}\n"
        f"{ban_block}\n"
        f"【few-shot 範例】\n{fewshot}\n\n"
        f"輸出 JSON object，包含 key『items』為 array，每個元素有 "
        f"question / expected_answer_keywords (最多 5 個) / ground_truth_chunk_ids。\n\n"
        f"【可用片段】\n{chunk_blocks}"
    )


# ────────────────────────────────────────────────────────────────────
# Validation
# ────────────────────────────────────────────────────────────────────

import re as _re

_BAD_TEMPLATES = (
    "有提到", "有討論", "是否提到過", "是否有提到", "是否有討論",
    "是否多次", "是否曾", "可能", "或許", "也許",
)


def _validate_item(
    item: dict,
    qtype: str,
    valid_chunk_ids: set[str],
    banned_topics: list[str] | None = None,
) -> tuple[bool, str]:
    """Return (ok, reason). Reason is empty if ok."""
    q = item.get("question", "")
    if not q or len(q) > 500:
        return False, "empty or too long"
    if any(t in q for t in _BAD_TEMPLATES):
        return False, "uses banned yes/no template"
    if banned_topics:
        for topic in banned_topics:
            if topic and topic in q:
                return False, f"hits banned topic: {topic}"

    gt = item.get("ground_truth_chunk_ids", [])

    if qtype == "negative":
        if gt:
            return False, "negative must have empty ground_truth"
        return True, ""

    if not gt:
        return False, "non-negative must have ≥1 chunk"
    bad = [c for c in gt if c not in valid_chunk_ids]
    if bad:
        return False, f"hallucinated chunk_id: {bad[0]}"

    if qtype == "cross-episode":
        ep_ids = {c.split("@")[0] for c in gt}
        if len(ep_ids) < 2:
            return False, f"cross-episode needs ≥2 episodes, got {len(ep_ids)}"

    if qtype == "code-switch":
        if not _re.search(r"[A-Za-z]", q):
            return False, "code-switch question must contain English"

    return True, ""


# ────────────────────────────────────────────────────────────────────
# Backend interaction (chunks fetch — uses internal admin endpoint)
# ────────────────────────────────────────────────────────────────────

def _fetch_chunks(backend_url: str, show_id: str, token: str) -> list[dict]:
    """Fetch transcript chunks for a show, sampled across 5 longest episodes.

    Returns list of {chunk_id, text, episode_id, start_time}.
    Uses public endpoints; token is optional (sent only if non-empty).
    """
    import urllib.request

    def _get(path: str) -> dict:
        headers: dict[str, str] = {}
        if token:
            headers["Cookie"] = f"session_id={token}"
        req = urllib.request.Request(f"{backend_url}{path}", headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())

    eps = _get(f"/shows/{show_id}/episodes?limit=200")
    transcribed = [e for e in eps if e.get("transcript_status") == "completed"]
    transcribed.sort(key=lambda e: e.get("duration_seconds", 0), reverse=True)
    chosen = transcribed[:5]

    chunks: list[dict] = []
    for ep in chosen:
        ep_id = ep["id"]
        try:
            t = _get(f"/episodes/{ep_id}/transcript")
        except Exception as exc:
            print(f"[warn] transcript fetch failed for {ep_id}: {exc}", file=sys.stderr)
            continue
        for seg in t.get("segments", []):
            chunks.append({
                "chunk_id": f"ep:{ep_id}@{seg['start_time']:.2f}",
                "text": seg["text"],
                "episode_id": ep_id,
                "start_time": seg["start_time"],
            })
    return chunks


def _sample_chunks(chunks: list[dict], k: int = 30, seed: int | None = None) -> list[dict]:
    """Sample k chunks across episodes for diversity. seed=None → fresh random each call."""
    if len(chunks) <= k:
        return chunks
    rng = random.Random(seed)
    return rng.sample(chunks, k)


# ────────────────────────────────────────────────────────────────────
# LLM call (Hub gpt-4o)
# ────────────────────────────────────────────────────────────────────

def _generate(
    qtype: str,
    n: int,
    chunks: list[dict],
    model: str,
    sentinel_examples: list[dict],
    banned_topics: list[str],
) -> list[dict]:
    """Call hub LLM to generate n items of qtype. Returns parsed JSON list."""
    from openai import OpenAI

    client = OpenAI(
        api_key=os.environ["OPENAI_API_KEY"],
        base_url="https://hnd1.aihub.zeabur.ai/v1",
    )
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(qtype, n, chunks, sentinel_examples, banned_topics)},
        ],
        response_format={"type": "json_object"},
        temperature=0.8,
        max_tokens=8192,
    )
    raw = response.choices[0].message.content or ""
    if not raw.strip():
        finish = response.choices[0].finish_reason
        raise ValueError(f"empty content (finish={finish})")
    # gpt-4o through hub sometimes wraps JSON in ```json ... ``` despite response_format
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"json parse failed: {exc}; raw[:300]={raw[:300]!r}") from exc
    items = parsed.get("items") if isinstance(parsed, dict) else parsed
    if not isinstance(items, list):
        raise ValueError(f"LLM did not return a list: {raw[:200]}")
    return items


def _load_sentinel(path: Path | None) -> list[dict]:
    if path is None:
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("items", []) if isinstance(data, dict) else []


# ────────────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────────────

def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build core golden-set items via LLM")
    parser.add_argument("--show-id", required=True, help="Show UUID")
    parser.add_argument("--show-slug", required=True, help="Lowercase slug for output dataset")
    parser.add_argument("--backend-url", default="http://localhost:8000")
    parser.add_argument(
        "--auth-token",
        default=os.environ.get("EVAL_AUTH_TOKEN", ""),
        help="Session token (env EVAL_AUTH_TOKEN as fallback)",
    )
    parser.add_argument("--n-core", type=int, default=40)
    parser.add_argument(
        "--quota",
        type=str,
        default=None,
        help="JSON object overriding per-type quotas, e.g. '{\"fact\":9,\"comprehension\":5}'",
    )
    parser.add_argument(
        "--ban-topics",
        type=str,
        default=None,
        help="JSON array of topic strings to ban from new questions (e.g. existing keep set)",
    )
    parser.add_argument("--model", default="gpt-4o", help="Hub model for synthesis")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("backend/eval/datasets/_pending_review.json"),
        help="Staging output path. To write to the main per-show dataset use "
             "--target-main with --reviewed-by/--reviewed-at.",
    )
    parser.add_argument(
        "--target-main",
        action="store_true",
        help="If set together with --reviewed-by and --reviewed-at, write "
             "directly to backend/eval/datasets/{show_slug}.json. Otherwise "
             "the script exits with code 2 to enforce staging discipline.",
    )
    parser.add_argument(
        "--reviewed-by",
        default=None,
        help="Required when --target-main is set: non-empty reviewer identifier.",
    )
    parser.add_argument(
        "--reviewed-at",
        default=None,
        help="Required when --target-main is set: ISO8601 timestamp of review.",
    )
    parser.add_argument(
        "--sentinel-path",
        type=Path,
        default=None,
        help="Optional sentinel JSON; items used as positive few-shot per type",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=2,
        help="Max regenerate rounds per type to fill quota with valid items",
    )
    args = parser.parse_args(argv)

    # Staging discipline gate (r3-5-disable-routing, 2026-05-13)
    if args.target_main:
        if not (args.reviewed_by and args.reviewed_at):
            print(
                "[fatal] --target-main requires both --reviewed-by <id> and "
                "--reviewed-at <ISO8601>. Refusing to write to main dataset "
                "without human review metadata.",
                file=sys.stderr,
            )
            return 2
        args.out = Path(f"backend/eval/datasets/{args.show_slug}.json")

    chunks = _fetch_chunks(args.backend_url, args.show_id, args.auth_token)
    if len(chunks) < 10:
        print(f"only {len(chunks)} chunks available — need at least 10", file=sys.stderr)
        return 3

    sampled = _sample_chunks(chunks, k=30)
    valid_chunk_ids = {c["chunk_id"] for c in chunks}  # full set, not just sampled

    sentinel_examples = _load_sentinel(args.sentinel_path)
    banned_topics: list[str] = json.loads(args.ban_topics) if args.ban_topics else []
    print(
        f"[setup] {len(chunks)} chunks, {len(sentinel_examples)} sentinel examples, "
        f"{len(banned_topics)} banned topics",
        file=sys.stderr,
    )

    all_items: list[dict] = []

    if args.quota:
        override = json.loads(args.quota)
        quotas = {k: int(override.get(k, 0)) for k in DEFAULT_TYPE_QUOTAS}
        quotas = {k: v for k, v in quotas.items() if v > 0}
    else:
        quotas = {**DEFAULT_TYPE_QUOTAS}
        if sum(quotas.values()) != args.n_core:
            scale = args.n_core / sum(quotas.values())
            quotas = {k: max(1, round(v * scale)) for k, v in quotas.items()}

    for qtype, n in quotas.items():
        accepted: list[dict] = []
        rejected_reasons: list[str] = []
        attempts = 0
        while len(accepted) < n and attempts <= args.max_retries:
            attempts += 1
            need = n - len(accepted)
            ask = need + 2  # over-generate a bit for slack
            print(f"[gen] {qtype} attempt {attempts}: asking {ask}, have {len(accepted)}/{n}", file=sys.stderr)
            try:
                # fresh random sample each attempt for diversity
                sample_for_call = _sample_chunks(chunks, k=30, seed=None)
                generated = _generate(
                    qtype, ask, sample_for_call, args.model,
                    sentinel_examples, banned_topics,
                )
            except Exception as exc:  # noqa: BLE001
                print(f"[warn] {qtype} attempt {attempts} failed: {exc}", file=sys.stderr)
                continue
            for g in generated:
                if len(accepted) >= n:
                    break
                ok, reason = _validate_item(g, qtype, valid_chunk_ids, banned_topics)
                if ok:
                    accepted.append(g)
                else:
                    rejected_reasons.append(reason)

        print(
            f"[done] {qtype}: {len(accepted)}/{n} valid"
            f" (rejected {len(rejected_reasons)}: "
            f"{dict((r, rejected_reasons.count(r)) for r in set(rejected_reasons))})",
            file=sys.stderr,
        )
        slug_short = args.show_slug.replace("-", "")[:6]
        for i, g in enumerate(accepted):
            all_items.append({
                "id": f"{slug_short}-core-{qtype[:3]}-{i:03d}",
                "type": qtype,
                "question": g.get("question", ""),
                "expected_answer_keywords": g.get("expected_answer_keywords", []),
                "ground_truth_chunk_ids": g.get("ground_truth_chunk_ids", []),
                "sentinel": False,
                "source_episode_id": _extract_episode_id(g.get("ground_truth_chunk_ids", [])),
            })

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(all_items, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[ok] wrote {len(all_items)} draft items → {args.out}", file=sys.stderr)
    return 0


def _extract_episode_id(chunk_ids: list[str]) -> str:
    """Extract episode UUID from first chunk_id, or empty string."""
    if not chunk_ids:
        return ""
    parts = chunk_ids[0].split("@")[0].removeprefix("ep:")
    return parts


if __name__ == "__main__":
    sys.exit(main())
