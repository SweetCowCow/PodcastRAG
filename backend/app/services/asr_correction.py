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
    """Return the approved, enabled correction rules applicable to an episode
    of ``show_id``.

    The applicable set is the union of every ``global`` rule and every
    ``show``-scoped rule bound to ``show_id`` that is BOTH ``status='approved'``
    AND ``enabled=true``. Pending LLM candidates (``status='pending'``,
    ``enabled=false``), rejected rules, and disabled rules are all excluded —
    asr-llm-homophone-postprocess (EQ2b) relies on this so that unreviewed
    candidates never reach the second correction layer or future episodes.
    """
    stmt = select(AsrCorrectionTerm.wrong, AsrCorrectionTerm.correct).where(
        AsrCorrectionTerm.enabled.is_(True),
        AsrCorrectionTerm.status == "approved",
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


async def _fast_dry_run_preview(
    session: "AsyncSession",
    work_units: list[tuple[UUID, list[CorrectionRule]]],
) -> BackfillReport:
    """Cheap, write-free preview for ``backfill_corrections(dry_run=True)``.

    Counts affected segments / transcripts / chunks with SQL substring matches
    rather than rebuilding every transcript's chunks. A chunk needs recompute
    exactly when its text contains a rule's ``wrong`` (literal replacement), and
    chunk text already spans overlap-neighbour segments, so the count is exact.
    The cost estimate is derived from the matched chunks' current text length.
    """
    from app.models.episode import Episode
    from app.models.transcript import Transcript
    from app.models.transcript_chunk import TranscriptChunk
    from app.models.transcript_segment import TranscriptSegment

    report = BackfillReport(dry_run=True)
    affected_transcripts: set[UUID] = set()
    total_affected_chars = 0

    for sid, rules in work_units:
        wrongs = [r.wrong for r in rules if r.wrong]
        if not wrongs:
            continue
        seg_cond = or_(
            *[TranscriptSegment.text.contains(w, autoescape=True) for w in wrongs]
        )
        seg_tids = (
            await session.execute(
                select(TranscriptSegment.transcript_id)
                .select_from(TranscriptSegment)
                .join(Transcript, TranscriptSegment.transcript_id == Transcript.id)
                .join(Episode, Transcript.episode_id == Episode.id)
                .where(Episode.show_id == sid, seg_cond)
            )
        ).scalars().all()
        report.affected_segments += len(seg_tids)
        affected_transcripts.update(seg_tids)

        chunk_cond = or_(
            *[TranscriptChunk.text.contains(w, autoescape=True) for w in wrongs]
        )
        chunk_texts = (
            await session.execute(
                select(TranscriptChunk.text)
                .select_from(TranscriptChunk)
                .join(Transcript, TranscriptChunk.transcript_id == Transcript.id)
                .join(Episode, Transcript.episode_id == Episode.id)
                .where(Episode.show_id == sid, chunk_cond)
            )
        ).scalars().all()
        report.affected_chunks += len(chunk_texts)
        total_affected_chars += sum(len(t or "") for t in chunk_texts)

    report.affected_transcripts = len(affected_transcripts)
    est_tokens = total_affected_chars * _EST_TOKENS_PER_CHAR * 2  # dual embed
    report.estimated_cost_usd = round(
        est_tokens / 1_000_000 * _EST_USD_PER_1M_EMBED_TOKENS, 6
    )
    return report


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

    # Fast preview path: counting affected rows via SQL is O(matches) instead of
    # rebuilding every transcript's chunks (which took ~95s for a 167-episode
    # show and blew the gateway timeout). A chunk's text changes iff it contains
    # a rule's ``wrong`` substring (apply_corrections is literal replace), and
    # chunk.text already includes overlap-neighbour segments — so a
    # ``chunk.text LIKE %wrong%`` count is both exact and cheap. No writes.
    if dry_run:
        return await _fast_dry_run_preview(session, work_units)

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
            # EQ2d F2 / task 2.3: content sync is independent of whether any
            # segment changed. Episodes corrected before EQ2d have corrected
            # segments but stale content; re-running backfill is a no-op on
            # segments yet content must still be brought into line. Compute the
            # corrected content and treat a content change as work on its own.
            corrected_content = apply_corrections(tr.content or "", rules)
            content_changed = corrected_content != (tr.content or "")
            if not changed_ids and not content_changed:
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

            if changed_ids:
                report.affected_transcripts += 1
            report.affected_segments += len(changed_ids)
            report.affected_chunks += len(affected)

            # EQ2d F1: snapshot original segment text once (only for segments
            # whose text actually changes and whose original_text is still NULL),
            # then write the corrected text.
            corrected_text_by_id = {cs.id: cs.text for cs in corrected}
            for s in segs:
                if s.id in changed_ids:
                    if s.original_text is None:
                        s.original_text = s.text or ""
                    s.text = corrected_text_by_id[s.id]

            # EQ2d F1/F2: snapshot original content once + sync corrected content.
            if content_changed:
                if tr.original_content is None:
                    tr.original_content = tr.content or ""
                tr.content = corrected_content

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


async def restore_episode(
    session: "AsyncSession",
    episode_id: UUID,
    *,
    embedding_cfg: "StepConfig | None" = None,
) -> BackfillReport:
    """Restore one episode's transcript to its original ASR text (EQ2d F1).

    Reverts each segment whose `original_text` is set back to that text, reverts
    `content` from `original_content`, recomputes the chunks affected by the
    reverted segments (text + dual embeddings + tsvector), then clears
    `original_text`/`original_content` so the episode returns to an uncorrected,
    no-snapshot state. An episode with no preserved original is a no-op
    (affected=0), never an error.
    """
    from app.models.episode import Episode
    from app.models.transcript import Transcript
    from app.models.transcript_chunk import TranscriptChunk
    from app.models.transcript_segment import TranscriptSegment
    from app.services import tokenizer
    from app.services.chunking import build_chunks
    from app.services.embedding import embed_texts_dual

    report = BackfillReport()

    tr = (
        await session.execute(
            select(Transcript)
            .join(Episode, Transcript.episode_id == Episode.id)
            .where(Episode.id == episode_id)
        )
    ).scalar_one_or_none()
    if tr is None:
        return report

    segs = (
        (
            await session.execute(
                select(TranscriptSegment)
                .where(TranscriptSegment.transcript_id == tr.id)
                .order_by(TranscriptSegment.start_time, TranscriptSegment.id)
            )
        )
        .scalars()
        .all()
    )

    restored_ids = {s.id for s in segs if s.original_text is not None}
    if not restored_ids and tr.original_content is None:
        return report  # nothing was ever corrected — no-op

    # Build restored-segment shims (revert to original_text where present) and
    # find chunks whose text changes back.
    restored = [
        SimpleNamespace(
            id=s.id,
            start_time=s.start_time,
            end_time=s.end_time,
            text=(s.original_text if s.original_text is not None else (s.text or "")),
        )
        for s in segs
    ]
    new_drafts = build_chunks(restored)
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

    report.affected_transcripts = 1 if (restored_ids or tr.original_content) else 0
    report.affected_segments = len(restored_ids)
    report.affected_chunks = len(affected)

    # Revert segment text + clear the snapshot.
    for s in segs:
        if s.id in restored_ids:
            s.text = s.original_text or ""
            s.original_text = None

    # Revert content + clear the snapshot.
    if tr.original_content is not None:
        tr.content = tr.original_content
        tr.original_content = None

    # Recompute affected chunks (text + dual embeddings + tsvector).
    if affected:
        if embedding_cfg is None:
            # Resolve lazily so a no-op restore (no chunks) never requires the
            # embedding step to be configured.
            from app.services.ai_step_resolver import get_step_config

            embedding_cfg = await get_step_config(session, "embedding")
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
                chunk.text_tsvector = func.to_tsvector("simple", " ".join(tokens))
            except Exception:
                logger.warning(
                    "asr restore: chunk %s recompute failed; skipping",
                    chunk.id,
                    exc_info=True,
                )
                report.failed_chunk_ids.append(str(chunk.id))

    await session.commit()
    return report
