"""Unit tests for R2 backup client wrapper.

Verifies the lifecycle policy JSON shape, the application-side retention
sweep that replaced the (never-working) bucket lifecycle enforcement, the
stale multipart cleanup, and the absolute usage guard.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError

from app.services.r2_backup_client import (
    _MAX_SWEEP_DELETES,
    _STATE_KEY,
    abort_stale_multipart_uploads,
    apply_lifecycle_policy,
    bucket_usage,
    get_r2_backup_client,
    parse_recipients,
    read_verify_state,
    sweep_retention,
    verify_lifecycle_policy,
    write_verify_state,
)

EXPECTED_RULE_IDS = {
    "daily-7d",
    "weekly-28d",
    "monthly-365d",
    "abort-incomplete-multipart-1d",
}


def _obj(key: str, size: int = 1024):
    return {"Key": key, "Size": size}


def _daily_keys(count: int, start_day: int = 1) -> list[dict]:
    """`count` well-formed daily artifacts, dated consecutively from 2026-05-DD."""
    return [_obj(f"daily/2026-05-{start_day + i:02d}.dump.age") for i in range(count)]


def _listing(objects: list[dict]) -> dict:
    return {"Contents": objects, "IsTruncated": False}


def _prefix_router(mapping: dict[str, list[dict]]):
    """list_objects_v2 side effect returning per-prefix listings."""

    def _side_effect(**kwargs):
        return _listing(mapping.get(kwargs.get("Prefix", ""), []))

    return _side_effect


# --------------------------------------------------------------------------
# client construction
# --------------------------------------------------------------------------


def test_get_client_returns_none_when_unset(monkeypatch):
    from app.core import config as config_mod

    monkeypatch.setattr(config_mod.settings, "r2_backup_endpoint_url", None)
    monkeypatch.setattr(config_mod.settings, "r2_backup_access_key_id", None)
    monkeypatch.setattr(config_mod.settings, "r2_backup_secret_access_key", None)
    monkeypatch.setattr(config_mod.settings, "r2_backup_bucket", None)

    assert get_r2_backup_client() is None


def test_get_client_returns_boto3_when_set(monkeypatch):
    from app.core import config as config_mod

    monkeypatch.setattr(
        config_mod.settings, "r2_backup_endpoint_url", "https://example.r2.com"
    )
    monkeypatch.setattr(config_mod.settings, "r2_backup_access_key_id", "k")
    monkeypatch.setattr(config_mod.settings, "r2_backup_secret_access_key", "s")
    monkeypatch.setattr(config_mod.settings, "r2_backup_bucket", "b")

    with patch("app.services.r2_backup_client.boto3.client") as mock_client:
        mock_client.return_value = MagicMock()
        client = get_r2_backup_client()
    assert client is not None
    mock_client.assert_called_once()
    call_kwargs = mock_client.call_args.kwargs
    assert call_kwargs["endpoint_url"] == "https://example.r2.com"
    assert call_kwargs["region_name"] == "auto"


# --------------------------------------------------------------------------
# 5.1 lifecycle rules + verification
# --------------------------------------------------------------------------


def test_apply_lifecycle_policy_shape():
    mock_client = MagicMock()
    apply_lifecycle_policy(mock_client, "podcastrag-backup")

    mock_client.put_bucket_lifecycle_configuration.assert_called_once()
    kwargs = mock_client.put_bucket_lifecycle_configuration.call_args.kwargs
    assert kwargs["Bucket"] == "podcastrag-backup"
    rules = kwargs["LifecycleConfiguration"]["Rules"]
    assert len(rules) == 4
    assert {r["ID"] for r in rules} == EXPECTED_RULE_IDS

    by_id = {r["ID"]: r for r in rules}
    assert by_id["daily-7d"]["Expiration"]["Days"] == 7
    assert by_id["weekly-28d"]["Expiration"]["Days"] == 28
    assert by_id["monthly-365d"]["Expiration"]["Days"] == 365
    # PutBucketLifecycleConfiguration overwrites the whole rule set, so the
    # abort rule has to be shipped explicitly or R2's default is erased.
    abort = by_id["abort-incomplete-multipart-1d"]
    assert abort["AbortIncompleteMultipartUpload"]["DaysAfterInitiation"] == 1
    for rule in rules:
        assert rule["Status"] == "Enabled"


def test_apply_lifecycle_policy_is_idempotent():
    mock_client = MagicMock()
    apply_lifecycle_policy(mock_client, "b")
    apply_lifecycle_policy(mock_client, "b")

    first, second = mock_client.put_bucket_lifecycle_configuration.call_args_list
    assert first.kwargs == second.kwargs


def test_verify_lifecycle_policy_all_rules_present():
    mock_client = MagicMock()
    mock_client.get_bucket_lifecycle_configuration.return_value = {
        "Rules": [{"ID": rid} for rid in EXPECTED_RULE_IDS]
    }
    matched, actual = verify_lifecycle_policy(mock_client, "b")
    assert matched is True
    assert set(actual) == EXPECTED_RULE_IDS


def test_verify_lifecycle_policy_missing_rule():
    mock_client = MagicMock()
    mock_client.get_bucket_lifecycle_configuration.return_value = {
        "Rules": [{"ID": "daily-7d"}, {"ID": "weekly-28d"}]
    }
    matched, actual = verify_lifecycle_policy(mock_client, "b")
    assert matched is False
    assert actual == ["daily-7d", "weekly-28d"]


def test_verify_lifecycle_policy_propagates_client_error():
    """AccessDenied must reach the caller — swallowing it hid this bug for 3.5 months."""
    mock_client = MagicMock()
    mock_client.get_bucket_lifecycle_configuration.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "Access Denied"}}, "GetBucketLifecycleConfiguration"
    )
    try:
        verify_lifecycle_policy(mock_client, "b")
    except ClientError as exc:
        assert exc.response["Error"]["Code"] == "AccessDenied"
    else:  # pragma: no cover
        raise AssertionError("expected ClientError to propagate")


# --------------------------------------------------------------------------
# 5.2 verification state persistence
# --------------------------------------------------------------------------


def test_read_verify_state_returns_none_when_absent():
    mock_client = MagicMock()
    mock_client.get_object.side_effect = ClientError(
        {"Error": {"Code": "NoSuchKey"}}, "GetObject"
    )
    assert read_verify_state(mock_client, "b") is None


def test_read_verify_state_reads_recorded_outcome():
    for outcome in ("ok", "failed"):
        mock_client = MagicMock()
        body = MagicMock()
        body.read.return_value = json.dumps({"outcome": outcome}).encode()
        mock_client.get_object.return_value = {"Body": body}
        assert read_verify_state(mock_client, "b") == outcome


def test_read_verify_state_rejects_garbage():
    mock_client = MagicMock()
    body = MagicMock()
    body.read.return_value = b"not json"
    mock_client.get_object.return_value = {"Body": body}
    assert read_verify_state(mock_client, "b") is None


def test_write_verify_state_uses_state_key():
    mock_client = MagicMock()
    write_verify_state(mock_client, "b", "failed")

    kwargs = mock_client.put_object.call_args.kwargs
    assert kwargs["Key"] == _STATE_KEY == "_state/lifecycle_verify.json"
    assert json.loads(kwargs["Body"])["outcome"] == "failed"


# --------------------------------------------------------------------------
# 5.3 sweep_retention core behaviour
# --------------------------------------------------------------------------


def test_sweep_deletes_excess_daily_keeping_newest():
    mock_client = MagicMock()
    mock_client.list_objects_v2.side_effect = _prefix_router(
        {"daily/": _daily_keys(12)}
    )
    mock_client.delete_objects.return_value = {
        "Deleted": [{"Key": f"daily/2026-05-{d:02d}.dump.age"} for d in range(1, 6)]
    }

    result = sweep_retention(mock_client, "b")

    assert result["prefixes"]["daily"]["retained"] == 7
    assert result["prefixes"]["daily"]["deleted"] == 5
    # newest 7 = 06..12, so 01..05 go
    assert sorted(result["deleted_keys"]) == [
        f"daily/2026-05-{d:02d}.dump.age" for d in range(1, 6)
    ]
    assert result["needs_review"] is False
    assert result["errors"] == []


def test_sweep_skips_prefix_at_exactly_the_limit():
    mock_client = MagicMock()
    mock_client.list_objects_v2.side_effect = _prefix_router({"daily/": _daily_keys(7)})

    result = sweep_retention(mock_client, "b")

    mock_client.delete_objects.assert_not_called()
    assert result["prefixes"]["daily"] == {
        "retained": 7,
        "deleted": 0,
        "deleted_keys": [],
    }


def test_sweep_skips_under_populated_prefix():
    """weekly/ has 1 object and monthly/ has 4 — both below their limits."""
    mock_client = MagicMock()
    mock_client.list_objects_v2.side_effect = _prefix_router(
        {
            "weekly/": [_obj("weekly/2026-05-10.dump.age")],
            "monthly/": [
                _obj(f"monthly/2026-0{m}-01.dump.age") for m in range(5, 9)
            ],
        }
    )

    result = sweep_retention(mock_client, "b")

    mock_client.delete_objects.assert_not_called()
    assert result["prefixes"]["weekly"]["deleted"] == 0
    assert result["prefixes"]["monthly"]["deleted"] == 0


def test_sweep_never_deletes_malformed_keys():
    mock_client = MagicMock()
    stray = [
        _obj("daily/not-a-date.dump.age"),
        _obj("daily/2026-05-01.tar.gz"),
        _obj(_STATE_KEY),
    ]
    mock_client.list_objects_v2.side_effect = _prefix_router(
        {"daily/": _daily_keys(9) + stray}
    )
    mock_client.delete_objects.return_value = {"Deleted": []}

    result = sweep_retention(mock_client, "b")

    deleted = set(result["deleted_keys"]) | {
        k for p in result["prefixes"].values() for k in p["deleted_keys"]
    }
    for obj in stray:
        assert obj["Key"] not in deleted
        assert obj["Key"] in result["unrecognised"]
    # 9 well-formed dailies, newest 7 kept
    assert result["prefixes"]["daily"]["deleted"] == 2


def test_sweep_follows_pagination():
    mock_client = MagicMock()
    page_one = {
        "Contents": _daily_keys(6, start_day=1),
        "IsTruncated": True,
        "NextContinuationToken": "tok",
    }
    page_two = {"Contents": _daily_keys(4, start_day=7), "IsTruncated": False}

    def _side_effect(**kwargs):
        if kwargs.get("Prefix") != "daily/":
            return _listing([])
        return page_two if kwargs.get("ContinuationToken") == "tok" else page_one

    mock_client.list_objects_v2.side_effect = _side_effect
    mock_client.delete_objects.return_value = {"Deleted": []}

    result = sweep_retention(mock_client, "b")

    # 10 objects seen across both pages → 3 deleted
    assert result["prefixes"]["daily"]["retained"] == 7
    assert result["prefixes"]["daily"]["deleted"] == 3


# --------------------------------------------------------------------------
# 5.4 safety valve
# --------------------------------------------------------------------------


def test_sweep_safety_valve_blocks_oversized_deletion():
    """21 pending deletions (> _MAX_SWEEP_DELETES) must delete nothing."""
    mock_client = MagicMock()
    mock_client.list_objects_v2.side_effect = _prefix_router(
        {"daily/": _daily_keys(7 + _MAX_SWEEP_DELETES + 1)}
    )

    result = sweep_retention(mock_client, "b")

    mock_client.delete_objects.assert_not_called()
    assert result["needs_review"] is True
    assert len(result["pending_keys"]) == _MAX_SWEEP_DELETES + 1
    assert result["deleted_keys"] == []
    assert result["prefixes"]["daily"]["deleted"] == 0


def test_sweep_deletes_at_exactly_the_safety_limit():
    mock_client = MagicMock()
    mock_client.list_objects_v2.side_effect = _prefix_router(
        {"daily/": _daily_keys(7 + _MAX_SWEEP_DELETES)}
    )
    mock_client.delete_objects.return_value = {"Deleted": []}

    result = sweep_retention(mock_client, "b")

    mock_client.delete_objects.assert_called_once()
    assert result["needs_review"] is False
    assert len(result["deleted_keys"]) == _MAX_SWEEP_DELETES


# --------------------------------------------------------------------------
# 5.5 delete_objects reports failures without raising
# --------------------------------------------------------------------------


def test_sweep_collects_per_key_delete_errors():
    mock_client = MagicMock()
    mock_client.list_objects_v2.side_effect = _prefix_router({"daily/": _daily_keys(9)})
    mock_client.delete_objects.return_value = {
        "Deleted": [{"Key": "daily/2026-05-01.dump.age"}],
        "Errors": [
            {
                "Key": "daily/2026-05-02.dump.age",
                "Code": "AccessDenied",
                "Message": "Access Denied",
            }
        ],
    }

    result = sweep_retention(mock_client, "b")

    assert len(result["errors"]) == 1
    assert result["errors"][0]["Key"] == "daily/2026-05-02.dump.age"
    assert result["errors"][0]["Code"] == "AccessDenied"
    assert result["deleted_keys"] == ["daily/2026-05-01.dump.age"]


# --------------------------------------------------------------------------
# 5.6 stale multipart cleanup
# --------------------------------------------------------------------------


def test_abort_stale_multipart_aborts_only_old_uploads():
    now = datetime.now(timezone.utc)
    mock_client = MagicMock()
    mock_client.list_multipart_uploads.return_value = {
        "Uploads": [
            {
                "Key": "daily/2026-08-20.dump.age",
                "UploadId": "old",
                "Initiated": now - timedelta(hours=30),
            },
            {
                "Key": "daily/2026-08-22.dump.age",
                "UploadId": "fresh",
                "Initiated": now - timedelta(hours=1),
            },
        ],
        "IsTruncated": False,
    }

    aborted = abort_stale_multipart_uploads(mock_client, "b")

    assert aborted == 1
    mock_client.abort_multipart_upload.assert_called_once_with(
        Bucket="b", Key="daily/2026-08-20.dump.age", UploadId="old"
    )


def test_abort_stale_multipart_noop_when_no_uploads_key():
    mock_client = MagicMock()
    mock_client.list_multipart_uploads.return_value = {"IsTruncated": False}

    assert abort_stale_multipart_uploads(mock_client, "b") == 0
    mock_client.abort_multipart_upload.assert_not_called()


def test_abort_stale_multipart_follows_pagination():
    now = datetime.now(timezone.utc)
    stale = lambda k, u: {  # noqa: E731
        "Key": k,
        "UploadId": u,
        "Initiated": now - timedelta(days=2),
    }
    mock_client = MagicMock()
    mock_client.list_multipart_uploads.side_effect = [
        {
            "Uploads": [stale("a", "1")],
            "IsTruncated": True,
            "NextKeyMarker": "a",
            "NextUploadIdMarker": "1",
        },
        {"Uploads": [stale("b", "2")], "IsTruncated": False},
    ]

    assert abort_stale_multipart_uploads(mock_client, "b") == 2


# --------------------------------------------------------------------------
# 5.7 usage accounting
# --------------------------------------------------------------------------


def test_bucket_usage_counts_and_sums_across_prefixes():
    mock_client = MagicMock()
    mock_client.list_objects_v2.side_effect = _prefix_router(
        {
            "daily/": [_obj("daily/2026-08-21.dump.age", 100), _obj("daily/2026-08-20.dump.age", 200)],
            "weekly/": [_obj("weekly/2026-05-10.dump.age", 300)],
            "monthly/": [],
        }
    )

    usage = bucket_usage(mock_client, "b")

    assert usage["object_count"] == 3
    assert usage["total_bytes"] == 600
    assert usage["prefixes"]["daily"] == {"count": 2, "bytes": 300}
    assert usage["prefixes"]["weekly"] == {"count": 1, "bytes": 300}
    assert usage["prefixes"]["monthly"] == {"count": 0, "bytes": 0}


def test_parse_recipients():
    assert parse_recipients(None) == []
    assert parse_recipients("") == []
    assert parse_recipients("age1abc") == ["age1abc"]
    assert parse_recipients("age1abc, age1def , age1ghi") == [
        "age1abc",
        "age1def",
        "age1ghi",
    ]
