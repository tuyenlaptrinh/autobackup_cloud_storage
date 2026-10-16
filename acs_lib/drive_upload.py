#!/usr/bin/python
# coding: utf-8
"""Google Drive upload helpers."""

from __future__ import print_function
import os
import mimetypes

from .paths import get_config, save_config
from .drive_auth import get_credentials


def get_drive_service():
    creds = get_credentials()
    if not creds:
        raise RuntimeError("Google Drive is not linked or token is invalid.")
    from googleapiclient.discovery import build

    return build("drive", "v3", credentials=creds, cache_discovery=False)


def ensure_backup_folder(service=None):
    """Find or create the root backup folder on Drive; cache its id."""
    if service is None:
        service = get_drive_service()
    cfg = get_config()
    folder_id = cfg.get("drive_folder_id") or ""
    folder_name = cfg.get("drive_folder_name") or "aaPanel Backups"

    if folder_id:
        try:
            meta = service.files().get(fileId=folder_id, fields="id,name,trashed").execute()
            if not meta.get("trashed"):
                return folder_id
        except Exception:
            folder_id = ""

    query = (
        "mimeType='application/vnd.google-apps.folder' "
        "and name='{}' and trashed=false and 'root' in parents"
    ).format(folder_name.replace("'", "\\'"))
    results = (
        service.files()
        .list(q=query, spaces="drive", fields="files(id, name)", pageSize=5)
        .execute()
    )
    files = results.get("files", [])
    if files:
        folder_id = files[0]["id"]
    else:
        meta = {
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder",
        }
        created = service.files().create(body=meta, fields="id").execute()
        folder_id = created["id"]

    cfg["drive_folder_id"] = folder_id
    save_config(cfg)
    return folder_id


def ensure_subfolder(service, parent_id, name):
    query = (
        "mimeType='application/vnd.google-apps.folder' "
        "and name='{}' and trashed=false and '{}' in parents"
    ).format(name.replace("'", "\\'"), parent_id)
    results = (
        service.files()
        .list(q=query, spaces="drive", fields="files(id, name)", pageSize=5)
        .execute()
    )
    files = results.get("files", [])
    if files:
        return files[0]["id"]
    meta = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    created = service.files().create(body=meta, fields="id").execute()
    return created["id"]


def upload_file(local_path, remote_name=None, parent_folder_id=None, schedule_name=None):
    """Upload a local file to Drive. Returns dict with id, name, size."""
    if not os.path.exists(local_path):
        raise RuntimeError("File not found: {}".format(local_path))

    from googleapiclient.http import MediaFileUpload

    service = get_drive_service()
    root_id = ensure_backup_folder(service)
    parent = parent_folder_id or root_id
    if schedule_name:
        parent = ensure_subfolder(service, root_id, schedule_name)

    name = remote_name or os.path.basename(local_path)
    mime, _ = mimetypes.guess_type(local_path)
    if not mime:
        mime = "application/zip"

    media = MediaFileUpload(local_path, mimetype=mime, resumable=True, chunksize=8 * 1024 * 1024)
    meta = {"name": name, "parents": [parent]}
    request = service.files().create(body=meta, media_body=media, fields="id,name,size,webViewLink")

    response = None
    while response is None:
        status, response = request.next_chunk()
    return {
        "id": response.get("id"),
        "name": response.get("name"),
        "size": int(response.get("size") or 0),
        "webViewLink": response.get("webViewLink", ""),
        "folder_id": parent,
    }


def prune_backups(folder_id, name_regex, keep):
    """Delete all but the newest `keep` files in folder whose name matches name_regex."""
    if not folder_id or keep <= 0:
        return []
    service = get_drive_service()
    query = (
        "'{}' in parents and trashed=false "
        "and mimeType!='application/vnd.google-apps.folder'"
    ).format(folder_id)
    matched = []
    page_token = None
    while True:
        res = (
            service.files()
            .list(
                q=query,
                spaces="drive",
                fields="nextPageToken, files(id, name)",
                pageSize=1000,
                pageToken=page_token,
            )
            .execute()
        )
        for f in res.get("files", []):
            if name_regex.match(f.get("name") or ""):
                matched.append(f)
        page_token = res.get("nextPageToken")
        if not page_token:
            break

    # Names end in _YYYYMMDD_HHMMSS.zip, so lexical order is chronological
    matched.sort(key=lambda f: f["name"], reverse=True)
    deleted = []
    for f in matched[keep:]:
        service.files().delete(fileId=f["id"]).execute()
        deleted.append(f["name"])
    return deleted
