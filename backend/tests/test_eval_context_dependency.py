"""Unit tests for app.api.deps.bind_eval_context.

Covers the four scenarios in eval-observability spec:
  - admin + complete headers → set + reset
  - non-admin + complete headers → no-op
  - admin + missing header → no-op
  - admin + malformed turn_idx → no-op
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.api.deps import bind_eval_context
from app.models.user import UserRole
from eval.tracing.langfuse_setup import get_eval_context, reset_eval_context


def _make_request(headers: dict[str, str]) -> SimpleNamespace:
    return SimpleNamespace(headers=headers)


def _make_user(role: str) -> SimpleNamespace:
    return SimpleNamespace(role=role)


@pytest.fixture(autouse=True)
def _clean_ctx():
    reset_eval_context()
    yield
    reset_eval_context()


@pytest.mark.asyncio
async def test_admin_with_complete_headers_sets_then_resets():
    request = _make_request(
        {
            "X-Eval-Run-Id": "eval-X",
            "X-Eval-Item-Id": "b20",
            "X-Eval-Turn-Idx": "0",
        }
    )
    user = _make_user(UserRole.admin.value)

    gen = bind_eval_context(request, user)
    await gen.__anext__()
    assert get_eval_context() == {
        "run_id": "eval-X",
        "item_id": "b20",
        "turn_idx": 0,
    }

    with pytest.raises(StopAsyncIteration):
        await gen.__anext__()
    assert get_eval_context() is None


@pytest.mark.asyncio
async def test_non_admin_with_complete_headers_does_not_bind():
    request = _make_request(
        {
            "X-Eval-Run-Id": "eval-X",
            "X-Eval-Item-Id": "b20",
            "X-Eval-Turn-Idx": "0",
        }
    )
    user = _make_user(UserRole.member.value)

    gen = bind_eval_context(request, user)
    await gen.__anext__()
    assert get_eval_context() is None

    with pytest.raises(StopAsyncIteration):
        await gen.__anext__()
    assert get_eval_context() is None


@pytest.mark.asyncio
async def test_admin_with_missing_header_does_not_bind():
    request = _make_request(
        {
            "X-Eval-Run-Id": "eval-X",
            # X-Eval-Item-Id missing
            "X-Eval-Turn-Idx": "0",
        }
    )
    user = _make_user(UserRole.admin.value)

    gen = bind_eval_context(request, user)
    await gen.__anext__()
    assert get_eval_context() is None

    with pytest.raises(StopAsyncIteration):
        await gen.__anext__()
    assert get_eval_context() is None


@pytest.mark.asyncio
async def test_admin_with_malformed_turn_idx_does_not_bind():
    request = _make_request(
        {
            "X-Eval-Run-Id": "eval-X",
            "X-Eval-Item-Id": "b20",
            "X-Eval-Turn-Idx": "not-a-number",
        }
    )
    user = _make_user(UserRole.admin.value)

    gen = bind_eval_context(request, user)
    await gen.__anext__()
    assert get_eval_context() is None

    with pytest.raises(StopAsyncIteration):
        await gen.__anext__()
    assert get_eval_context() is None


@pytest.mark.asyncio
async def test_admin_with_negative_turn_idx_does_not_bind():
    request = _make_request(
        {
            "X-Eval-Run-Id": "eval-X",
            "X-Eval-Item-Id": "b20",
            "X-Eval-Turn-Idx": "-1",
        }
    )
    user = _make_user(UserRole.admin.value)

    gen = bind_eval_context(request, user)
    await gen.__anext__()
    assert get_eval_context() is None

    with pytest.raises(StopAsyncIteration):
        await gen.__anext__()
    assert get_eval_context() is None
