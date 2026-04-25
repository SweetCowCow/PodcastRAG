import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.episode import Episode
from app.services.rss_parser import fetch_and_parse


async def sync_show_episodes(show_id: uuid.UUID, db: AsyncSession) -> dict:
    """Fetch the show's RSS feed and upsert episodes by GUID.

    Returns ``{"added": int, "updated": int, "total": int}``. Raises
    ``RssParseError`` for the caller to translate into HTTP 400.
    """
    from app.models.show import Show

    show = await db.get(Show, show_id)
    if show is None:
        raise LookupError(f"Show {show_id} not found")

    parsed = await fetch_and_parse(show.rss_url)

    existing_rows = (
        await db.execute(select(Episode).where(Episode.show_id == show_id))
    ).scalars().all()
    existing_by_guid: dict[str, Episode] = {ep.guid: ep for ep in existing_rows}

    added = 0
    updated = 0
    for ep in parsed.episodes:
        existing_ep = existing_by_guid.get(ep.guid)
        if existing_ep:
            changed = False
            for field in ("title", "description", "audio_url", "duration_seconds", "published_at"):
                new_value = getattr(ep, field)
                if getattr(existing_ep, field) != new_value:
                    setattr(existing_ep, field, new_value)
                    changed = True
            if changed:
                updated += 1
        else:
            db.add(
                Episode(
                    show_id=show_id,
                    title=ep.title,
                    description=ep.description,
                    audio_url=ep.audio_url,
                    duration_seconds=ep.duration_seconds,
                    published_at=ep.published_at,
                    guid=ep.guid,
                )
            )
            added += 1

    await db.flush()
    total = await db.scalar(
        select(func.count(Episode.id)).where(Episode.show_id == show_id)
    )
    return {"added": added, "updated": updated, "total": total or 0}
