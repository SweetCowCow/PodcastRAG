"""R2.1 section 3: tests for `app.services.citation_parser`.

Mirrors the spec scenarios under "Citation parser strips invalid refs and
degrades gracefully" plus a few defensive cases:
- valid single ref retained
- out-of-range ref stripped
- multi-ref with one invalid component drops the whole token
- empty input yields empty meta
- no brackets at all yields per-sentence empty meta
- malformed bracket content (letters / `[multi]`) gets stripped
- sentence indices line up across CJK + ASCII punctuation
"""
from __future__ import annotations

from app.services.citation_parser import parse


def test_valid_single_ref_retained():
    cleaned, meta = parse("這集播了三首[1]", num_sources=3)
    assert cleaned == "這集播了三首[1]"
    assert len(meta) == 1
    assert meta[0].sentence_index == 0
    assert meta[0].ref_ids == [1]


def test_out_of_range_ref_stripped():
    # Spec scenario: answer `這集很精彩[5]` with 3 sources → strip the token.
    cleaned, meta = parse("這集很精彩[5]", num_sources=3)
    assert cleaned == "這集很精彩"
    assert len(meta) == 1
    assert meta[0].ref_ids == []


def test_multi_ref_with_one_invalid_component_dropped():
    # Spec scenario: `他在兩集講過[1,9]` with 3 sources → drop entire token.
    cleaned, meta = parse("他在兩集講過[1,9]", num_sources=3)
    assert cleaned == "他在兩集講過"
    assert len(meta) == 1
    assert meta[0].ref_ids == []


def test_multi_ref_all_valid_kept_verbatim():
    cleaned, meta = parse("他在兩集講過[1,3]", num_sources=3)
    assert cleaned == "他在兩集講過[1,3]"
    assert meta[0].ref_ids == [1, 3]


def test_no_brackets_yields_per_sentence_empty_meta():
    # Spec scenario: pure prose with no `[N]` tokens.
    cleaned, meta = parse("第一句。第二句。第三句。", num_sources=3)
    assert cleaned == "第一句。第二句。第三句。"
    # Three sentences, each with empty ref_ids
    assert len(meta) == 3
    assert all(m.ref_ids == [] for m in meta)
    assert [m.sentence_index for m in meta] == [0, 1, 2]


def test_empty_input_yields_empty_meta():
    cleaned, meta = parse("", num_sources=3)
    assert cleaned == ""
    assert meta == []


def test_zero_sources_strips_every_ref():
    cleaned, meta = parse("這集很棒[1]，下集更好[2]", num_sources=0)
    assert cleaned == "這集很棒，下集更好"
    assert meta[0].ref_ids == []


def test_malformed_bracket_contents_dropped():
    # `[multi]` (legacy notation) and `[abc]` are not numeric → strip.
    cleaned, meta = parse("某事[multi]，另事[abc]，正常[1]", num_sources=3)
    assert cleaned == "某事，另事，正常[1]"
    # All in one sentence (no terminal punctuation in last clause).
    flat_ids: list[int] = []
    for m in meta:
        flat_ids.extend(m.ref_ids)
    assert flat_ids == [1]


def test_sentence_split_across_cjk_and_ascii_punctuation():
    cleaned, meta = parse("第一句[1]。Second sentence[2]! 第三句[3]？", num_sources=3)
    # All three valid → all three retained.
    assert cleaned == "第一句[1]。Second sentence[2]! 第三句[3]？"
    # Three sentences, one ref each.
    assert len(meta) == 3
    assert [m.ref_ids for m in meta] == [[1], [2], [3]]


def test_mixed_valid_and_invalid_in_same_sentence():
    cleaned, meta = parse("綜合說明[1][9][2]。", num_sources=3)
    # `[9]` stripped; `[1]` and `[2]` kept verbatim, in order.
    assert cleaned == "綜合說明[1][2]。"
    assert meta[0].ref_ids == [1, 2]


def test_whitespace_inside_multi_ref_tolerated():
    cleaned, meta = parse("兩來源綜合[1, 2]。", num_sources=3)
    assert cleaned == "兩來源綜合[1, 2]。"
    assert meta[0].ref_ids == [1, 2]
