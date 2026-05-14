"""LLM-driven entity extractor for the RAG chat path.

Single OpenAI-compatible chat call. Takes the user's question + current
datetime, returns a `QueryEntities` instance describing what date range,
guest names, and topics the question references. The result feeds the
chat path's metadata filter; an empty result (or any failure) falls back
to no-filter retrieval — this is the fail-open contract.

Usage from chat path (Phase 9 will wire this up):

    from openai import AsyncOpenAI
    client = AsyncOpenAI(base_url=..., api_key=...)
    entities = await extract_entities(client, model="gpt-4o-mini", question=q, now=datetime.now(UTC))

The function never raises — failures are converted to `QueryEntities.empty()`
and surface via the structured `extraction_status` field on the returned
tuple. Caller may log / count failures but MUST NOT block the chat path on
extraction errors.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from openai import APIError, AsyncOpenAI
from pydantic import ValidationError

from app.schemas.query_entity import QUERY_ENTITIES_JSON_SCHEMA, QueryEntities

logger = logging.getLogger(__name__)


class ExtractionStatus(str, Enum):
    ok = "ok"
    api_error = "api_error"
    invalid_json = "invalid_json"
    schema_mismatch = "schema_mismatch"
    empty_response = "empty_response"


_SYSTEM_PROMPT = """\
You extract structured entities from a Chinese-language podcast search query.

Return ONLY a JSON object matching this shape:
{
  "date_range": null | [iso_start, iso_end],
  "guests": [string, ...],
  "topics": [string, ...]
}

Rules:
- `date_range`: only set when the question references a SPECIFIC time window
  (year, month, season, "去年", "最近這集", etc). For "去年" use last full
  calendar year. For "最近這集" return null (no concrete bound). Always UTC,
  midnight at boundaries.
- `guests`: only proper-noun-like guest names that appear in the question.
  Do NOT include the hosts (迪拉 / 方品融 / 杜忠祐 / 阿鳴) unless the
  question is explicitly about them as guests in another show.
- `topics`: subject keywords the question pivots on (歌單 / 高雄美食 /
  烤肉 / 跑鞋 etc). Skip generic verbs (講, 聊, 提到).
- If a category does not apply, return null / [].
- Output MUST be valid JSON. No commentary, no surrounding text.

Examples (question → expected JSON, formatted for readability — output is one line):

Q: "馬世芳上過哪幾集？"
A: {"date_range": null, "guests": ["馬世芳"], "topics": []}

Q: "2024 那集是哪集？"
A: {"date_range": ["2024-01-01T00:00:00Z", "2025-01-01T00:00:00Z"], "guests": [], "topics": []}

Q: "去年有沒有聊到歌單？"
A: {"date_range": ["YYYY-01-01T00:00:00Z", "YYYY+1-01-01T00:00:00Z"], "guests": [], "topics": ["歌單"]}
   (substitute actual last-year year)

Q: "節目裡有哪些集是歌單？"
A: {"date_range": null, "guests": [], "topics": ["歌單"]}

Q: "高雄美食那幾集有講到鴨肉嗎？"
A: {"date_range": null, "guests": [], "topics": ["高雄美食", "鴨肉"]}

Q: "Leo王 和 迪拉 是怎麼認識的？"
A: {"date_range": null, "guests": ["Leo王"], "topics": []}
   (迪拉 is host; do NOT include)

Q: "馬芳跟馬世芳是同一個人嗎？"
A: {"date_range": null, "guests": ["馬芳", "馬世芳"], "topics": []}

Q: "你們是誰？"
A: {"date_range": null, "guests": [], "topics": []}
"""


async def extract_entities(
    client: AsyncOpenAI,
    *,
    model: str,
    question: str,
    now: datetime | None = None,
) -> tuple[QueryEntities, ExtractionStatus]:
    """Run the entity extractor.

    Never raises. Always returns (entities, status). On any failure the
    entities are `QueryEntities.empty()` and the caller MUST proceed with
    no-filter retrieval (fail-open).
    """
    now = now or datetime.now(timezone.utc)
    user_content = f"current_datetime_utc: {now.isoformat()}\nquestion: {question.strip()}"

    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.0,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "query_entities",
                    "strict": True,
                    "schema": QUERY_ENTITIES_JSON_SCHEMA,
                },
            },
        )
    except APIError as exc:
        logger.warning("entity_extraction api_error: %s", exc)
        return QueryEntities.empty(), ExtractionStatus.api_error
    except Exception as exc:  # noqa: BLE001 — fail-open contract
        logger.warning("entity_extraction unexpected_error: %s", exc)
        return QueryEntities.empty(), ExtractionStatus.api_error

    content = (resp.choices[0].message.content or "").strip() if resp.choices else ""
    if not content:
        return QueryEntities.empty(), ExtractionStatus.empty_response

    try:
        parsed: Any = json.loads(content)
    except json.JSONDecodeError as exc:
        logger.warning("entity_extraction invalid_json: %s; content=%r", exc, content[:300])
        return QueryEntities.empty(), ExtractionStatus.invalid_json

    try:
        entities = QueryEntities.model_validate(parsed)
    except ValidationError as exc:
        logger.warning("entity_extraction schema_mismatch: %s", exc)
        return QueryEntities.empty(), ExtractionStatus.schema_mismatch

    return entities, ExtractionStatus.ok
