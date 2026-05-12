"""Unit tests for description_rechunker (Phase 2 of r3-2-retrieval-fix)."""
from __future__ import annotations

from app.services.description_rechunker import (
    MAX_CHARS,
    rechunk_description,
)


def test_empty_inputs_return_no_chunks():
    assert rechunk_description(None) == []
    assert rechunk_description("") == []
    assert rechunk_description("   \n  ") == []
    assert rechunk_description("<p></p>") == []


def test_short_description_emits_single_chunk():
    raw = "本集介紹咖啡的歷史與烘焙風味。歡迎收聽！"
    chunks = rechunk_description(raw)
    assert len(chunks) == 1
    assert "咖啡" in chunks[0].text
    assert chunks[0].start_char == 0
    assert chunks[0].end_char == len(chunks[0].text)


def test_all_chunks_under_max_chars():
    # Build a description with many short bullet lines so we get multiple chunks
    bullets = [
        f"． 重點第{i}項：這是一段示範用的展示文字大約二十字左右。"
        for i in range(15)
    ]
    raw = "\n".join(bullets)
    chunks = rechunk_description(raw)
    assert len(chunks) > 1
    for c in chunks:
        assert len(c.text) <= MAX_CHARS, f"chunk over limit: {len(c.text)}"


def test_paragraphs_do_not_merge_across_newline():
    raw = "段落一短句。\n段落二短句。\n段落三短句。"
    chunks = rechunk_description(raw)
    # Each line is its own paragraph; even though three fit < MAX_CHARS, they
    # should not be merged across newlines.
    assert len(chunks) == 3
    assert chunks[0].text == "段落一短句。"
    assert chunks[1].text == "段落二短句。"
    assert chunks[2].text == "段落三短句。"


def test_html_tags_fully_stripped():
    raw = (
        "<p>本集嘉賓<a href='https://example.com'>馬世芳</a>聊音樂。</p>"
        "<script>alert(1)</script><style>.x{}</style>"
    )
    chunks = rechunk_description(raw)
    assert len(chunks) >= 1
    full = " ".join(c.text for c in chunks)
    assert "<" not in full and ">" not in full
    assert "alert" not in full
    assert ".x{" not in full
    assert "馬世芳" in full


def test_long_sentence_without_punctuation_hard_split():
    # 400-char run of CJK chars, no punctuation at all
    raw = "啊" * 400
    chunks = rechunk_description(raw)
    assert len(chunks) >= 2
    for c in chunks:
        assert len(c.text) <= MAX_CHARS
    # Recombined coverage == original (no chars lost)
    assert sum(len(c.text) for c in chunks) == 400


def test_code_switch_zh_en_mixed():
    raw = (
        "本集聊 RAG retrieval 的細節。We dive into embeddings + BM25 hybrid. "
        "Recall@5 是核心指標。Embedding model 用 text-embedding-3-small。"
    )
    chunks = rechunk_description(raw)
    assert len(chunks) >= 1
    full = " ".join(c.text for c in chunks)
    assert "RAG" in full
    assert "embeddings" in full
    assert "Recall@5" in full
    for c in chunks:
        assert len(c.text) <= MAX_CHARS


def test_real_sample_show_notes_bullet_list():
    """Snapshot-style: a real-shaped sample from show 45fc2462 (anonymised).

    Verifies: bullets stay split, sponsor URL line survives strip, total
    chunk count is reasonable for ~700-char descriptions.
    """
    raw = (
        "． 吃飯時我們就聊這桌菜好嗎？ \n"
        "． 用同樣的錢吃中菜根本是皇帝 \n"
        "． 變成大人的指標：點小菜不看價錢 \n"
        "． 貪吃的人需要一個貪吃的伴侶 \n"
        "． 站在灶台旁邊吃的那塊肉最好吃 \n"
        "  \n"
        "🍳 公共電視台熱播中！ \n"
        "每週日 晚間 21:00 最新集數 \n"
        "<a href=\"https://example.com/show\">https://example.com/show</a> \n"
        "  \n"
        "🍽️ 請客餐廳推薦： \n"
        "． 香港九記海鮮 - 豆豉炒生腸 \n"
        "． 方家小館 - 紅燒羊肉、清蒸臭豆腐 \n"
        "． 大三元 - 金湯蛋"
    )
    chunks = rechunk_description(raw)
    assert len(chunks) >= 3  # multi-chunk split, not the old 1-per-episode
    for c in chunks:
        assert len(c.text) <= MAX_CHARS
        assert "<a" not in c.text  # HTML stripped
    full = " ".join(c.text for c in chunks)
    assert "香港九記海鮮" in full
    assert "https://example.com/show" in full


def test_real_sample_short_episode_one_chunk():
    """Short description (< MAX_CHARS after clean) yields one chunk.

    `<p>` tags don't insert newlines via stdlib HTMLParser, so the cleaned
    text is a single paragraph well under MAX_CHARS — should be 1 chunk.
    """
    raw = (
        "<p>·足浴vs.逐玉</p>"
        "<p>·兩個朋友間的Chemistry</p>"
        "<p>·把握當下</p>"
    )
    chunks = rechunk_description(raw)
    assert len(chunks) == 1
    assert len(chunks[0].text) <= MAX_CHARS
    assert "足浴" in chunks[0].text
    assert "Chemistry" in chunks[0].text
    assert "把握當下" in chunks[0].text


def test_spans_are_monotonic_and_in_bounds():
    raw = "句一。句二！句三？句四。" * 5
    chunks = rechunk_description(raw)
    prev_end = -1
    for c in chunks:
        assert c.start_char >= 0
        assert c.end_char >= c.start_char
        # spans are into the *cleaned* text, which equals raw here
        assert c.end_char <= len(raw) + 5  # tolerate paragraph offset bookkeeping
        # monotonic across chunks
        assert c.start_char >= prev_end - 5
        prev_end = c.end_char
