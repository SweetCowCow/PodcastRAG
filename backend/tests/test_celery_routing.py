"""celery-routing-and-dispatcher-fix: Celery routing + priority 配置驗證。

Pure config / introspection tests — 不需 broker / DB。
"""
import pytest

from app.workers.celery_app import celery_app


def test_task_default_queue_is_control():
    assert celery_app.conf.task_default_queue == "control"


def test_task_queue_max_priority_set():
    assert celery_app.conf.task_queue_max_priority == 10
    assert celery_app.conf.task_default_priority == 5


def test_broker_priority_steps_for_redis():
    bto = celery_app.conf.broker_transport_options or {}
    assert bto.get("priority_steps") == [0, 3, 6, 9]


# fix-backup-retention task 1.2: 2026-08-21 的 db_backup 實測耗時。
MEASURED_BACKUP_DURATION_SECONDS = 7656


def test_broker_visibility_timeout_covers_long_tasks():
    """acks_late=True 下，visibility_timeout 短於任務耗時 = broker 重複投遞。

    kombu Redis transport 預設 3600s，比實測的備份耗時還短，導致 2026-08-22
    發現的「每天備份跑 3 次 + multipart 殘件」。必須顯式覆寫。
    """
    bto = celery_app.conf.broker_transport_options or {}
    assert bto.get("visibility_timeout") == 14400
    assert bto["visibility_timeout"] > MEASURED_BACKUP_DURATION_SECONDS


@pytest.mark.parametrize(
    "task_name,expected_queue",
    [
        ("app.workers.tasks.transcribe_episode", "transcribe"),
        ("app.workers.topic_task.classify_episode_topics", "topic"),
        ("app.workers.summary_task.generate_episode_summary", "summary"),
        ("app.workers.cron_tick.cron_tick", "control"),
        ("app.workers.quota_digest.send_quota_digest", "control"),
        ("app.workers.appeal_digest.send_appeal_digest", "control"),
        ("app.workers.eval_reminder.send_eval_reminder", "control"),
        ("app.workers.db_backup.run_db_backup", "control"),
        ("app.workers.tokenizer_reload.broadcast_reload", "control"),
        ("app.workers.usage_collector.collect_provider_usage", "control"),
        ("app.workers.usage_alert.evaluate_usage_thresholds", "control"),
    ],
)
def test_task_routes_to_expected_queue(task_name, expected_queue):
    routes = celery_app.conf.task_routes or {}
    assert task_name in routes, f"{task_name} missing from task_routes"
    assert routes[task_name]["queue"] == expected_queue


@pytest.mark.parametrize(
    "task_name,expected_priority",
    [
        ("app.workers.tasks.transcribe_episode", 9),
        ("app.workers.topic_task.classify_episode_topics", 2),
        ("app.workers.summary_task.generate_episode_summary", 2),
    ],
)
def test_task_default_priority(task_name, expected_priority):
    # 觸發 task 註冊
    import app.workers.tasks  # noqa: F401
    import app.workers.topic_task  # noqa: F401
    import app.workers.summary_task  # noqa: F401

    task = celery_app.tasks.get(task_name)
    assert task is not None, f"{task_name} not registered"
    assert task.priority == expected_priority


def test_unrouted_task_falls_back_to_control():
    """新註冊的 task 若沒設 queue / 沒在 task_routes，apply_async
    產生的 message 應走 task_default_queue=control。"""
    # 由於 celery_app.tasks 是全域 registry，我們透過 conf 而不是真送 task
    # 驗證；task_default_queue 設成 control 即足以保證未路由 task fallback。
    assert celery_app.conf.task_default_queue == "control"
    # 額外：task_queues 應該包含 control queue
    qnames = {q.name for q in (celery_app.conf.task_queues or [])}
    assert {"transcribe", "topic", "summary", "control"}.issubset(qnames)


def test_priority_pop_order_documented_via_priority_steps():
    """sanity-check priority_steps 設計：
    transcribe=9 落 step 9，topic/summary=2 落 step 0（最低 bucket）。
    Redis broker 會優先 pop 高 step bucket → transcribe 永遠先被取走。"""
    steps = celery_app.conf.broker_transport_options["priority_steps"]
    transcribe_p = 9
    topic_p = 2
    # 用 Celery/kombu 的「向下對齊到最近 step」規則
    def bucket(p):
        return max(s for s in steps if s <= p)

    assert bucket(transcribe_p) == 9
    assert bucket(topic_p) == 0
    assert bucket(transcribe_p) > bucket(topic_p)


def test_beat_schedule_all_entries_route_to_control_queue():
    """celery-publish-routing-fix-and-f2-smoke task 3.1: F1 殘留 leak 是
    beat publish 不套 task_routes 而走 default queue → fix 是每個 beat
    entry 顯式指定 options.queue='control'。此 test 防回退。"""
    schedule = celery_app.conf.beat_schedule
    assert schedule, "beat_schedule 不該為空"
    for name, entry in schedule.items():
        opts = entry.get("options") or {}
        assert opts.get("queue") == "control", (
            f"beat entry {name!r} 缺 options.queue='control'，"
            f"會走 task_default_queue fallback → 重蹈 F1 cron_tick leak"
        )
