"""Episode description re-chunker (Phase 2 of r3-2-retrieval-fix).

Splits a cleaned episode description into chunks of <= MAX_CHARS each so that
short signals (bullet items / show notes lines) survive embedding instead of
being averaged out in the 1-chunk-per-episode v1 baseline.

Algorithm:
  1. Reuse `description_indexer.clean_description` to strip HTML + boilerplate.
  2. Split on paragraph boundaries (newlines). Paragraphs never merge across
     a newline — keeps the natural bullet structure of show notes.
  3. Within each paragraph, split on CJK + ASCII sentence punctuation
     (. ! ? 。 ！ ？). Sentences accumulate into a chunk until adding the
     next sentence would exceed MAX_CHARS; then we emit and start a new chunk.
  4. If a single sentence already exceeds MAX_CHARS (no punctuation in long
     run), hard-split it on whitespace, then by raw char-window as a final
     fallback.
  5. Each emitted chunk records (start_char, end_char) span in the *cleaned*
     text so downstream code can attribute back to a region for citations.

Pure function, no IO. Downstream writer (pilot_reembed_descriptions.py) is
expected to insert rows with `chunking_version=2`; that column lands via the
sibling change `chunking-version-coexistence`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.description_indexer import clean_description

MAX_CHARS = 120

# Sentence-end punctuation (CJK + ASCII). Comma is intentionally excluded so
# we don't slice mid-clause; if a single comma-only sentence overruns we fall
# through to the hard-split branch.
# r3-4 change: drop ASCII `.` from sentence boundaries because it cuts URLs
# ("https://example.com" was being split into "https://example." +
# "com/..."). CJK 句末 + ASCII !? are sufficient for description text;
# trailing-period English sentences fall through into the hard-split layer
# which packs by whitespace.
_SENT_SPLIT_RE = re.compile(r"([。！？!?]+)")


@dataclass(frozen=True)
class DescriptionChunk:
    text: str
    start_char: int  # offset into the cleaned text
    end_char: int  # exclusive


def _split_sentences(paragraph: str) -> list[tuple[str, int]]:
    """Split a paragraph into (sentence, offset_within_paragraph) pairs.

    Punctuation stays attached to the preceding sentence. Empty pieces dropped.
    """
    if not paragraph:
        return []
    parts = _SENT_SPLIT_RE.split(paragraph)
    sentences: list[tuple[str, int]] = []
    cursor = 0
    buf = ""
    buf_start = 0
    for piece in parts:
        if not piece:
            continue
        if not buf:
            buf_start = cursor
        buf += piece
        cursor += len(piece)
        if _SENT_SPLIT_RE.fullmatch(piece):
            sentences.append((buf, buf_start))
            buf = ""
    if buf:
        sentences.append((buf, buf_start))
    return sentences


def _hard_split(text: str, base_offset: int) -> list[tuple[str, int, int]]:
    """Fallback for sentences longer than MAX_CHARS: chop on whitespace.

    Returns (chunk_text, start, end) tuples (absolute offsets).

    Per r3-4 spec: URLs / hashtags / emoji clusters SHALL NOT be broken
    mid-token. We pack whitespace-delimited tokens greedily; if a single
    token itself exceeds MAX_CHARS (e.g. a long URL), it emits as its own
    chunk that intentionally overruns the limit rather than mid-token char
    slicing.
    """
    out: list[tuple[str, int, int]] = []
    tokens = re.split(r"(\s+)", text)
    buf = ""
    buf_local_start = 0
    cursor = 0
    for tok in tokens:
        if buf and len(buf) + len(tok) > MAX_CHARS:
            out.append((buf, base_offset + buf_local_start, base_offset + cursor))
            buf = ""
            buf_local_start = cursor
        if not buf:
            buf_local_start = cursor
        buf += tok
        cursor += len(tok)
    if buf.strip():
        out.append((buf, base_offset + buf_local_start, base_offset + cursor))

    # If a residual chunk still exceeds MAX_CHARS, it's because a single
    # whitespace-token (URL, emoji cluster, hashtag) is itself > MAX_CHARS.
    # Spec: keep it intact in a single chunk. Only raw char-window slice
    # when there's truly no protected token (heuristic: chunk contains no
    # URL-like / hashtag / emoji content AND no internal whitespace).
    final: list[tuple[str, int, int]] = []
    for chunk_text, s, e in out:
        if len(chunk_text) <= MAX_CHARS:
            final.append((chunk_text, s, e))
            continue
        if _contains_protected_token(chunk_text):
            # Keep intact, overrun is allowed per spec.
            final.append((chunk_text, s, e))
            continue
        # No protected tokens, no whitespace -> last-resort char window slice.
        for i in range(0, len(chunk_text), MAX_CHARS):
            piece = chunk_text[i : i + MAX_CHARS]
            final.append((piece, s + i, s + i + len(piece)))
    return final


# Tokens we refuse to break mid-token: URLs, hashtags, and emoji clusters.
_PROTECTED_TOKEN_RE = re.compile(
    r"https?://\S+"               # URLs
    r"|#\S+"                       # hashtags
    r"|[\U0001F300-\U0001FAFF☀-➿️]+"  # emoji clusters
)


def _contains_protected_token(s: str) -> bool:
    return bool(_PROTECTED_TOKEN_RE.search(s))


def rechunk_description(raw: str | None) -> list[DescriptionChunk]:
    """Clean + rechunk an episode description.

    Returns chunks of <= MAX_CHARS each, with spans into the cleaned text
    (NOT the raw HTML). Empty / whitespace-only inputs return [].
    """
    cleaned = clean_description(raw)
    if not cleaned:
        return []

    chunks: list[DescriptionChunk] = []

    paragraph_offset = 0
    for paragraph in cleaned.split("\n"):
        para_len = len(paragraph)
        if not paragraph.strip():
            paragraph_offset += para_len + 1  # +1 for the consumed '\n'
            continue

        sentences = _split_sentences(paragraph)
        buf = ""
        buf_start = -1
        buf_end = -1
        for sent, sent_local_start in sentences:
            sent_abs_start = paragraph_offset + sent_local_start
            sent_abs_end = sent_abs_start + len(sent)

            # Sentence itself exceeds MAX_CHARS -> flush + hard-split.
            if len(sent) > MAX_CHARS:
                if buf.strip():
                    chunks.append(
                        DescriptionChunk(buf.strip(), buf_start, buf_end)
                    )
                    buf = ""
                    buf_start = buf_end = -1
                for t, s, e in _hard_split(sent, sent_abs_start):
                    if t.strip():
                        chunks.append(DescriptionChunk(t.strip(), s, e))
                continue

            # Would adding this sentence exceed the limit? Flush first.
            if buf and len(buf) + len(sent) > MAX_CHARS:
                chunks.append(DescriptionChunk(buf.strip(), buf_start, buf_end))
                buf = ""
                buf_start = buf_end = -1

            if not buf:
                buf_start = sent_abs_start
            buf += sent
            buf_end = sent_abs_end

        if buf.strip():
            chunks.append(DescriptionChunk(buf.strip(), buf_start, buf_end))

        paragraph_offset += para_len + 1  # account for the '\n' separator

    return chunks
