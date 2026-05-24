"""Unit tests for `find_by_ref` word-boundary matching (replaces the
substring ILIKE that caused `find_episode_by_ref(ref='EP1')` to return
EP146 in prod 2026-05-24).

Spec: chat-agentic-routing#find_episode_by_ref SHALL match episode
references on word boundaries.
"""

from __future__ import annotations

import re
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import episode_finders


def _pg_word_boundary_regex(n: str) -> re.Pattern:
    """Python mirror of the PG ~* pattern used in _BY_REF_EP_NUMBER_SQL.

    PG pattern (case-insensitive POSIX):
        (^|[^0-9A-Za-z])(?:EP|第)\\s*<n>(?:集)?($|[^0-9])
    """
    return re.compile(
        rf"(^|[^0-9A-Za-z])(?:EP|第)\s*{n}(?:集)?($|[^0-9])",
        re.IGNORECASE,
    )


@pytest.mark.parametrize(
    "title,n,should_match",
    [
        # b27 regression: EP1 query must NOT match EP146 / EP10 / EP100
        ("EP146｜你們是不是怕沒話聊？Ft. 9m88", "1", False),
        ("EP10｜什麼集", "1", False),
        ("EP100｜其他集", "1", False),
        # EP1 query DOES match real EP1
        ("EP1｜開播", "1", True),
        ("ep1｜小寫版", "1", True),
        # Chinese 第N集 form
        ("第1集｜開播", "1", True),
        ("第10集｜其他", "1", False),
        # EP10 query: matches EP10 but not EP100
        ("EP10｜什麼集", "10", True),
        ("EP100｜其他集", "10", False),
        # Whitespace tolerance
        ("EP 1｜開播", "1", True),
        # No EP marker
        ("某集標題沒 EP 號碼", "1", False),
    ],
)
def test_word_boundary_regex_matches(title: str, n: str, should_match: bool):
    pat = _pg_word_boundary_regex(n)
    assert bool(pat.search(title)) is should_match, (
        f"title={title!r} n={n} expected={should_match}"
    )


def test_sql_uses_word_boundary_pattern():
    """The SQL must use ~* word-boundary regex, not ILIKE substring."""
    sql = episode_finders._BY_REF_EP_NUMBER_SQL
    assert "ILIKE" not in sql, "find_by_ref must not use ILIKE (substring) anymore"
    assert "~*" in sql, "find_by_ref must use ~* POSIX regex"
    assert ":n" in sql, "SQL must bind episode number via :n param"
    # word-boundary anchors present
    assert "[^0-9A-Za-z]" in sql or "[^0-9]" in sql


@pytest.mark.asyncio
async def test_find_by_ref_binds_n_param_only():
    """find_by_ref must call execute with params dict containing exactly
    show_id + n (not the legacy 3 ILIKE token bag)."""
    db = MagicMock()
    db.execute = AsyncMock()
    # mappings().first() returns None → fallback to title ILIKE branch
    mappings_result = MagicMock()
    mappings_result.first.return_value = None
    execute_result = MagicMock()
    execute_result.mappings.return_value = mappings_result
    db.execute.return_value = execute_result

    show_id = uuid.uuid4()
    await episode_finders.find_by_ref(db, show_id, "EP1")
    # First call = EP-number SQL with new params shape
    first_call_args = db.execute.call_args_list[0]
    sql_compiled = first_call_args.args[0]
    params = first_call_args.args[1]
    assert "~*" in str(sql_compiled), "first execute should use word-boundary SQL"
    assert set(params.keys()) == {"show_id", "n"}, f"unexpected params: {set(params.keys())}"
    assert params["n"] == "1"


@pytest.mark.asyncio
async def test_find_by_ref_returns_none_for_empty():
    db = MagicMock()
    db.execute = AsyncMock()
    result = await episode_finders.find_by_ref(db, uuid.uuid4(), "")
    assert result is None
    db.execute.assert_not_called()
    result = await episode_finders.find_by_ref(db, uuid.uuid4(), "   ")
    assert result is None
