"""Tests for the service-layer RAG result cache (change: r4-rag-result-cache)."""
import uuid
from unittest.mock import patch

import pytest

from app.core.config import settings
from app.services import rag_cache
from app.services.rag_types import ChunkHit


class _FakeRedis:
    """Minimal in-memory stand-in for the redis client used by rag_cache."""

    def __init__(self):
        self.kv: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}

    def get(self, key):
        return self.kv.get(key)

    def set(self, key, value, ex=None):
        self.kv[key] = value

    def incr(self, key):
        self.kv[key] = str(int(self.kv.get(key, 0)) + 1)
        return int(self.kv[key])

    def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, value)

    def ltrim(self, key, start, end):
        self.lists[key] = self.lists.get(key, [])[start : end + 1]

    def lrange(self, key, start, end):
        items = self.lists.get(key, [])
        return items[start:] if end == -1 else items[start : end + 1]

    def expire(self, key, ttl):
        pass


class _RaisingRedis:
    """Every operation raises — used to prove fail-open behavior."""

    def __getattr__(self, _name):
        def _boom(*_a, **_k):
            raise RuntimeError("redis down")

        return _boom


def _patch_redis(fake):
    return patch("app.services.rag_cache._get_redis", return_value=fake)


def _sample_hit() -> ChunkHit:
    return ChunkHit(
        episode_id=uuid.uuid4(),
        episode_title="EP1",
        start_time=1.0,
        end_time=2.0,
        text="hello",
        chunk_id=uuid.uuid4(),
        rrf_score=0.5,
    )


# --- Task 1.1: settings defaults --------------------------------------------


def test_settings_defaults():
    assert settings.rag_cache_enabled is True
    assert settings.rag_cache_ttl_seconds == 604800
    assert settings.enable_semantic_cache is False
    assert settings.semantic_cache_threshold == 0.95


# --- Task 1.2: round-trip + miss --------------------------------------------


def test_embedding_round_trip_and_miss():
    fake = _FakeRedis()
    with _patch_redis(fake):
        assert rag_cache.get_embedding("hi", "m1") is None  # miss
        rag_cache.set_embedding("hi", "m1", [0.1, 0.2, 0.3])
        assert rag_cache.get_embedding("hi", "m1") == [0.1, 0.2, 0.3]


def test_retrieval_round_trip_preserves_hits():
    fake = _FakeRedis()
    hit = _sample_hit()
    with _patch_redis(fake):
        key = rag_cache.retrieval_key(uuid.uuid4(), "q", [0.1, 0.2], 8, None, None)
        assert rag_cache.get_retrieval(key) is None
        rag_cache.set_retrieval(key, [hit])
        got = rag_cache.get_retrieval(key)
    assert len(got) == 1
    assert got[0].episode_id == hit.episode_id
    assert got[0].chunk_id == hit.chunk_id
    assert got[0].text == "hello"
    assert isinstance(got[0].episode_id, uuid.UUID)


def test_keyword_round_trip():
    fake = _FakeRedis()
    show = uuid.uuid4()
    payload = {"query": "x", "t1": {"total": 1}, "cid": str(uuid.uuid4())}
    with _patch_redis(fake):
        key = rag_cache.keyword_key(show, "x", 10, 0, 0, 25)
        assert rag_cache.get_keyword(key) is None
        rag_cache.set_keyword(key, payload)
        assert rag_cache.get_keyword(key) == payload


# --- Task 1.3: fail-open + kill switch --------------------------------------


def test_fail_open_on_redis_error():
    with _patch_redis(_RaisingRedis()):
        # getters degrade to miss, setters swallow, nothing raises
        assert rag_cache.get_embedding("hi", "m1") is None
        rag_cache.set_embedding("hi", "m1", [0.1])
        key = rag_cache.retrieval_key(uuid.uuid4(), "q", [0.1], 8, None, None)
        assert rag_cache.get_retrieval(key) is None
        rag_cache.set_retrieval(key, [_sample_hit()])
        assert rag_cache.get_keyword("k") is None
        assert rag_cache.get_corpus_version(uuid.uuid4()) == 0


def test_kill_switch_disables_cache():
    fake = _FakeRedis()
    with _patch_redis(fake), patch.object(settings, "rag_cache_enabled", False):
        rag_cache.set_embedding("hi", "m1", [0.1])
        assert rag_cache.get_embedding("hi", "m1") is None  # disabled -> miss


# --- Task 2.1: normalization + key composition ------------------------------


def test_normalize_collapses_whitespace():
    assert rag_cache.normalize("  下   集  ") == "下 集"


def test_embedding_key_ignores_whitespace_variants():
    assert rag_cache._emb_key("a  b", "m") == rag_cache._emb_key(" a b ", "m")


def test_retrieval_key_differs_on_top_k():
    fake = _FakeRedis()
    show = uuid.uuid4()
    with _patch_redis(fake):
        k8 = rag_cache.retrieval_key(show, "q", [0.1, 0.2], 8, None, None)
        k25 = rag_cache.retrieval_key(show, "q", [0.1, 0.2], 25, None, None)
    assert k8 != k25


def test_corpus_version_bump_changes_retrieval_key():
    fake = _FakeRedis()
    show = uuid.uuid4()
    with _patch_redis(fake):
        before = rag_cache.retrieval_key(show, "q", [0.1], 8, None, None)
        rag_cache.bump_corpus_version(show)
        after = rag_cache.retrieval_key(show, "q", [0.1], 8, None, None)
    assert before != after


# --- Task 2.2: config version -----------------------------------------------


def test_config_version_changes_with_hyde_flag():
    fake = _FakeRedis()
    with _patch_redis(fake):
        with patch.object(settings, "enable_hyde_retrieval", False):
            v_off = rag_cache.compute_config_version()
        with patch.object(settings, "enable_hyde_retrieval", True):
            v_on = rag_cache.compute_config_version()
    assert v_off != v_on


# --- Task 6.1: semantic cache machinery (flag off) --------------------------


def test_semantic_lookup_disabled_returns_none():
    fake = _FakeRedis()
    with _patch_redis(fake):
        # default: enable_semantic_cache is False
        assert (
            rag_cache.semantic_lookup(uuid.uuid4(), [0.1, 0.2], "一個正常的問題")
            is None
        )


def test_semantic_excludes_low_quality_query_when_enabled():
    fake = _FakeRedis()
    show = uuid.uuid4()
    with _patch_redis(fake), patch.object(settings, "enable_semantic_cache", True):
        # punctuation-only / too-short queries are neither stored nor served
        rag_cache.semantic_store(show, [0.1, 0.2], "???", "ret_key")
        assert fake.lists == {}
        assert rag_cache.semantic_lookup(show, [0.1, 0.2], "???") is None


def test_semantic_hit_when_enabled_above_threshold():
    fake = _FakeRedis()
    show = uuid.uuid4()
    hit = _sample_hit()
    with _patch_redis(fake), patch.object(settings, "enable_semantic_cache", True):
        ret_key = rag_cache.retrieval_key(show, "近似問題", [1.0, 0.0], 8, None, None)
        rag_cache.set_retrieval(ret_key, [hit])
        rag_cache.semantic_store(show, [1.0, 0.0], "一個夠長的問題", ret_key)
        # identical vector -> cosine 1.0 >= threshold
        result = rag_cache.semantic_lookup(show, [1.0, 0.0], "一個夠長的問題")
    assert result is not None
    assert result["similarity"] == pytest.approx(1.0)
    assert result["hits"][0].episode_id == hit.episode_id
