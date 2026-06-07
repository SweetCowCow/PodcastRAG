"""Deterministic chat-agent tool routing (b22-cross-episode-topic-routing).

`should_force_topic_prefilter` is a pure, side-effect-free, DB-free predicate
that decides whether a chat turn's user question is a cross-episode topical /
narrative question that should be deterministically routed to the
`search_with_topic_prefilter` tool on the agent's first LLM call.

Design: high precision, low recall (design D2). We would rather let some
genuine cross-episode questions fall through to `tool_choice="auto"` than
wrongly force-route a question whose golden `expected_tools` is
`search_across_episodes`. Two conditions are ANDed:

  (a) the question must NOT look episode-scoped (an explicit `EP<N>` /
      `第N集` reference or a deictic phrase like 「這集」「上一集」「該集」)
      — those belong to episode-scoped tools, not cross-episode topic search;
  (b) the question must yield ≥2 *discriminating* topic tokens, reusing
      `episode_finders.extract_topic_terms_from_question` (jieba → len≥2 →
      drop TOPIC_STOPWORDS) and then dropping show-name terms
      (`tokenizer.get_show_name_terms()`), mirroring the transcript-prefilter
      gate in `episode_finders._discriminating_tokens`.

Empty / all-stopword input yields False (fail-safe → auto).
"""

from __future__ import annotations

import re

from app.services import tokenizer
from app.services.episode_finders import extract_topic_terms_from_question

# Episode-scoped reference patterns. Matching any of these means the question
# targets a specific episode, so cross-episode topic routing must NOT fire.
#   - `EP\s*\d+`      → "EP107", "ep 134", "Ep143" (case-insensitive)
#   - `第\s*\d+\s*集`  → "第3集", "第 12 集"
#   - deictic phrases → 這集 / 那集 / 這一集 / 那一集 / 上一集 / 下一集 /
#                       前一集 / 上集 / 本集 / 該集
_EPISODE_SCOPED_RE = re.compile(
    r"EP\s*\d+"
    r"|第\s*\d+\s*集"
    r"|[這那][一]?集"
    r"|[上下前]一集"
    r"|[上本該]集",
    re.IGNORECASE,
)


def should_force_topic_prefilter(question: str) -> bool:
    """Return True iff `question` is a cross-episode topical / narrative
    question that should be force-routed to `search_with_topic_prefilter`.

    Pure function: no DB, no I/O, no mutation. See module docstring for the
    two-condition (episode-ref exclusion AND ≥2 discriminating tokens) rule.
    """
    if not question or not question.strip():
        return False

    # (a) Episode-scoped reference → not a cross-episode topical question.
    if _EPISODE_SCOPED_RE.search(question):
        return False

    # (b) ≥2 discriminating topic tokens (reuse the same extraction + show-name
    # filtering as the transcript-prefilter candidate source).
    terms = extract_topic_terms_from_question(question)
    show_terms = tokenizer.get_show_name_terms()
    discriminating = [t for t in terms if t not in show_terms]
    return len(discriminating) >= 2
