"""Beat-driven sentinel probe for open circuit breakers.

Part of `task-failure-monitoring-and-circuit-breaker`. Runs every 30 min
(see ``celery_app.beat_schedule['circuit-probe']``). For each provider
whose ``service_circuit_state.state='open'``, issue a cheap "ping"
request against that provider:

- ``openai``: chat.completions ``model=gpt-4o-mini`` ``max_tokens=1``
- ``aihub``: same payload but against the AI Hub base URL configured
  in ai_steps (we read the first row that uses provider=aihub)
- ``zsend``: GET ``https://api.zeabur.com/api/v1/zsend/usage``

On success → atomic ``close(provider_id, by='probe', kind='probe')`` +
send recovery email. On failure → stamp ``last_probe_*`` and leave open.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.models.service_circuit_state import (
    CircuitState,
    ServiceCircuitState,
)
from app.services import circuit_breaker
from app.services.zsend import ZSendError, send_recovery_notice
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _new_engine():
    return create_async_engine(settings.database_url, poolclass=NullPool)


@celery_app.task(name="app.workers.circuit_probe.run_circuit_probe")
def run_circuit_probe() -> dict:
    return asyncio.run(_run())


async def _run() -> dict:
    engine = _new_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            open_rows = (
                await session.execute(
                    select(ServiceCircuitState).where(
                        ServiceCircuitState.state == CircuitState.open.value
                    )
                )
            ).scalars().all()
            snapshots = [
                {
                    "provider_id": r.provider_id,
                    "opened_at": r.opened_at,
                    "paused_task_count": r.paused_task_count,
                }
                for r in open_rows
            ]
    finally:
        await engine.dispose()

    if not snapshots:
        return {"probed": 0}

    closed = 0
    failed = 0
    for snap in snapshots:
        pid = snap["provider_id"]
        try:
            success = await _probe(pid)
        except Exception:
            logger.exception("circuit_probe: probe %s raised", pid)
            success = False
        await circuit_breaker.update_probe_result(pid, success=success)
        if not success:
            failed += 1
            continue

        result_row = await circuit_breaker.close(
            pid, by="sentinel-probe", kind="probe"
        )
        if result_row is None:
            # Already closed by admin between snapshot + close.
            continue
        closed += 1
        try:
            await send_recovery_notice(
                provider_id=pid,
                opened_at=snap["opened_at"],
                closed_at=datetime.now(timezone.utc),
                paused_count=snap["paused_task_count"] or 0,
                kind="probe",
            )
        except (ZSendError, Exception):
            logger.exception(
                "circuit_probe: recovery email failed for %s", pid
            )
    return {"probed": len(snapshots), "closed": closed, "failed": failed}


async def _probe(provider_id: str) -> bool:
    if provider_id == "openai":
        return await _probe_openai()
    if provider_id == "aihub":
        return await _probe_aihub()
    if provider_id == "zsend":
        return await _probe_zsend()
    logger.warning("circuit_probe: unknown provider %s", provider_id)
    return False


async def _probe_openai() -> bool:
    try:
        from openai import AsyncOpenAI

        # Reuse fallback key resolver (DB first, env fallback).
        api_key = await circuit_breaker._resolve_openai_direct_key()
        if not api_key:
            return False
        client = AsyncOpenAI(api_key=api_key)
        await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=1,
        )
        return True
    except Exception:
        logger.info("circuit_probe: openai probe failed", exc_info=True)
        return False


async def _probe_aihub() -> bool:
    """Probe the aihub OpenAI-compatible endpoint via the same client SDK
    settings used by ai_steps. Best-effort: any failure → False."""
    try:
        from sqlalchemy.ext.asyncio import (
            async_sessionmaker as _ams,
            create_async_engine as _cae,
        )

        from app.models.ai_step import AiStep
        from app.services.ai_step_resolver import get_step_config

        engine = _cae(settings.database_url, poolclass=NullPool)
        try:
            async with _ams(engine, expire_on_commit=False)() as session:
                # 任一 LLM step（summary 通常一定有設）拿 base_url + key。
                step = await get_step_config(session, "summary")
        finally:
            await engine.dispose()

        if not step or not step.base_url or not step.api_key:
            return False
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=step.api_key, base_url=step.base_url)
        await client.chat.completions.create(
            model=step.model or "gpt-4o-mini",
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=1,
        )
        return True
    except Exception:
        logger.info("circuit_probe: aihub probe failed", exc_info=True)
        return False


async def _probe_zsend() -> bool:
    try:
        url = "https://api.zeabur.com/api/v1/zsend/usage"
        headers = {}
        if settings.zsend_api_key:
            headers["Authorization"] = f"Bearer {settings.zsend_api_key}"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers)
        return 200 <= resp.status_code < 300
    except Exception:
        logger.info("circuit_probe: zsend probe failed", exc_info=True)
        return False
