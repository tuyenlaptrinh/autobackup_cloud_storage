#!/usr/bin/python
# coding: utf-8
"""Shared paths and helpers for Autobackup to Cloud."""

from __future__ import print_function
import os
import json
import time
import uuid
import threading

PLUGIN_NAME = "autobackup_cloud_storage"
PLUGIN_DIR = "/www/server/panel/plugin/{}".format(PLUGIN_NAME)
DATA_DIR = os.path.join(PLUGIN_DIR, "data")
LOGS_DIR = os.path.join(DATA_DIR, "logs")
TMP_DIR = os.path.join(DATA_DIR, "tmp")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
TOKEN_FILE = os.path.join(DATA_DIR, "token.json")
CREDENTIALS_FILE = os.path.join(DATA_DIR, "credentials.json")
MSGRAPH_TOKEN_FILE = os.path.join(DATA_DIR, "msgraph_token.json")
SCHEDULES_FILE = os.path.join(DATA_DIR, "schedules.json")
CRON_PREFIX = "autobackup_cloud_storage_"

_file_lock = threading.Lock()

DEFAULT_MSGRAPH = {
    "client_id": "",
    "client_secret": "",
    # organizations = work/school only (blocks personal MSA)
    "tenant": "organizations",
    "linked": False,
    "account_email": "",
    "folder_name": "aaPanel Backups",
    "folder_id": "",
    "site_url": "",
    "site_id": "",
    "drive_id": "",
}

DEFAULT_CONFIG = {
    "storage_provider": "gdrive",
    "drive_folder_name": "aaPanel Backups",
    "drive_folder_id": "",
    "client_id": "",
    "client_secret": "",
    "account_email": "",
    "linked": False,
    "s3": {
        "endpoint": "",
        "region": "us-east-1",
        "access_key": "",
        "secret_key": "",
        "bucket": "",
        "prefix": "aapanel-backups/",
        "path_style": False,
    },
    "msgraph": dict(DEFAULT_MSGRAPH),
}


def ensure_dirs():
    for d in (DATA_DIR, LOGS_DIR, TMP_DIR):
        if not os.path.exists(d):
            os.makedirs(d, 0o700)


def now_str():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def new_id():
    return uuid.uuid4().hex[:12]


def read_json(path, default=None):
    ensure_dirs()
    if default is None:
        default = {}
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return default


def write_json(path, data):
    ensure_dirs()
    with _file_lock:
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)


def get_config():
    cfg = read_json(CONFIG_FILE, {}) or {}
    merged = dict(DEFAULT_CONFIG)
    merged.update(cfg)
    # Deep-merge nested dicts so new keys appear after upgrades
    s3 = dict(DEFAULT_CONFIG.get("s3") or {})
    s3.update(cfg.get("s3") or {})
    merged["s3"] = s3
    mg = dict(DEFAULT_MSGRAPH)
    mg.update(cfg.get("msgraph") or {})
    # Never allow personal-account tenants
    if str(mg.get("tenant") or "").lower() in ("common", "consumers", ""):
        mg["tenant"] = "organizations"
    merged["msgraph"] = mg
    return merged


def save_config(cfg):
    write_json(CONFIG_FILE, cfg)


def get_py_bin():
    candidates = [
        "/www/server/panel/pyenv/bin/python",
        "/www/server/panel/pyenv/bin/python3",
        "/usr/bin/python3",
        "/usr/bin/python",
    ]
    for c in candidates:
        if os.path.exists(c) and os.access(c, os.X_OK):
            return c
    return "python3"


def ok(msg="OK", data=None):
    r = {"status": True, "msg": msg}
    if data is not None:
        r["data"] = data
    return r


def fail(msg="Error", data=None):
    r = {"status": False, "msg": msg}
    if data is not None:
        r["data"] = data
    return r


def get_arg(args, key, default=""):
    """Read a request arg from aaPanel args object (dict-like or getattr)."""
    if args is None:
        return default
    if isinstance(args, dict):
        return args.get(key, default)
    val = getattr(args, key, None)
    if val is None and hasattr(args, "get"):
        try:
            val = args.get(key, default)
        except Exception:
            val = default
    return default if val is None else val
