"""Tests for app.core.rate_limit using a real Redis (docker compose).

Each test uses a unique IP-like key suffix so concurrent / repeated runs
do not collide with each other or with prod-shaped keys.
"""
import socket
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.core import rate_limit


def _redis_reachable() -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.3)
    try:
        s.connect(("127.0.0.1", 6379))
        return True
    except OSError:
        return False
    finally:
        s.close()


@pytest.fixture
def fresh_ip():
    """Yield a unique IP-string and clean up its keys after."""
    fake = f"test-{uuid.uuid4()}"
    yield fake
    r = rate_limit._get_redis()
    today = datetime.now(timezone.utc)
    for offset in (0, -1, 1):
        d = today + timedelta(days=offset)
        r.delete(f"{rate_limit.KEY_PREFIX}:{fake}:{d.strftime('%Y%m%d')}")


@pytest.mark.skipif(not _redis_reachable(), reason="redis not reachable")
def test_first_hit_sets_counter_and_expire(fresh_ip):
    count, exceeded = rate_limit.check_ip_search_limit(fresh_ip, limit=20)
    assert count == 1
    assert exceeded is False
    r = rate_limit._get_redis()
    ttl = r.ttl(rate_limit._today_key(fresh_ip))
    # TTL should be close to 86400 (just set), allow some slack
    assert 86_390 <= ttl <= 86_400


@pytest.mark.skipif(not _redis_reachable(), reason="redis not reachable")
def test_below_limit_allowed(fresh_ip):
    for _ in range(5):
        rate_limit.check_ip_search_limit(fresh_ip, limit=20)
    count, exceeded = rate_limit.check_ip_search_limit(fresh_ip, limit=20)
    assert count == 6
    assert exceeded is False


@pytest.mark.skipif(not _redis_reachable(), reason="redis not reachable")
def test_at_limit_still_allowed_then_over(fresh_ip):
    """Inclusive: the Nth call (counter==limit) is the last allowed."""
    for _ in range(20):
        count, exceeded = rate_limit.check_ip_search_limit(fresh_ip, limit=20)
    assert count == 20
    assert exceeded is False
    count, exceeded = rate_limit.check_ip_search_limit(fresh_ip, limit=20)
    assert count == 21
    assert exceeded is True


@pytest.mark.skipif(not _redis_reachable(), reason="redis not reachable")
def test_separate_ips_independent(fresh_ip):
    other = f"test-{uuid.uuid4()}"
    try:
        for _ in range(5):
            rate_limit.check_ip_search_limit(fresh_ip, limit=10)
        count, _ = rate_limit.check_ip_search_limit(other, limit=10)
        # Other IP starts fresh
        assert count == 1
    finally:
        r = rate_limit._get_redis()
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        r.delete(f"{rate_limit.KEY_PREFIX}:{other}:{today}")


def test_client_ip_honors_xff_first_hop():
    from starlette.requests import Request

    scope = {
        "type": "http",
        "headers": [(b"x-forwarded-for", b"8.8.8.8, 10.0.0.1")],
        "client": ("127.0.0.1", 12345),
    }
    req = Request(scope)
    assert rate_limit.client_ip(req) == "8.8.8.8"


def test_client_ip_falls_back_to_request_client():
    from starlette.requests import Request

    scope = {
        "type": "http",
        "headers": [],
        "client": ("203.0.113.5", 12345),
    }
    req = Request(scope)
    assert rate_limit.client_ip(req) == "203.0.113.5"


def test_rate_limit_error_payload_structure():
    payload = rate_limit.rate_limit_error_payload(20)
    assert payload["error_code"] == "ip_rate_limited"
    assert payload["limit"] == 20
    assert "reset_at_utc" in payload
    # Format: YYYY-MM-DDT00:00:00Z
    assert payload["reset_at_utc"].endswith("T00:00:00Z")
