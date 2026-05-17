"""Tests for celery-routing-and-dispatcher-fix.

Verify queue routing config + message priority assignments declared in
``app.workers.celery_app``. Pure config inspection — no broker / DB needed,
so these run even without postgres / redis local stack.

Covers:
- Requirement: Queue routing splits tasks across four named queues
- Requirement: Message priority orders task dispatch within and across queues
- Requirement: task_default_queue defaults to control
"""
from __future__ import annotations

import pytest

from app.workers.celery_app import celery_app

# Force task registration by importing the task modules. In a worker this
# happens via celery_app.conf.include; in unit tests we need to import to
# populate celery_app.tasks for decorator inspection.
import app.workers.tasks  # noqa: F401
import app.workers.topic_task  # noqa: F401
import app.workers.summary_task  # noqa: F401
import app.workers.cron_tick  # noqa: F401
import app.workers.quota_digest  # noqa: F401
import app.workers.eval_reminder  # noqa: F401
import app.workers.db_backup  # noqa: F401
import app.workers.tokenizer_reload  # noqa: F401
import app.workers.usage_collector  # noqa: F401
import app.workers.usage_alert  # noqa: F401


# Single source of truth — what the proposal mandates each task should route to.
EXPECTED_ROUTES = {
    "app.workers.tasks.transcribe_episode": ("transcribe", 9),
    "app.workers.topic_task.classify_episode_topics": ("topic", 2),
    "app.workers.summary_task.generate_episode_summary": ("summary", 2),
    "app.workers.cron_tick.cron_tick": ("control", None),
    "app.workers.quota_digest.send_quota_digest": ("control", None),
    "app.workers.eval_reminder.send_eval_reminder": ("control", None),
    "app.workers.db_backup.run_db_backup": ("control", None),
    "app.workers.tokenizer_reload.broadcast_reload": ("control", None),
    "app.workers.usage_collector.collect_provider_usage": ("control", None),
    "app.workers.usage_alert.evaluate_usage_thresholds": ("control", None),
}


@pytest.mark.parametrize("task_name,expected", list(EXPECTED_ROUTES.items()))
def test_task_routes_match_expected(task_name, expected):
    expected_queue, expected_priority = expected
    routes = celery_app.conf.task_routes
    assert task_name in routes, f"task {task_name} missing from task_routes"
    entry = routes[task_name]
    assert entry["queue"] == expected_queue, (
        f"{task_name} → expected queue={expected_queue}, got {entry.get('queue')}"
    )
    if expected_priority is not None:
        assert entry.get("priority") == expected_priority, (
            f"{task_name} → expected priority={expected_priority}, "
            f"got {entry.get('priority')}"
        )


def test_task_default_queue_is_control():
    """Future task without explicit route SHALL fall to control (not be dropped)."""
    assert celery_app.conf.task_default_queue == "control"


def test_priority_config_present():
    assert celery_app.conf.task_queue_max_priority == 10
    assert celery_app.conf.task_default_priority == 5


def test_broker_transport_options_has_priority_steps():
    opts = celery_app.conf.broker_transport_options or {}
    assert opts.get("priority_steps") == [0, 3, 6, 9], (
        "Redis broker priority_steps must be [0,3,6,9] for 4-level low/default/medium/high"
    )


def test_worker_prefetch_multiplier_is_one():
    """prefetch=1 是 priority 真正生效的前提（worker 不囤積就會每次重排序）。"""
    assert celery_app.conf.worker_prefetch_multiplier == 1


def test_every_registered_task_routed_or_default():
    """task_routes 集中管理：四個關鍵 task 一定要顯式 routed；其他可吃 default control。"""
    routes = celery_app.conf.task_routes
    critical = {
        "app.workers.tasks.transcribe_episode",
        "app.workers.topic_task.classify_episode_topics",
        "app.workers.summary_task.generate_episode_summary",
    }
    missing = critical - set(routes.keys())
    assert not missing, f"critical tasks missing explicit route: {missing}"


def test_transcribe_task_decorator_priority_is_high():
    """Task decorator 自帶 priority=9，確保 .delay() / send_task() 都拿到高 priority。"""
    task = celery_app.tasks["app.workers.tasks.transcribe_episode"]
    assert getattr(task, "priority", None) == 9


def test_topic_and_summary_decorator_priority_is_low():
    topic = celery_app.tasks["app.workers.topic_task.classify_episode_topics"]
    summary = celery_app.tasks["app.workers.summary_task.generate_episode_summary"]
    assert getattr(topic, "priority", None) == 2
    assert getattr(summary, "priority", None) == 2


def test_priority_ordering_invariant():
    """Doc-style: priority 9 > 5 > 2，pop 順序就是這條 invariant。

    Redis broker 把每個 priority bucket 變成獨立 sub-list；slot 空出來時優先 pop
    高 priority bucket。這條測試以 EXPECTED_ROUTES 為真，驗 transcribe>control>topic 排序。
    """
    pri = {name: prio for name, (_q, prio) in EXPECTED_ROUTES.items() if prio is not None}
    assert pri["app.workers.tasks.transcribe_episode"] > celery_app.conf.task_default_priority
    assert pri["app.workers.topic_task.classify_episode_topics"] < celery_app.conf.task_default_priority
    assert pri["app.workers.summary_task.generate_episode_summary"] < celery_app.conf.task_default_priority
