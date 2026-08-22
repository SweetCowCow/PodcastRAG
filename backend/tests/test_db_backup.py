"""Tests for the daily DB backup beat task.

Strategy:
- subprocess.Popen is patched with a fake that returns canned bytes for
  pg_dump and a passthrough age. boto3 client is a MagicMock.
- Date-dependent branches (Sunday, day-of-month==1) are exercised by
  freezing `datetime.now` via monkeypatch.
- Failure paths assert ZSend send_email is called with the spec subject lines.
"""
from __future__ import annotations

import io
import json
import subprocess
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from app.workers import db_backup as backup_mod


@pytest.fixture
def configured_backup(monkeypatch):
    """Configure all backup-related settings + ZSend so the task is non-skipped."""
    s = backup_mod.settings
    monkeypatch.setattr(s, "r2_backup_endpoint_url", "https://r2.example.com")
    monkeypatch.setattr(s, "r2_backup_access_key_id", "kid")
    monkeypatch.setattr(s, "r2_backup_secret_access_key", "secret")
    monkeypatch.setattr(s, "r2_backup_bucket", "podcastrag-backup")
    monkeypatch.setattr(
        s,
        "backup_age_public_key",
        "age1admin000000000000000000000000000000000000000000000000000000,age1gha0000000000000000000000000000000000000000000000000000000",
    )
    monkeypatch.setattr(s, "zsend_api_key", "zs_test")
    monkeypatch.setattr(s, "zsend_from_email", "noreply@podcastrag.app")
    monkeypatch.setattr(s, "zsend_admin_to_email", "admin@example.com")
    monkeypatch.setattr(
        s, "database_url", "postgresql+asyncpg://u:p@h/d"
    )


def _make_proc(stdout_bytes=b"", stderr_bytes=b"", returncode=0):
    proc = MagicMock()
    proc.stdout = io.BytesIO(stdout_bytes)
    proc.stderr = io.BytesIO(stderr_bytes)
    proc.wait = MagicMock(return_value=returncode)
    proc.kill = MagicMock()
    return proc


def _patch_subprocess(monkeypatch, *, pg_rc=0, age_rc=0,
                       pg_stderr=b"", age_stderr=b"",
                       ciphertext=b"AGE-CIPHERTEXT-FAKE"):
    """Install a Popen fake that returns pg_dump then age procs in order."""
    procs = [
        _make_proc(stdout_bytes=b"pg-dump-bytes", stderr_bytes=pg_stderr,
                   returncode=pg_rc),
        _make_proc(stdout_bytes=ciphertext, stderr_bytes=age_stderr,
                   returncode=age_rc),
    ]
    call_log = []

    def fake_popen(cmd, **kwargs):
        call_log.append(cmd)
        return procs.pop(0)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    return call_log


def _frozen_now(monkeypatch, dt: datetime):
    class _DT(datetime):
        @classmethod
        def now(cls, tz=None):
            return dt if tz is None else dt.astimezone(tz)
    monkeypatch.setattr(backup_mod, "datetime", _DT)


def test_skip_when_r2_unconfigured(monkeypatch):
    s = backup_mod.settings
    monkeypatch.setattr(s, "r2_backup_endpoint_url", None)
    monkeypatch.setattr(s, "r2_backup_access_key_id", None)
    monkeypatch.setattr(s, "r2_backup_secret_access_key", None)
    monkeypatch.setattr(s, "r2_backup_bucket", None)

    result = backup_mod.run_db_backup()
    assert result == {"skipped": "r2_unconfigured"}


def _stub_maintenance(mock_client, *, lifecycle_ok=True, objects=None, uploads=None):
    """Give the post-backup maintenance calls realistic return values.

    Without this a bare MagicMock returns MagicMocks that blow up when the
    sweep tries to iterate them, which would mask the behaviour under test.
    """
    from app.services import r2_backup_client as r2

    rules = [{"ID": rid} for rid in r2._EXPECTED_RULE_IDS]
    if not lifecycle_ok:
        rules = rules[:2]
    mock_client.get_bucket_lifecycle_configuration.return_value = {"Rules": rules}

    body = MagicMock()
    body.read.return_value = b"{}"
    mock_client.get_object.return_value = {"Body": body}

    mock_client.list_objects_v2.return_value = {
        "Contents": objects or [],
        "IsTruncated": False,
    }
    mock_client.delete_objects.return_value = {"Deleted": [], "Errors": []}
    mock_client.list_multipart_uploads.return_value = {
        "Uploads": uploads or [],
        "IsTruncated": False,
    }
    return mock_client


def _make_draining_client():
    """boto3-like client whose upload_fileobj consumes the stream to EOF."""
    mock_client = MagicMock()

    def drain(fileobj, bucket, key, *args, **kwargs):
        while fileobj.read(64 * 1024):
            pass

    mock_client.upload_fileobj.side_effect = drain
    return _stub_maintenance(mock_client)


def test_happy_path_uploads_to_daily_key_with_lifecycle(monkeypatch, configured_backup):
    # Wednesday 2026-05-13 — neither Sunday nor day-1, so no promotion.
    _frozen_now(monkeypatch, datetime(2026, 5, 13, 3, 0, tzinfo=timezone.utc))
    _patch_subprocess(monkeypatch)

    mock_client = _make_draining_client()
    # head_object: yesterday doesn't exist → ClientError 404
    mock_client.head_object.side_effect = ClientError(
        {"Error": {"Code": "NoSuchKey", "Message": "missing"}}, "HeadObject"
    )

    monkeypatch.setattr(backup_mod, "get_r2_backup_client", lambda: mock_client)
    monkeypatch.setattr(backup_mod, "send_email", _async_noop)

    result = backup_mod.run_db_backup()

    assert result["sent_count"] == 1
    assert result["key"] == "daily/2026-05-13.dump.age"
    assert result["size_bytes"] > 0
    mock_client.put_bucket_lifecycle_configuration.assert_called_once()
    upload_args, upload_kwargs = mock_client.upload_fileobj.call_args
    # boto3 upload_fileobj signature: (fileobj, bucket, key)
    assert upload_args[1] == "podcastrag-backup"
    assert upload_args[2] == "daily/2026-05-13.dump.age"
    # No promotion calls today
    mock_client.copy.assert_not_called()
    mock_client.copy_object.assert_not_called()
    # Retention is now enforced in-app, not by the (unreachable) bucket policy.
    assert result["promotion_ok"] is True
    assert result["swept"] is not None
    assert result["aborted_uploads"] == 0


def test_sunday_promotes_to_weekly(monkeypatch, configured_backup):
    # 2026-05-10 is a Sunday.
    _frozen_now(monkeypatch, datetime(2026, 5, 10, 3, 0, tzinfo=timezone.utc))
    assert date(2026, 5, 10).weekday() == 6
    _patch_subprocess(monkeypatch)

    mock_client = _stub_maintenance(MagicMock())
    mock_client.head_object.side_effect = ClientError(
        {"Error": {"Code": "NoSuchKey", "Message": "missing"}}, "HeadObject"
    )
    monkeypatch.setattr(backup_mod, "get_r2_backup_client", lambda: mock_client)
    monkeypatch.setattr(backup_mod, "send_email", _async_noop)

    backup_mod.run_db_backup()

    # Managed copy: copy(CopySource, Bucket, Key) — positional, and it does
    # multipart under the hood so it clears the 5 GiB CopyObject ceiling.
    dest_keys = [c.args[2] for c in mock_client.copy.call_args_list]
    assert "weekly/2026-05-10.dump.age" in dest_keys
    mock_client.copy_object.assert_not_called()


def test_day_one_promotes_to_monthly(monkeypatch, configured_backup):
    # 2026-06-01 (also a Monday — not Sunday, so only monthly promotion fires)
    _frozen_now(monkeypatch, datetime(2026, 6, 1, 3, 0, tzinfo=timezone.utc))
    assert date(2026, 6, 1).weekday() != 6
    _patch_subprocess(monkeypatch)

    mock_client = _stub_maintenance(MagicMock())
    mock_client.head_object.side_effect = ClientError(
        {"Error": {"Code": "NoSuchKey", "Message": "missing"}}, "HeadObject"
    )
    monkeypatch.setattr(backup_mod, "get_r2_backup_client", lambda: mock_client)
    monkeypatch.setattr(backup_mod, "send_email", _async_noop)

    backup_mod.run_db_backup()

    dest_keys = [c.args[2] for c in mock_client.copy.call_args_list]
    assert dest_keys == ["monthly/2026-06-01.dump.age"]


def test_pg_dump_failure_alerts_and_raises(monkeypatch, configured_backup):
    _frozen_now(monkeypatch, datetime(2026, 5, 13, 3, 0, tzinfo=timezone.utc))
    _patch_subprocess(monkeypatch, pg_rc=1, pg_stderr=b"connection refused")

    mock_client = _stub_maintenance(MagicMock())
    monkeypatch.setattr(backup_mod, "get_r2_backup_client", lambda: mock_client)

    sent = []

    async def fake_send(to, subject, body):
        sent.append((to, subject, body))

    monkeypatch.setattr(backup_mod, "send_email", fake_send)

    with pytest.raises(RuntimeError, match="pg_dump exited"):
        backup_mod.run_db_backup()

    assert len(sent) == 1
    assert sent[0][0] == "admin@example.com"
    assert sent[0][1] == "[PodcastRAG] DB backup FAILED 2026-05-13"
    # Partial artifact must be deleted so a corrupt file doesn't shadow
    # yesterday's healthy backup (the 298-byte age-header-only case).
    mock_client.delete_object.assert_called_once_with(
        Bucket="podcastrag-backup", Key="daily/2026-05-13.dump.age"
    )


def test_size_anomaly_uploads_and_alerts(monkeypatch, configured_backup):
    _frozen_now(monkeypatch, datetime(2026, 5, 13, 3, 0, tzinfo=timezone.utc))
    # Force ciphertext small enough to trip the <0.5x lower bound vs yesterday.
    _patch_subprocess(monkeypatch, ciphertext=b"X" * 100)

    mock_client = _stub_maintenance(MagicMock())
    mock_client.head_object.return_value = {"ContentLength": 1_000}  # 10x larger
    monkeypatch.setattr(backup_mod, "get_r2_backup_client", lambda: mock_client)

    sent = []

    async def fake_send(to, subject, body):
        sent.append((to, subject, body))

    monkeypatch.setattr(backup_mod, "send_email", fake_send)

    result = backup_mod.run_db_backup()

    # Upload still completed
    assert result["sent_count"] == 1
    mock_client.upload_fileobj.assert_called_once()
    # Anomaly alert sent
    assert len(sent) == 1
    assert sent[0][1] == "[PodcastRAG] DB backup size anomaly 2026-05-13"


def test_zsend_not_configured_alert_is_noop(monkeypatch, configured_backup):
    monkeypatch.setattr(backup_mod.settings, "zsend_api_key", None)
    _frozen_now(monkeypatch, datetime(2026, 5, 13, 3, 0, tzinfo=timezone.utc))
    _patch_subprocess(monkeypatch, pg_rc=2, pg_stderr=b"boom")

    mock_client = MagicMock()
    monkeypatch.setattr(backup_mod, "get_r2_backup_client", lambda: mock_client)

    # send_email must NOT be called when ZSend is unconfigured.
    def fail_if_called(*a, **kw):  # pragma: no cover
        raise AssertionError("send_email should not be invoked")
    monkeypatch.setattr(backup_mod, "send_email", fail_if_called)

    with pytest.raises(RuntimeError):
        backup_mod.run_db_backup()


def test_no_plaintext_written_to_disk(monkeypatch, configured_backup):
    """Verify the streaming pipeline never opens a writable file handle.

    Patches `open` and `pathlib.Path.write_bytes` to record any disk writes
    (other than reads) made during a successful backup run.
    """
    _frozen_now(monkeypatch, datetime(2026, 5, 13, 3, 0, tzinfo=timezone.utc))
    _patch_subprocess(monkeypatch)

    mock_client = _stub_maintenance(MagicMock())
    mock_client.head_object.side_effect = ClientError(
        {"Error": {"Code": "NoSuchKey", "Message": "missing"}}, "HeadObject"
    )
    monkeypatch.setattr(backup_mod, "get_r2_backup_client", lambda: mock_client)
    monkeypatch.setattr(backup_mod, "send_email", _async_noop)

    write_calls: list[str] = []

    import builtins
    real_open = builtins.open

    def tracking_open(file, mode="r", *args, **kwargs):
        if any(m in mode for m in ("w", "a", "x")) and "b" in mode:
            write_calls.append(f"open({file!r}, {mode!r})")
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", tracking_open)

    from pathlib import Path
    real_write_bytes = Path.write_bytes

    def tracking_write_bytes(self, data):
        write_calls.append(f"Path({self}).write_bytes")
        return real_write_bytes(self, data)

    monkeypatch.setattr(Path, "write_bytes", tracking_write_bytes)

    backup_mod.run_db_backup()

    # No binary writes by our backup pipeline. (boto3's internal multipart
    # buffers stay in-memory; subprocess uses pipes, not files.)
    assert write_calls == [], (
        f"Backup pipeline wrote plaintext to disk: {write_calls}"
    )


async def _async_noop(*args, **kwargs):
    return None


def _collect_mail(monkeypatch):
    """Patch send_email to record (to, subject, body) tuples."""
    sent: list[tuple[str, str, str]] = []

    async def fake_send(to, subject, body):
        sent.append((to, subject, body))

    monkeypatch.setattr(backup_mod, "send_email", fake_send)
    return sent


def _subjects(sent) -> list[str]:
    return [s for _, s, _ in sent]


def _run_backup_on_a_quiet_day(monkeypatch, mock_client):
    """Run a successful backup on a non-promotion day."""
    _frozen_now(monkeypatch, datetime(2026, 5, 13, 3, 0, tzinfo=timezone.utc))
    _patch_subprocess(monkeypatch)
    mock_client.head_object.side_effect = ClientError(
        {"Error": {"Code": "NoSuchKey", "Message": "missing"}}, "HeadObject"
    )
    monkeypatch.setattr(backup_mod, "get_r2_backup_client", lambda: mock_client)
    return backup_mod.run_db_backup()


def _state_body(outcome: str | None):
    body = MagicMock()
    body.read.return_value = (
        b"{}" if outcome is None else f'{{"outcome": "{outcome}"}}'.encode()
    )
    return {"Body": body}


# --------------------------------------------------------------------------
# 5.8-5.10 lifecycle verification alerts only on state transitions
# --------------------------------------------------------------------------


def test_lifecycle_verify_failure_alerts_and_backup_still_completes(
    monkeypatch, configured_backup
):
    """First failure (no prior state) alerts, and the backup still succeeds."""
    mock_client = _stub_maintenance(_make_draining_client(), lifecycle_ok=False)
    mock_client.get_object.return_value = _state_body(None)
    sent = _collect_mail(monkeypatch)

    result = _run_backup_on_a_quiet_day(monkeypatch, mock_client)

    assert result["sent_count"] == 1  # backup itself unaffected
    assert "[PodcastRAG] DB backup lifecycle policy NOT applied" in _subjects(sent)
    # outcome persisted so tomorrow stays quiet
    state_writes = [
        c for c in mock_client.put_object.call_args_list
        if c.kwargs.get("Key") == "_state/lifecycle_verify.json"
    ]
    assert json.loads(state_writes[-1].kwargs["Body"])["outcome"] == "failed"


def test_lifecycle_verify_access_denied_alerts_with_error_code(
    monkeypatch, configured_backup
):
    """The real prod condition: the token cannot read bucket configuration."""
    mock_client = _stub_maintenance(_make_draining_client())
    mock_client.get_bucket_lifecycle_configuration.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "Access Denied"}},
        "GetBucketLifecycleConfiguration",
    )
    mock_client.get_object.return_value = _state_body(None)
    sent = _collect_mail(monkeypatch)

    result = _run_backup_on_a_quiet_day(monkeypatch, mock_client)

    assert result["sent_count"] == 1
    bodies = [b for _, s, b in sent if "NOT applied" in s]
    assert bodies and "AccessDenied" in bodies[0]


def test_lifecycle_verify_repeated_failure_does_not_resend(
    monkeypatch, configured_backup
):
    """failed -> failed stays silent. A daily unfixable email IS alert fatigue."""
    mock_client = _stub_maintenance(_make_draining_client(), lifecycle_ok=False)
    mock_client.get_object.return_value = _state_body("failed")
    sent = _collect_mail(monkeypatch)

    _run_backup_on_a_quiet_day(monkeypatch, mock_client)

    assert "[PodcastRAG] DB backup lifecycle policy NOT applied" not in _subjects(sent)


def test_lifecycle_verify_recovery_sends_restored_alert(
    monkeypatch, configured_backup
):
    """failed -> ok is worth one email."""
    mock_client = _stub_maintenance(_make_draining_client())
    mock_client.get_object.return_value = _state_body("failed")
    sent = _collect_mail(monkeypatch)

    _run_backup_on_a_quiet_day(monkeypatch, mock_client)

    assert "[PodcastRAG] DB backup lifecycle policy restored" in _subjects(sent)


def test_lifecycle_verify_ok_on_first_run_is_not_news(monkeypatch, configured_backup):
    """No prior state + passing verification must not email anybody."""
    mock_client = _stub_maintenance(_make_draining_client())
    mock_client.get_object.return_value = _state_body(None)
    sent = _collect_mail(monkeypatch)

    _run_backup_on_a_quiet_day(monkeypatch, mock_client)

    assert _subjects(sent) == []


# --------------------------------------------------------------------------
# 5.11 promotion failure is isolated from the day's backup
# --------------------------------------------------------------------------


def test_promotion_failure_alerts_without_failing_the_backup(
    monkeypatch, configured_backup
):
    """Promotion raising must NOT re-run pg_dump — that was the 7 GB retry bug."""
    # 2026-05-10 is a Sunday → weekly promotion fires.
    _frozen_now(monkeypatch, datetime(2026, 5, 10, 3, 0, tzinfo=timezone.utc))
    popen_calls = _patch_subprocess(monkeypatch)

    mock_client = _stub_maintenance(_make_draining_client())
    mock_client.get_object.return_value = _state_body("ok")
    mock_client.copy.side_effect = ClientError(
        {"Error": {"Code": "EntityTooLarge", "Message": "too large"}}, "CopyObject"
    )
    mock_client.head_object.side_effect = ClientError(
        {"Error": {"Code": "NoSuchKey", "Message": "missing"}}, "HeadObject"
    )
    monkeypatch.setattr(backup_mod, "get_r2_backup_client", lambda: mock_client)
    sent = _collect_mail(monkeypatch)

    result = backup_mod.run_db_backup()

    assert result["sent_count"] == 1
    assert result["promotion_ok"] is False
    assert "[PodcastRAG] DB backup promotion failed 2026-05-10" in _subjects(sent)
    # pg_dump ran exactly once (one pg_dump + one age invocation)
    assert sum(1 for c in popen_calls if c[0] == "pg_dump") == 1


# --------------------------------------------------------------------------
# 5.12 sweep failures
# --------------------------------------------------------------------------


def test_sweep_failure_alerts_without_failing_the_backup(
    monkeypatch, configured_backup
):
    mock_client = _stub_maintenance(_make_draining_client())
    mock_client.get_object.return_value = _state_body("ok")
    mock_client.list_objects_v2.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "denied"}}, "ListObjectsV2"
    )
    sent = _collect_mail(monkeypatch)

    result = _run_backup_on_a_quiet_day(monkeypatch, mock_client)

    assert result["sent_count"] == 1
    assert result["swept"] is None
    assert "[PodcastRAG] DB backup retention sweep failed 2026-05-13" in _subjects(sent)


def test_sweep_needs_review_alerts_and_deletes_nothing(monkeypatch, configured_backup):
    """The safety valve: too many deletions means ask a human, delete nothing."""
    from app.services.r2_backup_client import _MAX_SWEEP_DELETES

    doomed = [
        {"Key": f"daily/2026-05-{d:02d}.dump.age", "Size": 10}
        for d in range(1, 7 + _MAX_SWEEP_DELETES + 2)
    ]
    mock_client = _stub_maintenance(_make_draining_client(), objects=doomed)
    mock_client.get_object.return_value = _state_body("ok")
    sent = _collect_mail(monkeypatch)

    result = _run_backup_on_a_quiet_day(monkeypatch, mock_client)

    assert result["sent_count"] == 1
    mock_client.delete_objects.assert_not_called()
    assert "[PodcastRAG] DB backup retention sweep needs review" in _subjects(sent)


def test_sweep_per_key_errors_alert(monkeypatch, configured_backup):
    """delete_objects reports failures in Errors WITHOUT raising."""
    objects = [
        {"Key": f"daily/2026-05-{d:02d}.dump.age", "Size": 10} for d in range(1, 11)
    ]
    mock_client = _stub_maintenance(_make_draining_client(), objects=objects)
    mock_client.get_object.return_value = _state_body("ok")
    mock_client.delete_objects.return_value = {
        "Deleted": [],
        "Errors": [
            {
                "Key": "daily/2026-05-01.dump.age",
                "Code": "AccessDenied",
                "Message": "denied",
            }
        ],
    }
    sent = _collect_mail(monkeypatch)

    result = _run_backup_on_a_quiet_day(monkeypatch, mock_client)

    assert result["sent_count"] == 1
    assert "[PodcastRAG] DB backup retention sweep failed 2026-05-13" in _subjects(sent)


# --------------------------------------------------------------------------
# 5.13 absolute usage guard
# --------------------------------------------------------------------------


def _usage_objects(count: int, size: int):
    """`count` artifacts of `size` bytes each, spread so the sweep keeps them."""
    return [
        {"Key": f"monthly/2026-{(i % 12) + 1:02d}-{(i // 12) + 1:02d}.dump.age",
         "Size": size}
        for i in range(count)
    ]


def test_usage_alert_on_object_count(monkeypatch, configured_backup):
    mock_client = _stub_maintenance(
        _make_draining_client(), objects=_usage_objects(31, 1024)
    )
    mock_client.get_object.return_value = _state_body("ok")
    sent = _collect_mail(monkeypatch)

    result = _run_backup_on_a_quiet_day(monkeypatch, mock_client)

    # 31 objects per prefix x 3 prefixes as far as the usage guard is concerned
    assert result["object_count"] > backup_mod.MAX_EXPECTED_OBJECTS
    assert "[PodcastRAG] DB backup bucket usage alert" in _subjects(sent)


def test_usage_alert_on_total_bytes(monkeypatch, configured_backup):
    """301 GB across an otherwise normal object count still alerts."""
    huge = 301 * 1024**3
    mock_client = _stub_maintenance(
        _make_draining_client(),
        objects=[{"Key": "monthly/2026-08-01.dump.age", "Size": huge}],
    )
    mock_client.get_object.return_value = _state_body("ok")
    sent = _collect_mail(monkeypatch)

    result = _run_backup_on_a_quiet_day(monkeypatch, mock_client)

    assert result["total_bytes"] > backup_mod.MAX_EXPECTED_BYTES
    assert "[PodcastRAG] DB backup bucket usage alert" in _subjects(sent)


def test_usage_within_bounds_does_not_alert(monkeypatch, configured_backup):
    """23 artifacts totalling ~163 GB is the healthy steady state."""
    seven_gb = 7 * 1024**3
    mock_client = MagicMock()

    def drain(fileobj, bucket, key, *args, **kwargs):
        while fileobj.read(64 * 1024):
            pass

    mock_client.upload_fileobj.side_effect = drain
    _stub_maintenance(mock_client)
    mock_client.get_object.return_value = _state_body("ok")

    # daily 7 / weekly 4 / monthly 12 = 23 artifacts, none over its limit.
    listings = {
        "daily/": [
            {"Key": f"daily/2026-08-{15 + i:02d}.dump.age", "Size": seven_gb}
            for i in range(7)
        ],
        "weekly/": [
            {"Key": f"weekly/2026-07-{1 + i:02d}.dump.age", "Size": seven_gb}
            for i in range(4)
        ],
        "monthly/": [
            {"Key": f"monthly/2026-{1 + i:02d}-01.dump.age", "Size": seven_gb}
            for i in range(12)
        ],
    }
    mock_client.list_objects_v2.side_effect = lambda **kw: {
        "Contents": listings.get(kw.get("Prefix", ""), []),
        "IsTruncated": False,
    }
    sent = _collect_mail(monkeypatch)

    result = _run_backup_on_a_quiet_day(monkeypatch, mock_client)

    assert result["object_count"] == 23
    assert result["total_bytes"] == 23 * seven_gb
    assert result["total_bytes"] < backup_mod.MAX_EXPECTED_BYTES
    assert "[PodcastRAG] DB backup bucket usage alert" not in _subjects(sent)
    mock_client.delete_objects.assert_not_called()


def test_usage_check_failure_is_advisory_only(monkeypatch, configured_backup):
    """A broken usage check must not fail the backup."""
    mock_client = _stub_maintenance(_make_draining_client())
    mock_client.get_object.return_value = _state_body("ok")
    monkeypatch.setattr(
        backup_mod,
        "bucket_usage",
        MagicMock(side_effect=RuntimeError("boom")),
    )
    sent = _collect_mail(monkeypatch)

    result = _run_backup_on_a_quiet_day(monkeypatch, mock_client)

    assert result["sent_count"] == 1
    assert result["object_count"] is None
    assert result["total_bytes"] is None
    assert "[PodcastRAG] DB backup bucket usage alert" not in _subjects(sent)


def test_libpq_url_strips_asyncpg_suffix():
    assert (
        backup_mod._libpq_url("postgresql+asyncpg://u:p@h:5432/d")
        == "postgresql://u:p@h:5432/d"
    )
    # Plain libpq URL passes through unchanged.
    assert (
        backup_mod._libpq_url("postgresql://u:p@h:5432/d")
        == "postgresql://u:p@h:5432/d"
    )


def test_pg_dump_argv_keeps_password_out_of_cmdline():
    """Password must be passed via PGPASSWORD env, never on argv."""
    argv, env = backup_mod._pg_dump_argv_and_env(
        "postgresql+asyncpg://root:s3cret-pa$$@db.host:5432/zeabur"
    )
    # No flag carries the password; argv has only host/port/user/dbname.
    assert "s3cret-pa$$" not in " ".join(argv)
    assert argv[-1] == "zeabur"
    assert "-h" in argv and "db.host" in argv
    assert "-p" in argv and "5432" in argv
    assert "-U" in argv and "root" in argv
    assert env["PGPASSWORD"] == "s3cret-pa$$"


def test_pg_dump_argv_url_decodes_password():
    """URL-encoded special chars in the password are decoded for PGPASSWORD."""
    # Password contains @ which must be %40 in the URL.
    argv, env = backup_mod._pg_dump_argv_and_env(
        "postgresql://u:p%40ss%2Fword@h/d"
    )
    assert env["PGPASSWORD"] == "p@ss/word"
    assert "p@ss/word" not in " ".join(argv)
