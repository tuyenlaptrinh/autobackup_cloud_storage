#!/usr/bin/python
# coding: utf-8
"""Unified storage config, status, test, and upload."""

from __future__ import print_function
import os
import re

from .paths import get_config, save_config, ok, fail, TOKEN_FILE, DEFAULT_MSGRAPH
from .storage_providers import list_providers, get_provider, is_s3, is_msgraph


DEFAULT_S3 = {
    "endpoint": "",
    "region": "us-east-1",
    "access_key": "",
    "secret_key": "",
    "bucket": "",
    "prefix": "aapanel-backups/",
    "path_style": False,
}


def _ensure_storage_shape(cfg):
    """Migrate legacy flat Drive config into nested storage shape."""
    changed = False
    if "storage_provider" not in cfg:
        cfg["storage_provider"] = "gdrive" if cfg.get("linked") else "gdrive"
        changed = True
    if "s3" not in cfg or not isinstance(cfg.get("s3"), dict):
        cfg["s3"] = dict(DEFAULT_S3)
        changed = True
    else:
        merged = dict(DEFAULT_S3)
        merged.update(cfg["s3"])
        cfg["s3"] = merged
    if "msgraph" not in cfg or not isinstance(cfg.get("msgraph"), dict):
        cfg["msgraph"] = dict(DEFAULT_MSGRAPH)
        changed = True
    else:
        merged = dict(DEFAULT_MSGRAPH)
        merged.update(cfg["msgraph"])
        if str(merged.get("tenant") or "").lower() in ("common", "consumers", ""):
            merged["tenant"] = "organizations"
        cfg["msgraph"] = merged
    if changed:
        save_config(cfg)
    return cfg


def get_storage_config():
    cfg = _ensure_storage_shape(get_config())
    return cfg


def save_storage_provider(provider_id):
    meta = get_provider(provider_id)
    if not meta:
        return fail("Unknown provider.")
    cfg = get_storage_config()
    cfg["storage_provider"] = provider_id
    # Apply preset defaults for empty S3 endpoint/region when switching
    if meta.get("kind") == "s3":
        s3 = cfg.get("s3") or dict(DEFAULT_S3)
        if meta.get("endpoint") and (
            not s3.get("endpoint")
            or "<" in str(s3.get("endpoint"))
            or s3.get("endpoint") in (
                "https://<ACCOUNT_ID>.r2.cloudflarestorage.com",
                "https://s3.<REGION>.backblazeb2.com",
                "https://<REGION>.digitaloceanspaces.com",
                "https://<REGION>.linodeobjects.com",
                "https://s3.<REGION>.wasabisys.com",
                "https://minio.example.com",
            )
        ):
            # Keep placeholder only as hint in UI; don't overwrite user value if customized
            if not s3.get("endpoint"):
                s3["endpoint"] = meta.get("endpoint") or ""
        if not s3.get("region") and meta.get("region"):
            s3["region"] = meta["region"]
        if "path_style" not in s3 or s3.get("path_style") is None:
            s3["path_style"] = bool(meta.get("path_style"))
        cfg["s3"] = s3
    save_config(cfg)
    return ok("Storage provider set to {}.".format(meta["name"]), storage_status_data(cfg))


def save_s3_config(payload):
    cfg = get_storage_config()
    s3 = dict(cfg.get("s3") or DEFAULT_S3)
    for key in ("endpoint", "region", "access_key", "bucket", "prefix"):
        if key in payload and payload[key] is not None:
            s3[key] = str(payload[key]).strip()
    # Keep existing secret when UI sends blank
    if "secret_key" in payload and payload["secret_key"] is not None:
        new_secret = str(payload["secret_key"]).strip()
        if new_secret:
            s3["secret_key"] = new_secret
    if "path_style" in payload:
        v = payload["path_style"]
        if isinstance(v, bool):
            s3["path_style"] = v
        else:
            s3["path_style"] = str(v).lower() in ("1", "true", "yes", "on")
    if not s3.get("bucket"):
        return fail("Bucket is required.")
    if not s3.get("access_key") or not s3.get("secret_key"):
        return fail("Access Key and Secret Key are required.")
    cfg["s3"] = s3
    if payload.get("provider") and is_s3(payload.get("provider")):
        cfg["storage_provider"] = payload.get("provider")
    elif not is_s3(cfg.get("storage_provider")):
        cfg["storage_provider"] = "s3_compat"
    save_config(cfg)
    return ok("Object storage settings saved.", storage_status_data(cfg))


def storage_status_data(cfg=None):
    cfg = cfg or get_storage_config()
    provider_id = cfg.get("storage_provider") or "gdrive"
    meta = get_provider(provider_id)
    ready = False
    detail = ""

    if meta.get("kind") == "gdrive":
        linked = bool(cfg.get("linked")) and os.path.exists(TOKEN_FILE)
        if linked:
            try:
                from .drive_auth import get_credentials

                ready = get_credentials() is not None
            except Exception:
                ready = False
        detail = cfg.get("account_email") or ""
    elif meta.get("kind") == "msgraph":
        from .msgraph_auth import msgraph_status, get_access_token

        mg_st = msgraph_status()
        ready = bool(mg_st.get("linked") and get_access_token())
        if provider_id == "sharepoint" and ready and not (cfg.get("msgraph") or {}).get("site_url"):
            ready = False
        detail = mg_st.get("email") or ""
        if provider_id == "sharepoint" and (cfg.get("msgraph") or {}).get("site_url"):
            detail = (detail + " · " if detail else "") + (cfg.get("msgraph") or {}).get("site_url")
    else:
        s3 = cfg.get("s3") or {}
        ready = bool(s3.get("bucket") and s3.get("access_key") and s3.get("secret_key"))
        detail = s3.get("bucket") or ""

    s3 = cfg.get("s3") or dict(DEFAULT_S3)
    # Never send full secret to UI — mask
    secret = s3.get("secret_key") or ""
    masked = ("*" * min(8, len(secret))) if secret else ""

    from .msgraph_auth import msgraph_status as _mg_status

    mg_ui = _mg_status()
    mg_secret = bool((cfg.get("msgraph") or {}).get("client_secret"))

    return {
        "provider": provider_id,
        "provider_name": meta.get("name"),
        "kind": meta.get("kind"),
        "ready": ready,
        "detail": detail,
        "providers": list_providers(),
        "drive": {
            "linked": bool(cfg.get("linked")) and os.path.exists(TOKEN_FILE),
            "email": cfg.get("account_email", ""),
            "client_configured": bool(cfg.get("client_id") and cfg.get("client_secret"))
            or os.path.exists(os.path.join(os.path.dirname(TOKEN_FILE), "credentials.json")),
            "client_id": cfg.get("client_id", ""),
            "credentials_uploaded": os.path.exists(
                os.path.join(os.path.dirname(TOKEN_FILE), "credentials.json")
            ),
            "drive_folder_name": cfg.get("drive_folder_name", "aaPanel Backups"),
            "drive_folder_id": cfg.get("drive_folder_id", ""),
            "token_valid": ready if meta.get("kind") == "gdrive" else False,
        },
        "msgraph": {
            "linked": bool(mg_ui.get("linked")),
            "email": mg_ui.get("email") or "",
            "client_configured": bool(mg_ui.get("client_configured")),
            "client_id": mg_ui.get("client_id") or "",
            "client_secret_set": mg_secret,
            "tenant": mg_ui.get("tenant") or "organizations",
            "folder_name": mg_ui.get("folder_name") or "aaPanel Backups",
            "site_url": mg_ui.get("site_url") or "",
            "token_valid": bool(mg_ui.get("token_valid")),
            "work_school_only": True,
        },
        "s3": {
            "endpoint": s3.get("endpoint", ""),
            "region": s3.get("region", "us-east-1"),
            "access_key": s3.get("access_key", ""),
            "secret_key_set": bool(secret),
            "secret_key_masked": masked,
            "bucket": s3.get("bucket", ""),
            "prefix": s3.get("prefix", "aapanel-backups/"),
            "path_style": bool(s3.get("path_style", False)),
        },
    }


def get_storage_status():
    return ok("OK", storage_status_data())


def test_storage(provider_id=None):
    cfg = get_storage_config()
    pid = provider_id or cfg.get("storage_provider") or "gdrive"
    meta = get_provider(pid)
    try:
        if meta.get("kind") == "gdrive":
            from .drive_auth import get_credentials
            from .drive_upload import get_drive_service, ensure_backup_folder

            if not get_credentials():
                return fail("Google Drive is not linked.")
            service = get_drive_service()
            folder_id = ensure_backup_folder(service)
            return ok("Google Drive OK.", {"folder_id": folder_id})
        if meta.get("kind") == "msgraph":
            from . import msgraph_upload

            info = msgraph_upload.test_connection(pid)
            return ok("{} connection OK.".format(meta.get("name")), info)
        from . import storage_s3

        storage_s3.test_connection(cfg.get("s3") or {})
        return ok("{} connection OK.".format(meta.get("name")))
    except Exception as e:
        return fail(str(e))


def upload_backup(local_path, remote_name, schedule_name=None, provider_id=None):
    """Upload archive using active (or override) storage provider."""
    cfg = get_storage_config()
    pid = provider_id or cfg.get("storage_provider") or "gdrive"
    meta = get_provider(pid)

    if meta.get("kind") == "gdrive":
        from .drive_upload import upload_file as drive_upload

        result = drive_upload(
            local_path,
            remote_name=remote_name,
            schedule_name=schedule_name,
        )
        result["provider"] = "gdrive"
        return result

    if meta.get("kind") == "msgraph":
        from . import msgraph_upload

        result = msgraph_upload.upload_file(
            local_path,
            remote_name=remote_name,
            schedule_name=schedule_name,
            provider_id=pid,
        )
        result["provider"] = pid
        return result

    from . import storage_s3

    result = storage_s3.upload_file(
        local_path,
        remote_name=remote_name,
        cfg=cfg.get("s3") or {},
        schedule_name=schedule_name,
    )
    result["provider"] = pid
    return result


def prune_backups(archive_prefix, keep, schedule_name=None, provider_id=None, uploaded=None):
    """Keep only the newest `keep` archives named {archive_prefix}_YYYYMMDD_HHMMSS.zip."""
    if keep <= 0 or not archive_prefix:
        return []
    name_regex = re.compile(r"^{}_\d{{8}}_\d{{6}}\.zip$".format(re.escape(archive_prefix)))
    cfg = get_storage_config()
    pid = provider_id or cfg.get("storage_provider") or "gdrive"
    meta = get_provider(pid)

    if meta.get("kind") == "gdrive":
        from .drive_upload import prune_backups as drive_prune

        folder_id = (uploaded or {}).get("folder_id")
        return drive_prune(folder_id, name_regex, keep)

    if meta.get("kind") == "msgraph":
        from . import msgraph_upload

        folder_id = (uploaded or {}).get("folder_id")
        return msgraph_upload.prune_backups(folder_id, name_regex, keep, provider_id=pid)

    from . import storage_s3

    return storage_s3.prune_backups(cfg.get("s3") or {}, schedule_name, name_regex, keep)
