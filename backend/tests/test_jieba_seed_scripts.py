"""Smoke tests for the jieba seed-dict scripts.

The build script needs a real DB to run end-to-end; these tests focus on
the import script (CSV → DB) which can be exercised with a small fixture
CSV. Build-script behaviour is covered by a unit-style assertion on its
ordering helper.
"""
from __future__ import annotations

import csv
from pathlib import Path

import pytest
from sqlalchemy import delete, select

from app.models.tokenizer_term import TokenizerCustomTerm
from scripts import import_jieba_seed
from tests.conftest import _postgres_reachable


@pytest.mark.asyncio
@pytest.mark.skipif(not _postgres_reachable(), reason="postgres not reachable")
async def test_import_inserts_rows_with_seed_script_source(
    db_session, tmp_path: Path
):
    test_terms = ["脆腸測試詞A", "脆腸測試詞B", "脆腸測試詞C"]
    await db_session.execute(
        delete(TokenizerCustomTerm).where(
            TokenizerCustomTerm.term.in_(test_terms)
        )
    )
    await db_session.commit()

    csv_path = tmp_path / "seed.csv"
    with csv_path.open("w", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["term", "occurrences", "sample_episode_titles"])
        for t in test_terms:
            writer.writerow([t, 50, "ep1 | ep2"])

    inserted, skipped = await import_jieba_seed.import_from_csv(csv_path)
    assert inserted == 3
    assert skipped == 0

    rows = (
        await db_session.execute(
            select(TokenizerCustomTerm).where(
                TokenizerCustomTerm.term.in_(test_terms)
            )
        )
    ).scalars().all()
    assert {r.term for r in rows} == set(test_terms)
    assert all(r.source == "seed_script" for r in rows)
    assert all(r.weight == 100 for r in rows)

    inserted2, skipped2 = await import_jieba_seed.import_from_csv(csv_path)
    assert inserted2 == 0
    assert skipped2 == 3

    await db_session.execute(
        delete(TokenizerCustomTerm).where(
            TokenizerCustomTerm.term.in_(test_terms)
        )
    )
    await db_session.commit()


def test_default_jieba_splits_oov_term():
    from scripts.build_jieba_seed_dict import _splits_in_default_jieba

    # control: a real word jieba knows shouldn't split
    assert not _splits_in_default_jieba("世界")
    # OOV restaurant name (4 chars) should split — 4-char hapaxes are not
    # fused by jieba's HMM the way some 3-char names are.
    assert _splits_in_default_jieba("蘴月食堂")


def test_cjk_only_filter():
    from scripts.build_jieba_seed_dict import _is_cjk_only

    assert _is_cjk_only("迪拉胖")
    assert not _is_cjk_only("ep143")
    assert not _is_cjk_only("迪 拉胖")
    assert not _is_cjk_only("")
