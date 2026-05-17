"""Tests for the daily usage_alert beat task.

Covers the 4 scenarios from the spec:
- 80% triggers yellow
- 95% triggers red
- Already alerted today → no re-alert
- Below 80% → no alert

The threshold classifier is pure-Python so we test it without a DB. The
end-to-end orchestration (DB read + ZSend dispatch + alert log write) is
exercised via fakes for the DB session + ZSend helper.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.workers import usage_alert


def test_classify_thresholds():
    assert usage_alert._classify(0.50) is None
    assert usage_alert._classify(0.799) is None
    assert usage_alert._classify(0.80) == "yellow"
    assert usage_alert._classify(0.94) == "yellow"
    assert usage_alert._classify(0.95) == "red"
    assert usage_alert._classify(1.50) == "red"


# ── End-to-end orchestration with fakes ────────────────────────────────


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value

    def all(self):
        return self._value if isinstance(self._value, list) else []

    def first(self):
        if isinstance(self._value, list) and self._value:
            return self._value[0]
        return self._value


class _FakeSession:
    """Records execute calls; returns scripted scalars by SQL substring match."""

    def __init__(self, *, accumulated: dict, already_alerted: set):
        self.accumulated = accumulated  # {provider: Decimal}
        self.already_alerted = already_alerted  # {(provider, severity)}
        self.recorded_alerts: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, stmt, params=None):
        sql_text = str(getattr(stmt, "text", stmt))
        params = params or {}
        if "SUM(spend_usd)" in sql_text and "GROUP BY model" not in sql_text:
            # month-to-date spend
            return _FakeResult(self.accumulated.get(params["provider"], Decimal("0")))
        if "GROUP BY model" in sql_text:
            # top models — return some fake
            return _FakeResult(
                [("gpt-4o-mini", Decimal("5.0")), ("whisper-1", Decimal("2.0"))]
            )
        # already_alerted SELECT
        if "usage_alert_log" in sql_text and "INSERT" not in sql_text.upper():
            # We can't easily parse SQLAlchemy expressions; rely on the helper
            # path instead by inspecting _already_alerted directly elsewhere.
            return _FakeResult(None)
        # INSERT into usage_alert_log (via on_conflict)
        if "usage_alert_log" in sql_text.lower() or "INSERT" in sql_text.upper():
            self.recorded_alerts.append(dict(params or {}))
            return _FakeResult(None)
        return _FakeResult(None)

    async def commit(self):
        return None


@pytest.fixture
def patch_engine(monkeypatch):
    class _NoopEngine:
        async def dispose(self):
            return None

    monkeypatch.setattr(
        usage_alert, "create_async_engine", lambda *a, **kw: _NoopEngine()
    )


@pytest.fixture
def patch_zsend_settings(monkeypatch):
    monkeypatch.setattr(usage_alert.settings, "zsend_api_key", "x")
    monkeypatch.setattr(
        usage_alert.settings, "zsend_admin_to_email", "admin@example.com"
    )
    monkeypatch.setattr(
        usage_alert.settings,
        "provider_budget_usd_monthly_aihub",
        80.0,
        raising=False,
    )
    monkeypatch.setattr(
        usage_alert.settings,
        "provider_budget_usd_monthly_openai",
        30.0,
        raising=False,
    )


async def _run_with_state(
    monkeypatch,
    *,
    accumulated: dict[str, Decimal],
    already_alerted: set[tuple[str, str]] | None = None,
):
    sent: list[dict] = []

    async def fake_send(**kwargs):
        sent.append(kwargs)

    monkeypatch.setattr(usage_alert, "send_usage_threshold_alert", fake_send)

    session = _FakeSession(
        accumulated=accumulated, already_alerted=already_alerted or set()
    )

    class _Maker:
        def __call__(self):
            return session

    monkeypatch.setattr(
        usage_alert,
        "async_sessionmaker",
        lambda engine, expire_on_commit=False: _Maker(),
    )

    # Override _already_alerted because the FakeSession can't introspect
    # SQLAlchemy SELECTs faithfully — drive dedupe via the same set.
    state = already_alerted or set()

    async def fake_already(db, provider, severity, alerted_date):
        # Yellow is suppressed if any alert today; red checks (provider, red)
        if severity == "yellow":
            return any(p == provider for (p, _s) in state)
        return (provider, severity) in state

    monkeypatch.setattr(usage_alert, "_already_alerted", fake_already)

    async def fake_record(db, provider, severity, alerted_date):
        state.add((provider, severity))

    monkeypatch.setattr(usage_alert, "_record_alert", fake_record)

    return await usage_alert._run(), sent


@pytest.mark.asyncio
async def test_80_percent_triggers_yellow(
    monkeypatch, patch_engine, patch_zsend_settings
):
    summary, sent = await _run_with_state(
        monkeypatch,
        accumulated={"aihub": Decimal("65"), "openai": Decimal("0")},
    )
    assert summary["aihub"]["severity"] == "yellow"
    yellows = [s for s in sent if s["severity"] == "yellow" and s["provider"] == "aihub"]
    assert len(yellows) == 1


@pytest.mark.asyncio
async def test_95_percent_triggers_red_and_no_yellow(
    monkeypatch, patch_engine, patch_zsend_settings
):
    summary, sent = await _run_with_state(
        monkeypatch,
        accumulated={"aihub": Decimal("77"), "openai": Decimal("0")},
    )
    assert summary["aihub"]["severity"] == "red"
    sevs = {s["severity"] for s in sent if s["provider"] == "aihub"}
    assert sevs == {"red"}


@pytest.mark.asyncio
async def test_already_alerted_today_skipped(
    monkeypatch, patch_engine, patch_zsend_settings
):
    summary, sent = await _run_with_state(
        monkeypatch,
        accumulated={"aihub": Decimal("66"), "openai": Decimal("0")},
        already_alerted={("aihub", "yellow")},
    )
    assert all(s["provider"] != "aihub" for s in sent)
    assert summary["aihub"]["severity"] == "yellow"
    assert summary["aihub"].get("skipped") == "already_alerted"


@pytest.mark.asyncio
async def test_below_80_no_alert(
    monkeypatch, patch_engine, patch_zsend_settings
):
    summary, sent = await _run_with_state(
        monkeypatch,
        accumulated={"aihub": Decimal("40"), "openai": Decimal("10")},
    )
    assert sent == []
    assert summary["aihub"]["severity"] is None
    assert summary["openai"]["severity"] is None


@pytest.mark.asyncio
async def test_skipped_when_zsend_unconfigured(monkeypatch, patch_engine):
    monkeypatch.setattr(usage_alert.settings, "zsend_api_key", None)
    result = await usage_alert._run()
    assert result == {"skipped": "zsend_unconfigured"}
