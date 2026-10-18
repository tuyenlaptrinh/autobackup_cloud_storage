#!/usr/bin/python
# coding: utf-8
"""Upload / prune backups on OneDrive Business and SharePoint via Microsoft Graph."""

from __future__ import print_function
import os
from urllib.parse import quote

from .msgraph_auth import get_access_token, _msgraph_cfg, _save_msgraph

GRAPH = "https://graph.microsoft.com/v1.0"
# Chunk size must be a multiple of 320 KiB for Graph upload sessions
CHUNK_SIZE = 320 * 1024 * 10  # 3.2 MiB


def _headers(token, extra=None):
    h = {"Authorization": "Bearer {}".format(token)}
    if extra:
        h.update(extra)
    return h


def _request(method, url, token, **kwargs):
    import requests

    headers = kwargs.pop("headers", None) or {}
    headers = _headers(token, headers)
    timeout = kwargs.pop("timeout", 120)
    r = requests.request(method, url, headers=headers, timeout=timeout, **kwargs)
    return r


def _json(method, url, token, **kwargs):
    r = _request(method, url, token, **kwargs)
    if r.status_code >= 400:
        raise RuntimeError("Graph {} {} → {}: {}".format(method, url, r.status_code, r.text[:500]))
    if r.status_code == 204 or not r.content:
        return {}
    return r.json()


def _msgraph_cfg_mut():
    return _msgraph_cfg()


def resolve_sharepoint_site(site_url, token=None):
    """Resolve https://contoso.sharepoint.com/sites/Name → site id + default drive id."""
    token = token or get_access_token()
    if not token:
        raise RuntimeError("Microsoft 365 is not linked.")
    site_url = (site_url or "").strip().rstrip("/")
    if not site_url:
        raise RuntimeError("SharePoint site URL is required.")

    # Accept hostname:/path form or full URL
    if "://" in site_url:
        from urllib.parse import urlparse

        parsed = urlparse(site_url)
        host = parsed.netloc
        path = parsed.path or "/"
    elif ":/" in site_url:
        host, path = site_url.split(":/", 1)
        path = "/" + path.lstrip("/")
    else:
        raise RuntimeError(
            "Invalid SharePoint URL. Example: https://contoso.sharepoint.com/sites/Backups"
        )

    # GET /sites/{hostname}:{server-relative-path}
    api = "{}/sites/{}:{}".format(GRAPH, host, path if path != "/" else "")
    data = _json("GET", api, token)
    site_id = data.get("id")
    if not site_id:
        raise RuntimeError("Could not resolve SharePoint site from URL.")
    drive = _json("GET", "{}/sites/{}/drive".format(GRAPH, site_id), token)
    drive_id = drive.get("id")
    if not drive_id:
        raise RuntimeError("Site has no default document library drive.")
    return site_id, drive_id, data.get("displayName") or data.get("name") or ""


def ensure_target_drive(provider_id="onedrive_business"):
    """Return (drive_root_api_prefix, folder_id_parent_for_schedules) metadata cached in config."""
    token = get_access_token()
    if not token:
        raise RuntimeError("Microsoft 365 is not linked. Complete OAuth first.")
    mg = _msgraph_cfg_mut()

    if provider_id == "sharepoint":
        site_url = mg.get("site_url") or ""
        if not site_url:
            raise RuntimeError("Save a SharePoint site URL first.")
        if not mg.get("site_id") or not mg.get("drive_id"):
            site_id, drive_id, _ = resolve_sharepoint_site(site_url, token)
            mg["site_id"] = site_id
            mg["drive_id"] = drive_id
            _save_msgraph(mg)
        drive_base = "{}/drives/{}".format(GRAPH, mg["drive_id"])
    else:
        # OneDrive Business — signed-in user's work drive
        drive_base = "{}/me/drive".format(GRAPH)

    folder_name = mg.get("folder_name") or "aaPanel Backups"
    folder_id = mg.get("folder_id") or ""
    if folder_id:
        try:
            meta = _json("GET", "{}/items/{}".format(drive_base, folder_id), token)
            if meta.get("id") and not meta.get("deleted"):
                return drive_base, folder_id, token
        except Exception:
            folder_id = ""

    # Find or create root backup folder under drive root
    children = _json(
        "GET",
        "{}/root/children?$select=id,name,folder&$top=200".format(drive_base),
        token,
    )
    for item in children.get("value") or []:
        if item.get("folder") is not None and item.get("name") == folder_name:
            folder_id = item["id"]
            break
    if not folder_id:
        created = _json(
            "POST",
            "{}/root/children".format(drive_base),
            token,
            headers={"Content-Type": "application/json"},
            json={
                "name": folder_name,
                "folder": {},
                "@microsoft.graph.conflictBehavior": "rename",
            },
        )
        folder_id = created.get("id")
        if not folder_id:
            raise RuntimeError("Failed to create backup folder on Microsoft drive.")

    mg["folder_id"] = folder_id
    _save_msgraph(mg)
    return drive_base, folder_id, token


def ensure_subfolder(drive_base, parent_id, name, token):
    safe = (name or "backup").strip() or "backup"
    listed = _json(
        "GET",
        "{}/items/{}/children?$select=id,name,folder&$top=200".format(drive_base, parent_id),
        token,
    )
    for item in listed.get("value") or []:
        if item.get("name") == safe and item.get("folder") is not None:
            return item["id"]

    created = _json(
        "POST",
        "{}/items/{}/children".format(drive_base, parent_id),
        token,
        headers={"Content-Type": "application/json"},
        json={
            "name": safe,
            "folder": {},
            "@microsoft.graph.conflictBehavior": "fail",
        },
    )
    return created["id"]


def _item_path_url(drive_base, parent_id, filename, suffix):
    """Build Graph path: /items/{parent-id}:/{filename}:/{suffix}."""
    return (
        drive_base
        + "/items/"
        + str(parent_id)
        + ":/"
        + quote(filename, safe="")
        + ":/"
        + suffix
    )


def upload_file(local_path, remote_name=None, schedule_name=None, provider_id="onedrive_business"):
    if not os.path.exists(local_path):
        raise RuntimeError("File not found: {}".format(local_path))

    drive_base, root_folder_id, token = ensure_target_drive(provider_id)
    parent = root_folder_id
    if schedule_name:
        parent = ensure_subfolder(drive_base, root_folder_id, schedule_name, token)

    name = remote_name or os.path.basename(local_path)
    size = os.path.getsize(local_path)

    # Small files: simple upload (< 4 MiB)
    if size < 4 * 1024 * 1024:
        with open(local_path, "rb") as f:
            content = f.read()
        url = _item_path_url(drive_base, parent, name, "content")
        r = _request(
            "PUT",
            url,
            token,
            data=content,
            headers={"Content-Type": "application/octet-stream"},
            timeout=300,
        )
        if r.status_code >= 400:
            raise RuntimeError("Upload failed: {}".format(r.text[:500]))
        meta = r.json()
    else:
        session = _json(
            "POST",
            _item_path_url(drive_base, parent, name, "createUploadSession"),
            token,
            headers={"Content-Type": "application/json"},
            json={
                "item": {
                    "@microsoft.graph.conflictBehavior": "replace",
                    "name": name,
                }
            },
        )
        upload_url = session.get("uploadUrl")
        if not upload_url:
            raise RuntimeError("No uploadUrl from createUploadSession.")
        meta = _upload_chunks(upload_url, local_path, size)

    web = meta.get("webUrl") or ""
    return {
        "id": meta.get("id") or "",
        "name": meta.get("name") or name,
        "size": int(meta.get("size") or size),
        "webViewLink": web,
        "folder_id": parent,
        "provider": provider_id,
    }


def _upload_chunks(upload_url, local_path, size):
    import requests

    with open(local_path, "rb") as f:
        start = 0
        while start < size:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            end = start + len(chunk) - 1
            headers = {
                "Content-Length": str(len(chunk)),
                "Content-Range": "bytes {}-{}/{}".format(start, end, size),
            }
            r = requests.put(upload_url, data=chunk, headers=headers, timeout=300)
            if r.status_code in (200, 201):
                return r.json()
            if r.status_code not in (202,):
                raise RuntimeError(
                    "Chunk upload failed ({}): {}".format(r.status_code, r.text[:400])
                )
            start = end + 1
    raise RuntimeError("Upload session ended without a completed file.")


def prune_backups(folder_id, name_regex, keep, provider_id="onedrive_business"):
    if not folder_id or keep <= 0:
        return []
    drive_base, _, token = ensure_target_drive(provider_id)
    matched = []
    url = "{}/items/{}/children?$select=id,name,file&$top=200".format(drive_base, folder_id)
    while url:
        data = _json("GET", url, token)
        for item in data.get("value") or []:
            if item.get("file") is None:
                continue
            n = item.get("name") or ""
            if name_regex.match(n):
                matched.append(item)
        url = data.get("@odata.nextLink")

    matched.sort(key=lambda f: f.get("name") or "", reverse=True)
    deleted = []
    for item in matched[keep:]:
        _request("DELETE", "{}/items/{}".format(drive_base, item["id"]), token)
        deleted.append(item.get("name") or item["id"])
    return deleted


def test_connection(provider_id="onedrive_business"):
    drive_base, folder_id, token = ensure_target_drive(provider_id)
    meta = _json("GET", "{}/items/{}".format(drive_base, folder_id), token)
    return {
        "folder_id": folder_id,
        "folder_name": meta.get("name") or "",
        "drive": drive_base,
    }
