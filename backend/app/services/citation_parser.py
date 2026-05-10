"""R2.1 Decision 4 (the strip half): parse `[N]` / `[N,M,...]` ref tokens.

Given the raw answer string returned by the LLM and the count `N` of
sources the model was shown, this module:

1. Locates every bracketed reference token of the form `[K]` or `[K,M,...]`.
2. Keeps tokens whose every numeric component lies in `1..N`; drops the
   entire token (brackets included) when any component is out of range or
   when the token is malformed (non-numeric content inside).
3. Returns a `(cleaned_answer, citations_meta)` tuple where
   `citations_meta` is a list of `{sentence_index, ref_ids: [...]}` entries
   produced by splitting the *original* answer text on `。 ！ ？ . ! ?` and
   collecting the valid refs that appeared inside each sentence.

The frontend can render source cards purely from `used_chunk_ids` /
`citations`, so even when the LLM ignores the citation contract entirely
the UI still degrades gracefully (Decision 4: 後端嚴格 strip + UI 不依賴
inline ref).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Sentence boundaries per spec scenario "No bracketed refs at all yields
# empty meta". Matches both fullwidth CJK punctuation and ASCII.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？.!?])")

# A bracket token is `[<contents>]` where `<contents>` is one-or-more
# digit groups separated by commas, with optional whitespace around commas.
# Anything else inside the brackets (letters, multi, slashes) makes the
# token invalid → we still drop it from the answer text.
_BRACKET_RE = re.compile(r"\[([^\]]*)\]")
_NUMERIC_TOKEN_RE = re.compile(r"^\s*\d+(?:\s*,\s*\d+)*\s*$")


@dataclass
class SentenceCitation:
    sentence_index: int
    ref_ids: list[int]


def _parse_token_contents(contents: str, num_sources: int) -> list[int] | None:
    """Return the list of valid 1..N ref ids inside one bracket token.

    Returns None when the token is invalid (non-numeric, out-of-range, or
    empty), signalling the caller to drop the entire `[...]` from the
    answer text.
    """
    if not _NUMERIC_TOKEN_RE.match(contents):
        return None
    parts = [p.strip() for p in contents.split(",")]
    ids: list[int] = []
    for p in parts:
        try:
            n = int(p)
        except ValueError:
            return None
        if n < 1 or n > num_sources:
            return None
        ids.append(n)
    return ids


def _split_sentences(text: str) -> list[str]:
    """Split on sentence-final punctuation, keeping the punctuation attached.

    Always returns at least one entry (the input itself) so callers can
    safely index into the result.
    """
    if not text:
        return [""]
    parts = [p for p in _SENTENCE_SPLIT_RE.split(text) if p != ""]
    return parts or [text]


def parse(answer_text: str, num_sources: int) -> tuple[str, list[SentenceCitation]]:
    """Strip invalid bracket refs from `answer_text` and emit per-sentence meta.

    Per spec:
    - Tokens with every component in `1..num_sources` are RETAINED verbatim
      in the cleaned answer.
    - Tokens with any out-of-range or non-numeric component are REMOVED
      entirely (brackets included).
    - `citations_meta` maps each sentence's 0-based index to the list of
      valid `ref_ids` that appeared inside it (kept tokens contribute their
      ids; stripped tokens contribute nothing).

    `num_sources <= 0` means there were no retrievable sources — every
    bracket token is by definition out-of-range and gets stripped.
    """
    if not answer_text:
        return "", []

    # Per-sentence walk. We split first, then run the bracket replacement
    # *per sentence* so the sentence_index lines up with the surviving text.
    raw_sentences = _split_sentences(answer_text)
    cleaned_sentences: list[str] = []
    meta: list[SentenceCitation] = []

    for idx, sentence in enumerate(raw_sentences):
        kept_ids: list[int] = []

        def _replace(m: re.Match[str]) -> str:
            contents = m.group(1)
            ids = _parse_token_contents(contents, num_sources)
            if ids is None:
                # Strip the whole `[...]` token, including brackets.
                return ""
            kept_ids.extend(ids)
            return m.group(0)  # keep verbatim

        cleaned = _BRACKET_RE.sub(_replace, sentence)
        cleaned_sentences.append(cleaned)
        meta.append(SentenceCitation(sentence_index=idx, ref_ids=kept_ids))

    cleaned_answer = "".join(cleaned_sentences)
    return cleaned_answer, meta
