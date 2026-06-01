"""Deterministic ASR typo correction dictionary.

Part of change `asr-correction-dictionary` (EQ2a). Rules map a literal `wrong`
string to a `correct` string, scoped global or per-show. Applied at
transcription time (before chunking) and via admin-triggered backfill so that
both the displayed transcript and the search index carry the corrected text.

Matching is literal whole-string substring replacement — NOT regex — so that
behaviour is deterministic and admin-controllable. Fuzzy / homophone matching
is intentionally out of scope here (that is EQ2b).
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import and_, func, or_, select

from app.models.asr_correction_term import AsrCorrectionTerm

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.services.ai_step_resolver import StepConfig

logger = logging.getLogger(__name__)

# Embedding cost estimate for the dry-run preview. Rough by design (label it an
# estimate to the operator; the provider bill is the source of truth): dual
# embedding = legacy small (~$0.02/1M) + v2 large (~$0.13/1M) ≈ $0.15/1M tokens.
_EST_USD_PER_1M_EMBED_TOKENS = 0.15
_EST_TOKENS_PER_CHAR = 1.0  # Chinese rough heuristic: 1 char ≈ 1 token


@dataclass(frozen=True)
class CorrectionRule:
    """A single wrong→correct replacement, decoupled from the ORM row so it is
    safe to carry across sessions and trivially unit-testable."""

    wrong: str
    correct: str


@dataclass
class BackfillReport:
    """Outcome of a backfill run (or dry-run preview)."""

    affected_transcripts: int = 0
    affected_segments: int = 0
    affected_chunks: int = 0
    estimated_cost_usd: float = 0.0
    failed_chunk_ids: list[str] = field(default_factory=list)
    dry_run: bool = False


async def load_rules(
    session: "AsyncSession", show_id: UUID | None
) -> list[CorrectionRule]:
    """Return the enabled correction rules applicable to an episode of ``show_id``.

    The applicable set is the union of every enabled ``global`` rule and every
    enabled ``show``-scoped rule bound to ``show_id``. Disabled rules are
    excluded.
    """
    stmt = select(AsrCorrectionTerm.wrong, AsrCorrectionTerm.correct).where(
        AsrCorrectionTerm.enabled.is_(True),
        or_(
            AsrCorrectionTerm.scope == "global",
            and_(
                AsrCorrectionTerm.scope == "show",
                AsrCorrectionTerm.show_id == show_id,
            ),
        ),
    )
    rows = (await session.execute(stmt)).all()
    return [CorrectionRule(wrong=w, correct=c) for w, c in rows]


def apply_corrections(text: str, rules: list[CorrectionRule]) -> str:
    """Apply literal whole-string replacements to ``text``.

    Each rule's ``wrong`` is matched as a literal substring (regex
    metacharacters are treated literally) and every occurrence is replaced with
    ``correct``. Rules are applied longest-``wrong``-first so that a shorter
    ``wrong`` that is a substring of a longer one cannot pre-empt the longer
    match.
    """
    if not text or not rules:
        return text
    for rule in sorted(rules, key=lambda r: len(r.wrong), reverse=True):
        if rule.wrong:
            text = text.replace(rule.wrong, rule.correct)
    return text


async def _resolve_work_units(
    session: "AsyncSession", *, show_id: UUID | None, term_id: UUID | None
) -> list[tuple[UUID, list[CorrectionRule]]]:
    """Resolve which (show_id, rules) units a backfill covers.

    - ``term_id`` given: use only that one rule. A global term covers every
      show; a show term covers only its bound show.
    - ``show_id`` given: that show, using its full applicable rule set.
    - neither: every show, each using its own applicable rule set.
    """
    from app.models.show import Show

    if term_id is not None:
        term = await session.get(AsrCorrectionTerm, term_id)
        if term is None or not term.enabled:
            return []
        rule = [CorrectionRule(term.wrong, term.correct)]
        if term.scope == "global":
            sids = (await session.execute(select(Show.id))).scalars().all()
            return [(sid, rule) for sid in sids]
        return [(term.show_id, rule)] if term.show_id is not None else []

    if show_id is not None:
        return [(show_id, await load_rules(session, show_id))]

    sids = (await session.execute(select(Show.id))).scalars().all()
    return [(sid, await load_rules(session, sid)) for sid in sids]


async def backfill_corrections(
    session: "AsyncSession",
    *,
    show_id: UUID | None = None,
    term_id: UUID | None = None,
    dry_run: bool = False,
    embedding_cfg: "StepConfig | None" = None,
) -> BackfillReport:
    """Apply correction rules to existing transcripts and recompute the
    affected chunks (text + dual embeddings + tsvector).

    Affected chunks are found by re-running ``build_chunks`` on the corrected
    segments and diffing chunk ``text`` per ``chunk_index`` — this captures
    overlap-neighbour chunks that a plain ``segment_ids`` lookup would miss
    (chunk text includes adjacent overlap segments).

    Idempotent: a second run over already-corrected text is a no-op (the
    ``wrong`` string is gone, so nothing changes). Progress commits per
    transcript so an interrupted run resumes safely. A per-chunk recompute
    failure is recorded in ``failed_chunk_ids`` and skipped without aborting.

    ``dry_run=True`` performs no writes; it returns the affected counts plus an
    ``estimated_cost_usd`` for the embeddings that a real run would recompute.
    """
    from app.models.episode import Episode
    from app.models.transcript import Transcript
    from app.models.transcript_chunk import TranscriptChunk
    from app.models.transcript_segment import TranscriptSegment
    from app.services import tokenizer
    from app.services.chunking import build_chunks
    from app.services.embedding import embed_texts_dual

    report = BackfillReport(dry_run=dry_run)
    total_affected_chars = 0
    work_units = await _resolve_work_units(
        session, show_id=show_id, term_id=term_id
    )

    for sid, rules in work_units:
        if not rules:
            continue
        transcripts = (
            (
                await session.execute(
                    select(Transcript)
                    .join(Episode, Transcript.episode_id == Episode.id)
                    .where(Episode.show_id == sid)
                )
            )
            .scalars()
            .all()
        )
        for tr in transcripts:
            segs = (
                (
                    await session.execute(
                        select(TranscriptSegment)
                        .where(TranscriptSegment.transcript_id == tr.id)
                        .order_by(
                            TranscriptSegment.start_time, TranscriptSegment.id
                        )
                    )
                )
                .scalars()
                .all()
            )
            if not segs:
                continue

            # Build corrected shims (do NOT mutate ORM rows yet — keeps dry-run
            # read-only and lets us diff against the originals).
            corrected = [
                SimpleNamespace(
                    id=s.id,
                    start_time=s.start_time,
                    end_time=s.end_time,
                    text=apply_corrections(s.text or "", rules),
                )
                for s in segs
            ]
            changed_ids = {
                cs.id
                for cs, s in zip(corrected, segs)
                if cs.text != (s.text or "")
            }
            if not changed_ids:
                continue

            new_drafts = build_chunks(corrected)
            existing = (
                (
                    await session.execute(
                        select(TranscriptChunk)
                        .where(TranscriptChunk.transcript_id == tr.id)
                        .order_by(TranscriptChunk.chunk_index)
                    )
                )
                .scalars()
                .all()
            )
            by_idx = {c.chunk_index: c for c in existing}
            affected: list[tuple[TranscriptChunk, str]] = []
            for idx, draft in enumerate(new_drafts):
                chunk = by_idx.get(idx)
                if chunk is not None and chunk.text != draft.text:
                    affected.append((chunk, draft.text))

            report.affected_transcripts += 1
            report.affected_segments += len(changed_ids)
            report.affected_chunks += len(affected)

            if dry_run:
                total_affected_chars += sum(len(t) for _, t in affected)
                continue

            # Write path: commit corrected segment text.
            corrected_text_by_id = {cs.id: cs.text for cs in corrected}
            for s in segs:
                if s.id in changed_ids:
                    s.text = corrected_text_by_id[s.id]

            if affected:
                texts = [t for _, t in affected]
                legacy_vecs, v2_vecs = await asyncio.to_thread(
                    embed_texts_dual, texts, embedding_cfg
                )
                await tokenizer.load_dictionary(session)
                for i, (chunk, new_text) in enumerate(affected):
                    try:
                        chunk.text = new_text
                        chunk.embedding = legacy_vecs[i] if legacy_vecs else None
                        chunk.embedding_v2 = v2_vecs[i] if v2_vecs else None
                        tokens = tokenizer.tokenize(new_text)
                        chunk.text_tsvector = func.to_tsvector(
                            "simple", " ".join(tokens)
                        )
                    except Exception:
                        logger.warning(
                            "asr backfill: chunk %s recompute failed; skipping",
                            chunk.id,
                            exc_info=True,
                        )
                        report.failed_chunk_ids.append(str(chunk.id))

            # Commit per transcript so an interrupted run resumes from here.
            await session.commit()

    if dry_run:
        est_tokens = total_affected_chars * _EST_TOKENS_PER_CHAR * 2  # dual
        report.estimated_cost_usd = round(
            est_tokens / 1_000_000 * _EST_USD_PER_1M_EMBED_TOKENS, 6
        )
    return report
