"""Unit tests for R2 backup client wrapper.

Verifies lifecycle policy JSON shape matches Decision 4 (7 daily / 4 weekly /
12 monthly) and the no-op fallback when settings are unset.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.r2_backup_client import (
    apply_lifecycle_policy,
    get_r2_backup_client,
    parse_recipients,
)


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


def test_apply_lifecycle_policy_shape():
    mock_client = MagicMock()
    apply_lifecycle_policy(mock_client, "podcastrag-backup")

    mock_client.put_bucket_lifecycle_configuration.assert_called_once()
    kwargs = mock_client.put_bucket_lifecycle_configuration.call_args.kwargs
    assert kwargs["Bucket"] == "podcastrag-backup"
    rules = kwargs["LifecycleConfiguration"]["Rules"]
    assert len(rules) == 3

    by_prefix = {r["Filter"]["Prefix"]: r for r in rules}
    assert by_prefix["daily/"]["Expiration"]["Days"] == 7
    assert by_prefix["weekly/"]["Expiration"]["Days"] == 28
    assert by_prefix["monthly/"]["Expiration"]["Days"] == 365
    for rule in rules:
        assert rule["Status"] == "Enabled"


def test_parse_recipients():
    assert parse_recipients(None) == []
    assert parse_recipients("") == []
    assert parse_recipients("age1abc") == ["age1abc"]
    assert parse_recipients("age1abc, age1def , age1ghi") == [
        "age1abc",
        "age1def",
        "age1ghi",
    ]
