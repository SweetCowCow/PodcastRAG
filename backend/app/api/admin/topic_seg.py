from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require_admin
from app.schemas.topic_seg import AuditSampleItem
from app.services.topic_segmentation import UNIVERSAL_LABELS

router = APIRouter(
    prefix="/topic-seg",
    tags=["admin", "topic-seg"],
    dependencies=[Depends(require_admin)],
)


_SAMPLE_SQL = """
WITH sampled AS (
    SELECT s.id AS segment_id,
           s.transcript_id,
           s.start_time,
           s.end_time,
           s.text,
           s.topic_label,
           t.episode_id,
           e.title AS episode_title,
           e.show_id
    FROM transcript_segments s
    JOIN transcripts t ON t.id = s.transcript_id
    JOIN episodes e ON e.id = t.episode_id
    WHERE s.topic_label IS NOT NULL
    ORDER BY random()
    LIMIT :n
)
SELECT s.segment_id,
       s.episode_id,
       s.episode_title,
       s.start_time,
       s.end_time,
       s.text,
       s.topic_label,
       prev_seg.text AS prev_text,
       next_seg.text AS next_text,
       sh.segment_categories AS show_extensions
FROM sampled s
JOIN shows sh ON sh.id = s.show_id
LEFT JOIN LATERAL (
    SELECT ps.text
    FROM transcript_segments ps
    WHERE ps.transcript_id = s.transcript_id
      AND ps.start_time < s.start_time
    ORDER BY ps.start_time DESC
    LIMIT 1
) prev_seg ON TRUE
LEFT JOIN LATERAL (
    SELECT ns.text
    FROM transcript_segments ns
    WHERE ns.transcript_id = s.transcript_id
      AND ns.start_time > s.start_time
    ORDER BY ns.start_time ASC
    LIMIT 1
) next_seg ON TRUE
"""


@router.get("/audit-sample", response_model=list[AuditSampleItem])
async def audit_sample(
    db: AsyncSession = Depends(get_db),
    n: int = Query(default=50, ge=1, le=200),
) -> list[AuditSampleItem]:
    result = await db.execute(text(_SAMPLE_SQL), {"n": n})
    items: list[AuditSampleItem] = []
    universal = set(UNIVERSAL_LABELS)
    for row in result.mappings():
        extensions = row["show_extensions"] or []
        ext_names = {
            str(e.get("name", "")).strip()
            for e in extensions
            if isinstance(e, dict) and e.get("name")
        }
        label = row["topic_label"]
        is_show_specific = label not in universal and label in ext_names
        items.append(
            AuditSampleItem(
                segment_id=row["segment_id"],
                episode_id=row["episode_id"],
                episode_title=row["episode_title"],
                start_time=float(row["start_time"]),
                end_time=float(row["end_time"]),
                text=row["text"],
                topic_label=label,
                prev_text=row["prev_text"],
                next_text=row["next_text"],
                is_show_specific_label=is_show_specific,
            )
        )
    return items
