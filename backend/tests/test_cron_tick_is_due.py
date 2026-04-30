"""Unit tests for cron_tick._is_due — pure function, no DB needed."""
from types import SimpleNamespace

import pytest

from app.workers.cron_tick import _is_due


def make_schedule(frequency: str, run_time: str, day_of_week: int = 0):
    return SimpleNamespace(
        frequency=frequency, run_time=run_time, day_of_week=day_of_week
    )


@pytest.mark.parametrize(
    "weekday,current_hhmm,sched_dow,sched_run_time,expected",
    [
        # Per design weekly due-evaluation table
        (2, "09:30", 2, "09:30", True),   # Wed match
        (1, "09:30", 2, "09:30", False),  # Tue, dow mismatch
        (2, "09:31", 2, "09:30", False),  # Wed but time off by 1 min
        (0, "06:00", 0, "06:00", True),   # Mon match
        (6, "23:00", 6, "23:00", True),   # Sun match
    ],
)
def test_weekly_due_evaluation(
    weekday, current_hhmm, sched_dow, sched_run_time, expected
):
    sched = make_schedule("weekly", sched_run_time, sched_dow)
    assert _is_due(sched, current_hhmm, weekday) is expected


def test_daily_fires_when_time_matches():
    sched = make_schedule("daily", "06:00")
    # Daily ignores weekday entirely
    for wd in range(7):
        assert _is_due(sched, "06:00", wd) is True


def test_daily_does_not_fire_when_time_differs():
    sched = make_schedule("daily", "06:00")
    assert _is_due(sched, "06:01", 0) is False


def test_manual_never_fires():
    sched = make_schedule("manual", "06:00", day_of_week=0)
    for wd in range(7):
        assert _is_due(sched, "06:00", wd) is False
