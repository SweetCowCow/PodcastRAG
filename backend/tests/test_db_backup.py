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


def _make_draining_client():
    """boto3-like client whose upload_fileobj consumes the stream to EOF."""
    mock_client = MagicMock()

    def drain(fileobj, bucket, key, *args, **kwargs):
        while fileobj.read(64 * 1024):
            pass

    mock_client.upload_fileobj.side_effect = drain
    return mock_client


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
    mock_client.copy_object.assert_not_called()


def test_sunday_promotes_to_weekly(monkeypatch, configured_backup):
    # 2026-05-10 is a Sunday.
    _frozen_now(monkeypatch, datetime(2026, 5, 10, 3, 0, tzinfo=timezone.utc))
    assert date(2026, 5, 10).weekday() == 6
    _patch_subprocess(monkeypatch)

    mock_client = MagicMock()
    mock_client.head_object.side_effect = ClientError(
        {"Error": {"Code": "NoSuchKey", "Message": "missing"}}, "HeadObject"
    )
    monkeypatch.setattr(backup_mod, "get_r2_backup_client", lambda: mock_client)
    monkeypatch.setattr(backup_mod, "send_email", _async_noop)

    backup_mod.run_db_backup()

    copy_calls = mock_client.copy_object.call_args_list
    weekly_keys = [c.kwargs["Key"] for c in copy_calls]
    assert "weekly/2026-05-10.dump.age" in weekly_keys


def test_day_one_promotes_to_monthly(monkeypatch, configured_backup):
    # 2026-06-01 (also a Monday — not Sunday, so only monthly promotion fires)
    _frozen_now(monkeypatch, datetime(2026, 6, 1, 3, 0, tzinfo=timezone.utc))
    assert date(2026, 6, 1).weekday() != 6
    _patch_subprocess(monkeypatch)

    mock_client = MagicMock()
    mock_client.head_object.side_effect = ClientError(
        {"Error": {"Code": "NoSuchKey", "Message": "missing"}}, "HeadObject"
    )
    monkeypatch.setattr(backup_mod, "get_r2_backup_client", lambda: mock_client)
    monkeypatch.setattr(backup_mod, "send_email", _async_noop)

    backup_mod.run_db_backup()

    copy_calls = mock_client.copy_object.call_args_list
    keys = [c.kwargs["Key"] for c in copy_calls]
    assert keys == ["monthly/2026-06-01.dump.age"]


def test_pg_dump_failure_alerts_and_raises(monkeypatch, configured_backup):
    _frozen_now(monkeypatch, datetime(2026, 5, 13, 3, 0, tzinfo=timezone.utc))
    _patch_subprocess(monkeypatch, pg_rc=1, pg_stderr=b"connection refused")

    mock_client = MagicMock()
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

    mock_client = MagicMock()
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

    mock_client = MagicMock()
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
