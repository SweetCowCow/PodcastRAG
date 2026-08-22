"""Cloudflare R2 client wrapper for the off-site DB backup pipeline.

Separate from `app.services.storage` (which targets the audio bucket) to keep
token blast radius and lifecycle policies isolated. Backup-side env vars are
all `R2_BACKUP_*` prefixed so they don't collide with the audio bucket vars.

`get_r2_backup_client()` returns None when settings are missing, so module
import never fails in environments without R2 (local dev, CI without secrets).
Callers must handle the None case explicitly.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone

import boto3
from botocore.client import BaseClient, Config

from app.core.config import settings

logger = logging.getLogger(__name__)

# Retention policy: 7 daily / 4 weekly / 12 monthly.
#
# fix-backup-retention: these rules used to be the ONLY retention mechanism —
# the original comment here read "the app does not need to walk and delete
# artifacts". That was wrong in practice: the R2 API token only carries
# Object-level permissions, so every `PutBucketLifecycleConfiguration` call
# was rejected with AccessDenied and swallowed by a bare except. Nothing
# expired for 107 days (108 objects / 472 GB, vs. a designed ~23 / 12 GB).
#
# Retention is now enforced by `sweep_retention()` below. These rules stay so
# that they take effect the moment the token is upgraded, and they carry the
# AbortIncompleteMultipartUpload rule that R2's bucket default provides —
# `PutBucketLifecycleConfiguration` has whole-set-overwrite semantics, so
# shipping only the three Expiration rules actively erased that default.
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
        {
            "ID": "abort-incomplete-multipart-1d",
            "Status": "Enabled",
            "Filter": {"Prefix": ""},
            "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 1},
        },
    ]
}

_EXPECTED_RULE_IDS = frozenset(r["ID"] for r in _LIFECYCLE_RULES["Rules"])

# Artifact keys the sweep is allowed to touch. Anything else in the bucket
# (including `_STATE_KEY` below) is left alone — see `sweep_retention`.
_KEY_RE = re.compile(r"^(daily|weekly|monthly)/(\d{4}-\d{2}-\d{2})\.dump\.age$")

_RETENTION = {"daily": 7, "weekly": 4, "monthly": 12}

# Safety valve. A sweep that wants to delete more than this refuses to act and
# asks for a human instead. Steady state deletes 1 object/day; anything near
# this number means the bucket is in a state nobody has looked at yet.
_MAX_SWEEP_DELETES = 20

# Where the lifecycle verification outcome is remembered between runs. Lives in
# R2 rather than worker memory because the container is restarted freely.
_STATE_KEY = "_state/lifecycle_verify.json"

# delete_objects accepts at most 1000 keys per call.
_DELETE_BATCH = 1000


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
    """Write the lifecycle rules to the bucket.

    Deliberately does NOT catch exceptions: the caller owns the alerting
    decision. Swallowing the error here is what hid the AccessDenied for
    three and a half months.
    """
    client.put_bucket_lifecycle_configuration(
        Bucket=bucket,
        LifecycleConfiguration=_LIFECYCLE_RULES,
    )
    logger.info("r2_backup: lifecycle policy applied to bucket=%s", bucket)


def verify_lifecycle_policy(client: BaseClient, bucket: str) -> tuple[bool, list[str]]:
    """Read the policy back and check every expected rule ID survived.

    Returns (all expected IDs present, actual rule IDs). Raises through on
    ClientError/BotoCoreError so the caller can report the error code.
    """
    resp = client.get_bucket_lifecycle_configuration(Bucket=bucket)
    actual = [r.get("ID", "") for r in resp.get("Rules", []) or []]
    return _EXPECTED_RULE_IDS.issubset(set(actual)), actual


def read_verify_state(client: BaseClient, bucket: str) -> str | None:
    """Last recorded lifecycle verification outcome: "ok", "failed", or None.

    None means "never recorded" — which the caller must treat as a state
    change so the first failure still alerts.
    """
    try:
        body = client.get_object(Bucket=bucket, Key=_STATE_KEY)["Body"].read()
    except Exception:  # noqa: BLE001 — missing/unreadable state is not fatal
        logger.info("r2_backup: no previous lifecycle verify state at %s", _STATE_KEY)
        return None
    try:
        outcome = json.loads(body).get("outcome")
    except (ValueError, TypeError, AttributeError):
        logger.warning("r2_backup: unreadable lifecycle verify state, treating as None")
        return None
    return outcome if outcome in ("ok", "failed") else None


def write_verify_state(client: BaseClient, bucket: str, outcome: str) -> None:
    """Persist the lifecycle verification outcome for the next run to compare."""
    payload = json.dumps(
        {"outcome": outcome, "checked_at": datetime.now(timezone.utc).isoformat()}
    ).encode()
    client.put_object(
        Bucket=bucket, Key=_STATE_KEY, Body=payload, ContentType="application/json"
    )


def _list_prefix(client: BaseClient, bucket: str, prefix: str) -> list[dict]:
    """List every object under a prefix, following pagination."""
    objects: list[dict] = []
    token: str | None = None
    while True:
        kwargs = {"Bucket": bucket, "Prefix": prefix}
        if token:
            kwargs["ContinuationToken"] = token
        resp = client.list_objects_v2(**kwargs)
        objects.extend(resp.get("Contents", []) or [])
        if not resp.get("IsTruncated"):
            return objects
        token = resp.get("NextContinuationToken")
        if not token:
            return objects


def sweep_retention(client: BaseClient, bucket: str) -> dict:
    """Delete artifacts beyond the per-prefix retention limits.

    Returns a dict describing what happened:
        prefixes      per-prefix {retained, deleted, deleted_keys}
        deleted_keys  every key actually deleted
        pending_keys  keys the sweep WANTED to delete but did not (safety valve)
        needs_review  True when the safety valve tripped — nothing was deleted
        unrecognised  keys that did not match the artifact naming pattern
        errors        per-key failures reported by delete_objects

    `delete_objects` reports per-key failures in an `Errors` array WITHOUT
    raising, so those are collected into `errors` — an unchecked Errors array
    is exactly the silent-retention-failure mode this change exists to remove.
    """
    result: dict = {
        "prefixes": {},
        "deleted_keys": [],
        "pending_keys": [],
        "needs_review": False,
        "unrecognised": [],
        "errors": [],
    }

    to_delete: list[str] = []
    for prefix, limit in _RETENTION.items():
        objects = _list_prefix(client, bucket, f"{prefix}/")

        dated: list[tuple[str, str]] = []
        for obj in objects:
            key = obj.get("Key", "")
            match = _KEY_RE.match(key)
            if match:
                dated.append((match.group(2), key))
            else:
                result["unrecognised"].append(key)
                logger.warning("r2_backup: sweep ignoring unrecognised key %s", key)

        dated.sort(key=lambda pair: pair[0], reverse=True)

        if len(dated) <= limit:
            logger.info(
                "r2_backup: sweep prefix=%s count=%d <= limit=%d — skipped",
                prefix,
                len(dated),
                limit,
            )
            result["prefixes"][prefix] = {
                "retained": len(dated),
                "deleted": 0,
                "deleted_keys": [],
            }
            continue

        doomed = [key for _, key in dated[limit:]]
        to_delete.extend(doomed)
        result["prefixes"][prefix] = {
            "retained": limit,
            "deleted": len(doomed),
            "deleted_keys": doomed,
        }

    if not to_delete:
        logger.info("r2_backup: sweep found nothing to delete")
        return result

    if len(to_delete) > _MAX_SWEEP_DELETES:
        # Refuse to act. A sweep this large means the bucket drifted into a
        # state no human has reviewed; deleting the only off-site backup
        # unattended is worse than paying for another day of storage.
        logger.warning(
            "r2_backup: sweep wants to delete %d objects (max %d) — needs review",
            len(to_delete),
            _MAX_SWEEP_DELETES,
        )
        result["needs_review"] = True
        result["pending_keys"] = to_delete
        for stats in result["prefixes"].values():
            stats["deleted"] = 0
            stats["deleted_keys"] = []
        return result

    for start in range(0, len(to_delete), _DELETE_BATCH):
        batch = to_delete[start : start + _DELETE_BATCH]
        resp = client.delete_objects(
            Bucket=bucket,
            Delete={"Objects": [{"Key": k} for k in batch], "Quiet": False},
        )
        deleted = [d.get("Key") for d in resp.get("Deleted", []) or []]
        errors = resp.get("Errors", []) or []
        # Quiet=False is not universally honoured; fall back to assuming the
        # batch succeeded except for whatever Errors names.
        if not deleted:
            failed_keys = {e.get("Key") for e in errors}
            deleted = [k for k in batch if k not in failed_keys]
        result["deleted_keys"].extend(deleted)
        for err in errors:
            result["errors"].append(
                {
                    "Key": err.get("Key"),
                    "Code": err.get("Code"),
                    "Message": err.get("Message"),
                }
            )

    logger.info(
        "r2_backup: sweep deleted %d objects, %d errors, keys=%s",
        len(result["deleted_keys"]),
        len(result["errors"]),
        result["deleted_keys"],
    )
    return result


def abort_stale_multipart_uploads(
    client: BaseClient, bucket: str, older_than_hours: int = 24
) -> int:
    """Abort incomplete multipart uploads older than the cutoff.

    R2 bills these but does not return them from ListObjectsV2, so they are
    invisible to every other check in this module. Returns the number aborted.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)
    aborted = 0
    key_marker: str | None = None
    upload_marker: str | None = None

    while True:
        kwargs: dict = {"Bucket": bucket}
        if key_marker:
            kwargs["KeyMarker"] = key_marker
        if upload_marker:
            kwargs["UploadIdMarker"] = upload_marker
        resp = client.list_multipart_uploads(**kwargs)

        for upload in resp.get("Uploads", []) or []:
            initiated = upload.get("Initiated")
            if initiated is None or initiated > cutoff:
                continue
            client.abort_multipart_upload(
                Bucket=bucket, Key=upload["Key"], UploadId=upload["UploadId"]
            )
            aborted += 1
            logger.info(
                "r2_backup: aborted stale upload key=%s initiated=%s",
                upload["Key"],
                initiated,
            )

        if not resp.get("IsTruncated"):
            break
        key_marker = resp.get("NextKeyMarker")
        upload_marker = resp.get("NextUploadIdMarker")
        if not key_marker and not upload_marker:
            break

    logger.info("r2_backup: aborted %d stale multipart uploads", aborted)
    return aborted


def bucket_usage(client: BaseClient, bucket: str) -> dict:
    """Absolute object count and byte total across the artifact prefixes.

    This is the check that would have caught the original failure: the
    day-over-day size ratio never fired because keeping one extra copy a day
    is a sub-1% daily increase.
    """
    per_prefix: dict[str, dict] = {}
    total_objects = 0
    total_bytes = 0

    for prefix in _RETENTION:
        objects = _list_prefix(client, bucket, f"{prefix}/")
        size = sum(o.get("Size", 0) for o in objects)
        per_prefix[prefix] = {"count": len(objects), "bytes": size}
        total_objects += len(objects)
        total_bytes += size

    return {
        "prefixes": per_prefix,
        "object_count": total_objects,
        "total_bytes": total_bytes,
    }


def parse_recipients(raw: str | None) -> list[str]:
    """Parse comma-separated age public keys into a list."""
    if not raw:
        return []
    return [s.strip() for s in raw.split(",") if s.strip()]
