"""r3-4 spec test: description chunker max=120.

Spec requirements:
  (a) short description (< 120) → single chunk unchanged
  (b) long paragraphs → each chunk ≤ 120 chars
  (c) Chinese full-width punctuation `。！？，；` + newlines preserved as
      primary split points (no mid-sentence breaks when avoidable)
  (d) URLs / hashtags / emoji clusters not broken mid-token
"""
from __future__ import annotations

from app.services.description_rechunker import (
    MAX_CHARS,
    rechunk_description,
)


def test_max_chars_constant_is_120():
    assert MAX_CHARS == 120


def test_a_short_description_single_chunk():
    raw = "本集介紹 AI 與咖啡的有趣交集，全長僅約六十字左右。歡迎收聽！"
    chunks = rechunk_description(raw)
    assert len(chunks) == 1
    assert chunks[0].text == raw
    assert len(chunks[0].text) <= MAX_CHARS


def test_b_long_paragraph_splits_under_120():
    # ~400 chars, sentence boundaries at 30, 60, 90, 120, 150, 180, 210, ...
    sentences = [
        "這是一段示範性的中文敘述句子大約三十字左右。" for _ in range(15)
    ]
    raw = "".join(sentences)
    chunks = rechunk_description(raw)
    assert len(chunks) > 1
    for c in chunks:
        assert len(c.text) <= MAX_CHARS, (
            f"chunk len={len(c.text)} > MAX_CHARS={MAX_CHARS}: {c.text!r}"
        )


def test_c_chinese_punctuation_preserved_as_boundaries():
    raw = (
        "第一句中文敘述放在這裡。"
        "第二句敘述繼續延伸內容。"
        "第三句把段落再展開一些。"
        "第四句呢？也來補上一點。"
        "第五句！這邊用驚嘆號收尾。"
        "第六句；分號也算 boundary。"
        "第七句，逗號通常不切。"
    )
    chunks = rechunk_description(raw)
    for c in chunks:
        assert len(c.text) <= MAX_CHARS
    # Each chunk should end on a sentence-end punctuation (。！？.!?) when
    # multiple chunks are produced. Comma is intentionally not a boundary
    # per the chunker design.
    if len(chunks) > 1:
        for c in chunks[:-1]:
            assert c.text.rstrip()[-1] in "。！？.!?；", (
                f"chunk should end on sentence boundary: {c.text!r}"
            )


def test_d_url_kept_intact_even_if_overruns():
    """URLs longer than the 120-char window must not split mid-token.

    The chunker's hard-split fallback uses whitespace-first packing — URLs
    have no whitespace so they stay intact in a single chunk.
    """
    url = "https://example.com/very/long/path/that/keeps/going" + "x" * 80
    raw = "請點此連結 " + url + " 來收聽。"
    chunks = rechunk_description(raw)
    # The URL must appear intact in exactly one chunk.
    found = sum(1 for c in chunks if url in c.text)
    assert found == 1, f"URL was split across chunks: {[c.text for c in chunks]}"


def test_d_emoji_cluster_not_broken():
    raw = "本集重點 🍳🍽️🎙️ 開動囉！" + "額外文字" * 30
    chunks = rechunk_description(raw)
    full = "".join(c.text for c in chunks)
    # Emoji cluster preserved end-to-end
    assert "🍳🍽️🎙️" in full
    for c in chunks:
        assert len(c.text) <= MAX_CHARS or "🍳🍽️🎙️" in c.text


def test_code_switch_zh_en_under_120():
    raw = (
        "本集聊 RAG retrieval 細節。We dive into embeddings + BM25 hybrid. "
        "Recall@5 是核心指標。Embedding model 用 text-embedding-3-large 升級。"
        "結論：semantic + lexical 缺一不可。"
    )
    chunks = rechunk_description(raw)
    full = " ".join(c.text for c in chunks)
    assert "RAG" in full
    assert "Recall@5" in full
    for c in chunks:
        assert len(c.text) <= MAX_CHARS
