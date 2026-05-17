"""Unit tests for `_unwrap_self_referential_json` in `app.services.rag`.

Covers the R2.1 RCA finding (fix-eval-dataset-com-004-json-leak): the LLM
occasionally returns the answer field as a JSON-wrapped string and the judge
ends up scoring metadata instead of prose.
"""

from app.services.rag import _unwrap_self_referential_json


def test_pure_text_unchanged():
    """Plain prose answer must pass through untouched (no false unwrap)."""
    text = "這集播了三首歌"
    assert _unwrap_self_referential_json(text) == text


def test_json_wrapped_unwraps():
    """A self-referential `{"answer":"..."}` wrapper must be peeled."""
    wrapped = '{"answer":"這集播了三首歌"}'
    assert _unwrap_self_referential_json(wrapped) == "這集播了三首歌"


def test_json_no_answer_key_unchanged():
    """JSON that doesn't carry an `answer` field must stay as-is."""
    payload = '{"meta":"x"}'
    assert _unwrap_self_referential_json(payload) == payload
