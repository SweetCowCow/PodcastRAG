"""Shared FastAPI dependencies for app.api endpoints."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from fastapi import Depends, Request

from app.core.security import require_authenticated_user
from app.models.user import User, UserRole

logger = logging.getLogger(__name__)


_EVAL_HEADER_RUN_ID = "X-Eval-Run-Id"
_EVAL_HEADER_ITEM_ID = "X-Eval-Item-Id"
_EVAL_HEADER_TURN_IDX = "X-Eval-Turn-Idx"


async def bind_eval_context(
    request: Request,
    user: User = Depends(require_authenticated_user),
) -> AsyncIterator[None]:
    """Bind eval-runner ContextVar from admin-issued X-Eval-* headers.

    Activates set_eval_context() only when all hold:
      1. authenticated user.role == admin
      2. all three X-Eval-* headers present and non-empty
      3. X-Eval-Turn-Idx parses as non-negative int

    Otherwise yield without touching the ContextVar (silent skip — never 4xx).
    """
    from eval.tracing.langfuse_setup import (
        reset_eval_context,
        set_eval_context,
    )

    run_id = (request.headers.get(_EVAL_HEADER_RUN_ID) or "").strip()
    item_id = (request.headers.get(_EVAL_HEADER_ITEM_ID) or "").strip()
    raw_turn_idx = (request.headers.get(_EVAL_HEADER_TURN_IDX) or "").strip()

    bound = False
    if (
        user.role == UserRole.admin.value
        and run_id
        and item_id
        and raw_turn_idx
    ):
        try:
            turn_idx = int(raw_turn_idx)
        except ValueError:
            turn_idx = -1
        if turn_idx >= 0:
            try:
                set_eval_context(
                    run_id=run_id, item_id=item_id, turn_idx=turn_idx
                )
                bound = True
            except Exception:  # noqa: BLE001 — fail-safe per design Decision 7
                logger.warning(
                    "bind_eval_context: set_eval_context raised — skipping",
                    exc_info=True,
                )

    try:
        yield
    finally:
        if bound:
            try:
                reset_eval_context()
            except Exception:  # noqa: BLE001
                logger.warning(
                    "bind_eval_context: reset_eval_context raised",
                    exc_info=True,
                )
