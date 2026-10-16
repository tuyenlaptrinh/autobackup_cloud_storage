#!/usr/bin/python
# coding: utf-8
"""S3-compatible object storage upload (AWS, R2, B2, Spaces, Linode, …)."""

from __future__ import print_function
import os
import mimetypes


def _import_boto3():
    try:
        import boto3
        from botocore.client import Config
        from botocore.exceptions import ClientError, BotoCoreError

        return boto3, Config, ClientError, BotoCoreError
    except ImportError:
        raise RuntimeError(
            "boto3 is not installed. Re-run install.sh or: pip install boto3"
        )


def build_client(cfg):
    boto3, Config, _, _ = _import_boto3()
    endpoint = (cfg.get("endpoint") or "").strip() or None
    region = (cfg.get("region") or "us-east-1").strip() or "us-east-1"
    access_key = (cfg.get("access_key") or "").strip()
    secret_key = (cfg.get("secret_key") or "").strip()
    path_style = bool(cfg.get("path_style", False))

    if not access_key or not secret_key:
        raise RuntimeError("Access Key and Secret Key are required.")

    addressing = "path" if path_style else "virtual"
    config = Config(
        signature_version="s3v4",
        s3={"addressing_style": addressing},
    )
    kwargs = {
        "service_name": "s3",
        "region_name": region,
        "aws_access_key_id": access_key,
        "aws_secret_access_key": secret_key,
        "config": config,
    }
    if endpoint:
        kwargs["endpoint_url"] = endpoint
    return boto3.client(**kwargs)


def test_connection(cfg):
    bucket = (cfg.get("bucket") or "").strip()
    if not bucket:
        raise RuntimeError("Bucket name is required.")
    client = build_client(cfg)
    # head_bucket is enough for most providers; fall back to list
    try:
        client.head_bucket(Bucket=bucket)
    except Exception:
        client.list_objects_v2(Bucket=bucket, MaxKeys=1)
    return True


def _folder_key(cfg, schedule_name=None):
    """Key prefix (no trailing slash) where a schedule's archives are stored."""
    prefix = (cfg.get("prefix") or "").strip().strip("/")
    key_parts = []
    if prefix:
        key_parts.append(prefix)
    if schedule_name:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in schedule_name)[:60]
        key_parts.append(safe)
    return "/".join(key_parts)


def upload_file(local_path, remote_name, cfg, schedule_name=None):
    if not os.path.exists(local_path):
        raise RuntimeError("File not found: {}".format(local_path))

    bucket = (cfg.get("bucket") or "").strip()
    if not bucket:
        raise RuntimeError("Bucket name is required.")

    folder = _folder_key(cfg, schedule_name)
    name = remote_name or os.path.basename(local_path)
    key = "{}/{}".format(folder, name) if folder else name

    mime, _ = mimetypes.guess_type(local_path)
    if not mime:
        mime = "application/zip"

    client = build_client(cfg)
    extra = {"ContentType": mime}
    client.upload_file(
        local_path,
        bucket,
        key,
        ExtraArgs=extra,
    )

    size = os.path.getsize(local_path)
    endpoint = (cfg.get("endpoint") or "").rstrip("/")
    # Best-effort public/console URL (may require auth)
    url = ""
    if endpoint:
        url = "{}/{}/{}".format(endpoint, bucket, key)
    else:
        region = cfg.get("region") or "us-east-1"
        url = "https://{}.s3.{}.amazonaws.com/{}".format(bucket, region, key)

    return {
        "id": key,
        "name": remote_name or os.path.basename(local_path),
        "size": size,
        "webViewLink": url,
        "bucket": bucket,
        "key": key,
    }


def prune_backups(cfg, schedule_name, name_regex, keep):
    """Delete all but the newest `keep` objects in the schedule folder matching name_regex."""
    if keep <= 0:
        return []
    bucket = (cfg.get("bucket") or "").strip()
    if not bucket:
        raise RuntimeError("Bucket name is required.")

    folder = _folder_key(cfg, schedule_name)
    list_prefix = folder + "/" if folder else ""
    client = build_client(cfg)

    matched = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=list_prefix):
        for obj in page.get("Contents", []) or []:
            key = obj.get("Key") or ""
            rest = key[len(list_prefix):]
            # Only direct children of the schedule folder
            if "/" in rest:
                continue
            if name_regex.match(rest):
                matched.append(key)

    # Names end in _YYYYMMDD_HHMMSS.zip, so lexical order is chronological
    matched.sort(reverse=True)
    to_delete = matched[keep:]
    for i in range(0, len(to_delete), 1000):
        batch = to_delete[i:i + 1000]
        client.delete_objects(
            Bucket=bucket,
            Delete={"Objects": [{"Key": k} for k in batch], "Quiet": True},
        )
    return [k.rsplit("/", 1)[-1] for k in to_delete]
