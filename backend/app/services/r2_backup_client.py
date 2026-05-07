"""Cloudflare R2 client wrapper for the off-site DB backup pipeline.

Separate from `app.services.storage` (which targets the audio bucket) to keep
token blast radius and lifecycle policies isolated. Backup-side env vars are
all `R2_BACKUP_*` prefixed so they don't collide with the audio bucket vars.

`get_r2_backup_client()` returns None when settings are missing, so module
import never fails in environments without R2 (local dev, CI without secrets).
Callers must handle the None case explicitly.
"""
from __future__ import annotations

import logging

import boto3
from botocore.client import BaseClient, Config

from app.core.config import settings

logger = logging.getLogger(__name__)

# Decision 4 — retention policy: 7 daily / 4 weekly / 12 monthly. Encoded as
# R2 lifecycle rules so the bucket itself enforces retention; the app does
# not need to walk and delete artifacts.
_LIFECYCLE_RULES = {
    "Rules": [
        {
            "ID": "daily-7d",
            "Status": "Enabled",
            "Filter": {"Prefix": "daily/"},
            "Expiration": {"Days": 7},
        },
        {
            "ID": "weekly-28d",
            "Status": "Enabled",
            "Filter": {"Prefix": "weekly/"},
            "Expiration": {"Days": 28},
        },
        {
            "ID": "monthly-365d",
            "Status": "Enabled",
            "Filter": {"Prefix": "monthly/"},
            "Expiration": {"Days": 365},
        },
    ]
}


def get_r2_backup_client() -> BaseClient | None:
    """Return a boto3 S3 client targeting R2 backup bucket, or None if unset."""
    if not (
        settings.r2_backup_endpoint_url
        and settings.r2_backup_access_key_id
        and settings.r2_backup_secret_access_key
        and settings.r2_backup_bucket
    ):
        return None
    return boto3.client(
        "s3",
        endpoint_url=settings.r2_backup_endpoint_url,
        aws_access_key_id=settings.r2_backup_access_key_id,
        aws_secret_access_key=settings.r2_backup_secret_access_key,
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )


def apply_lifecycle_policy(client: BaseClient, bucket: str) -> None:
    """Idempotently apply the 7/28/365-day lifecycle rules to the bucket."""
    client.put_bucket_lifecycle_configuration(
        Bucket=bucket,
        LifecycleConfiguration=_LIFECYCLE_RULES,
    )
    logger.info("r2_backup: lifecycle policy applied to bucket=%s", bucket)


def parse_recipients(raw: str | None) -> list[str]:
    """Parse comma-separated age public keys into a list."""
    if not raw:
        return []
    return [s.strip() for s in raw.split(",") if s.strip()]
