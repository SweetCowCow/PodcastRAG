"""Pull baseline answers for the bake-off golden set (read-only).

Writes JSON to `backend/scripts/agentic_bakeoff/golden_set/baseline_pull_<ts>.json`.
Covers 19 queries:
- N1-N2  guest finder (馬世芳 / 楊大正)
- N3     topic finder (咖啡)
- N4-N6  date range (2024 H1 / 2024 Nov / 2025 CNY)
- N7-N9  episode summaries (EP143 / EP140 / EP66 / EP19)
- mt01-T1 topic finder (歌單)
- mt02-T2 search_across (家常味)
- mt03 T1/T2/T3 search_within EP140
- mt04 T2/T3 search_within EP19

Run:
  cd backend && python -m scripts.agentic_bakeoff.baseline_pull
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.services import episode_finders, rag
from app.services.ai_step_resolver import get_step_config
from app.services.embedding import embed_texts


SHOW_ID = uuid.UUID("45fc2462-17cf-42f5-98a7-68fe1a222228")
EP_143 = uuid.UUID("6c5ce32f-fb37-4aa0-b72c-7d14a7c1c163")
EP_140 = uuid.UUID("d15bddde-153f-484f-bff6-0bb74415b718")
EP_66 = uuid.UUID("dbeecd79-f170-476a-b4e9-80e64eb49528")
EP_19 = uuid.UUID("88f78fbe-d216-4334-bf4f-e3e3caeea48d")


def _ep_to_dict(ep) -> dict:
    return {
        "episode_id": str(ep.episode_id),
        "title": ep.title,
        "published_at": ep.published_at.isoformat() if ep.published_at else None,
        "guests": list(ep.guests or []),
        "ai_summary": ep.ai_summary,
    }


def _hit_to_dict(h) -> dict:
    return {
        "chunk_id": str(h.chunk_id) if h.chunk_id else None,
        "episode_id": str(h.episode_id),
        "text": (getattr(h, "text", "") or "")[:240],
        "rrf_score": float(h.rrf_score or 0.0),
        "pool": getattr(h, "source_pool", None),
    }


async def main():
    eng = create_async_engine(settings.database_url)
    Session = async_sessionmaker(eng, expire_on_commit=False)
    out: dict = {
        "pulled_at": datetime.now(timezone.utc).isoformat(),
        "show_id": str(SHOW_ID),
        "baselines": {},
    }
    b = out["baselines"]

    async with Session() as db:
        # ---- guest finders ----
        for name in ["馬世芳", "楊大正"]:
            rows = await episode_finders.find_episodes_by_guest(db, SHOW_ID, [name])
            b[f"guest_{name}"] = [_ep_to_dict(r) for r in rows]

        # ---- topic finders ----
        for term in ["咖啡", "歌單"]:
            rows = await episode_finders.find_episodes_by_topic(db, SHOW_ID, [term])
            b[f"topic_{term}"] = [_ep_to_dict(r) for r in rows]

        # ---- date ranges ----
        ranges = [
            ("2024_h1",
             datetime(2024, 1, 1, tzinfo=timezone.utc),
             datetime(2024, 6, 30, 23, 59, 59, tzinfo=timezone.utc)),
            ("2024_11",
             datetime(2024, 11, 1, tzinfo=timezone.utc),
             datetime(2024, 11, 30, 23, 59, 59, tzinfo=timezone.utc)),
            ("2025_cny",
             datetime(2025, 1, 25, tzinfo=timezone.utc),
             datetime(2025, 2, 10, 23, 59, 59, tzinfo=timezone.utc)),
        ]
        for label, s, e in ranges:
            rows = await episode_finders.find_episodes_by_date_range(db, SHOW_ID, s, e)
            b[f"date_{label}"] = [_ep_to_dict(r) for r in rows]

        # ---- episode summaries ----
        summary_eps = {"EP143": EP_143, "EP140": EP_140, "EP66": EP_66, "EP19": EP_19}
        for label, ep_id in summary_eps.items():
            r = await db.execute(
                text("SELECT id, title, published_at, ai_summary FROM episodes WHERE id = :id"),
                {"id": ep_id},
            )
            row = r.mappings().first()
            b[f"summary_{label}"] = (
                {
                    "episode_id": str(row["id"]),
                    "title": row["title"],
                    "published_at": row["published_at"].isoformat() if row["published_at"] else None,
                    "ai_summary": row["ai_summary"],
                }
                if row
                else None
            )

        # ---- embedding-backed searches ----
        step = await get_step_config(db, "embedding")

        # mt02-T2 家常味 across show
        vec = embed_texts(["家常味"], step)[0]
        hits = await rag.retrieve_hybrid(
            db, show_id=SHOW_ID, query_embedding=vec, question="家常味", k=8
        )
        b["search_家常味_across"] = [_hit_to_dict(h) for h in hits]

        # mt03 within EP140
        for q in ["第二彈來賓是誰", "推薦的餐廳", "推薦餐廳的料理"]:
            vec = embed_texts([q], step)[0]
            hits = await rag.retrieve_hybrid(
                db, show_id=SHOW_ID, query_embedding=vec, question=q, k=5,
                episode_id_filter=[EP_140],
            )
            b[f"search_EP140_{q}"] = [_hit_to_dict(h) for h in hits]

        # mt04 within EP19
        for q in ["大家推薦了哪些歌", "歌出自哪部作品"]:
            vec = embed_texts([q], step)[0]
            hits = await rag.retrieve_hybrid(
                db, show_id=SHOW_ID, query_embedding=vec, question=q, k=5,
                episode_id_filter=[EP_19],
            )
            b[f"search_EP19_{q}"] = [_hit_to_dict(h) for h in hits]

    # ---- write output ----
    out_dir = Path(__file__).parent / "golden_set"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"baseline_pull_{ts}.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2))

    print(f"WROTE: {out_path}")
    print(f"baselines: {len(b)} entries")
    for k, v in b.items():
        n = len(v) if isinstance(v, list) else (1 if v else 0)
        print(f"  {k:40s} = {n}")


if __name__ == "__main__":
    asyncio.run(main())
