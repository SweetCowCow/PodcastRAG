"""Shared Celery hooks for task failure logging + circuit-breaker entry check.

Part of `task-failure-monitoring-and-circuit-breaker`. Provides:

- ``record_task_failure(task_name, args, exc, provider_id, retry_count)``:
  sync wrapper that runs ``failure_log.write_failure_log`` in a fresh
  asyncio loop. Safe to call from Celery ``Task.on_failure`` (which is
  synchronous).

- ``check_circuit_or_retry(task, provider_id)``: sync helper for task
  entry. If the provider's circuit is open, increments paused_task_count
  and raises ``task.retry(countdown=300, max_retries=None)``. Otherwise
  no-ops.

- ``classify_and_short_circuit(task, exc, task_name, args, provider_id)``:
  unified except-handler helper. If ``exc`` is classified permanent,
  writes a failure-log row and returns True (caller should re-raise
  without calling ``self.retry``). If transient, returns False (caller
  falls through to existing ``autoretry_for`` behaviour).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.services import circuit_breaker, error_classifier
from app.services.failure_log import write_failure_log

logger = logging.getLogger(__name__)


def _run_async(coro):
    """Run an async coroutine in a private event loop.

    Celery's prefork worker process may or may not have a running loop;
    the safest approach is to create a private one each call (same
    pattern the existing tasks.py / topic_task.py / summary_task.py use
    via ``asyncio.run(...)``).
    """
    try:
        return asyncio.run(coro)
    except RuntimeError:
        # If an event loop is already running (e.g. tests), create
        # a separate loop for the call.
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


def record_task_failure(
    task_name: str,
    args: Any,
    exc: BaseException,
    provider_id: str | None = None,
    retry_count: int = 0,
) -> None:
    """Synchronously write one row to ``task_failure_log``."""
    try:
        _run_async(
            write_failure_log(
                task_name=task_name,
                args=args,
                exc=exc,
                provider_id=provider_id,
                retry_count=retry_count,
            )
        )
    except Exception:
        logger.exception(
            "failure_hooks.record_task_failure raised for task=%s", task_name
        )


def check_circuit_or_retry(task, provider_id: str) -> None:
    """Entry hook: pause task via ``task.retry`` if provider's breaker is open.

    No-op if circuit is closed. Increments ``paused_task_count`` first
    so admin UI sees the pause volume.
    """
    try:
        is_open = _run_async(circuit_breaker.is_open(provider_id))
    except Exception:
        logger.exception(
            "failure_hooks.check_circuit_or_retry: is_open lookup failed for %s",
            provider_id,
        )
        return
    if not is_open:
        return
    try:
        _run_async(circuit_breaker.increment_paused(provider_id))
    except Exception:
        logger.exception(
            "failure_hooks.check_circuit_or_retry: increment_paused failed"
        )
    logger.warning(
        "circuit_breaker: %s is OPEN — task %s self-retrying in 300s",
        provider_id,
        getattr(task, "name", "?"),
    )
    raise task.retry(countdown=300, max_retries=None)


def classify_and_short_circuit(
    task,
    exc: BaseException,
    task_name: str,
    args: Any,
    provider_id: str | None,
) -> bool:
    """If ``exc`` is permanent, log + return True (caller re-raises).

    For transient/unknown returns False (caller does nothing special;
    Celery's existing ``autoretry_for`` handles retry).
    """
    verdict = error_classifier.classify(exc)
    if verdict != "permanent":
        return False
    record_task_failure(
        task_name=task_name,
        args=args,
        exc=exc,
        provider_id=provider_id,
        retry_count=int(getattr(getattr(task, "request", None), "retries", 0) or 0),
    )
    # Tag exception so the base Task.on_failure won't double-write it.
    try:
        setattr(exc, "_failure_logged", True)
    except Exception:
        pass
    return True


def record_task_failure_unless_logged(
    task_name: str,
    args: Any,
    exc: BaseException,
    provider_id: str | None = None,
    retry_count: int = 0,
) -> None:
    """Wrapper used by base ``Task.on_failure`` — skips if already logged.

    Avoids double-writing when the task's own except block already
    short-circuited a permanent error via ``classify_and_short_circuit``.
    """
    if getattr(exc, "_failure_logged", False):
        return
    record_task_failure(
        task_name=task_name,
        args=args,
        exc=exc,
        provider_id=provider_id,
        retry_count=retry_count,
    )
