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

MAX_CHARS = 200

# Sentence-end punctuation (CJK + ASCII). Comma is intentionally excluded so
# we don't slice mid-clause; if a single comma-only sentence overruns we fall
# through to the hard-split branch.
_SENT_SPLIT_RE = re.compile(r"([。！？!?\.]+)")


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
    """Fallback for sentences longer than MAX_CHARS: chop on whitespace, then
    raw char-window. Returns (chunk_text, start, end) tuples (absolute offsets).
    """
    out: list[tuple[str, int, int]] = []
    # First try whitespace-greedy packing
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

    # Any residual chunk still > MAX_CHARS (e.g., no whitespace at all):
    # raw char-window slice.
    final: list[tuple[str, int, int]] = []
    for chunk_text, s, e in out:
        if len(chunk_text) <= MAX_CHARS:
            final.append((chunk_text, s, e))
            continue
        for i in range(0, len(chunk_text), MAX_CHARS):
            piece = chunk_text[i : i + MAX_CHARS]
            final.append((piece, s + i, s + i + len(piece)))
    return final


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
