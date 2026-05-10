"""R2.1-fix Fix 1: tests for `app.services.rag.strip_citations`.

The helper is intentionally aggressive: it removes every `[N]` /
`[N,M,...]` token regardless of whether the numeric components are in
range. Eval / judge consumers never see the inline noise; the API path
keeps `citation_parser.parse` for the frontend.
"""
from __future__ import annotations

from app.services.rag import strip_citations


def test_empty_returns_empty():
    assert strip_citations("") == ""
    assert strip_citations(None) == ""  # type: ignore[arg-type]


def test_strips_single_ref_at_sentence_end():
    assert strip_citations("這集播了三首[1]。") == "這集播了三首。"


def test_strips_multi_ref():
    assert strip_citations("他在 EP1 與 EP134 都聊過[1,3]") == "他在 EP1 與 EP134 都聊過"


def test_strips_multi_ref_with_spaces():
    assert strip_citations("a[1, 2, 3]b") == "ab"


def test_strips_preceding_whitespace():
    # Spec: token regex eats leading spaces so "foo [1]" → "foo" not "foo ".
    assert strip_citations("foo [1]") == "foo"


def test_keeps_non_numeric_brackets():
    # `[multi]` / `[?]` are out of scope — they survive.
    assert strip_citations("see [multi]") == "see [multi]"


def test_idempotent():
    once = strip_citations("a[1] b[2,3] c[4].")
    assert once == strip_citations(once)


def test_handles_multiple_refs_per_string():
    raw = "迪拉胖在訪談中提到[1]。陳零九講過這句話[2,3]。"
    assert strip_citations(raw) == "迪拉胖在訪談中提到。陳零九講過這句話。"


def test_keeps_text_when_no_refs():
    s = "節目名來自迪拉的口頭禪。"
    assert strip_citations(s) == s
