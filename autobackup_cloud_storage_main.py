#!/usr/bin/python
# coding: utf-8
# +-------------------------------------------------------------------
# | aaPanel — Autobackup to Cloud
# +-------------------------------------------------------------------
"""
aaPanel plugin entrypoint.

Frontend calls:
  POST /plugin?action=a&name=autobackup_cloud_storage&s=<method>
"""

from __future__ import print_function
import os
import sys
import json

# Resolve plugin dir from this file so imports work even if panel cwd differs
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

# Panel helpers
_panel_root = "/www/server/panel"
_panel_class = os.path.join(_panel_root, "class")
if os.path.isdir(_panel_root):
    try:
        os.chdir(_panel_root)
    except Exception:
        pass
if os.path.isdir(_panel_class) and _panel_class not in sys.path:
    sys.path.insert(0, _panel_class)

try:
    import public  # type: ignore
except ImportError:
    public = None


def _parse_json_field(val, default=None):
    if default is None:
        default = []
    if val is None or val == "":
        return default
    if isinstance(val, (list, dict)):
        return val
    try:
        return json.loads(val)
    except Exception:
        return default


class autobackup_cloud_storage_main:
    def __init__(self):
        from acs_lib.paths import ensure_dirs

        ensure_dirs()

    # ----- helpers -----
    def _args_dict(self, args):
        from acs_lib.paths import get_arg

        if args is None:
            return {}
        if isinstance(args, dict):
            return args
        # dict_obj from panel — iterate common keys via getattr
        data = {}
        for key in dir(args):
            if key.startswith("_"):
                continue
            try:
                val = getattr(args, key)
            except Exception:
                continue
            if callable(val):
                continue
            data[key] = val
        # also support .get
        return data

    def _get(self, args, key, default=""):
        from acs_lib.paths import get_arg

        return get_arg(args, key, default)

    # ----- status / overview -----
    def get_status(self, args):
        from acs_lib.storage import get_storage_status
        from acs_lib.schedule_mgr import list_schedules
        from acs_lib.logs import get_logs

        st = get_storage_status()
        schedules = list_schedules()
        recent = get_logs(limit=10)
        storage = st.get("data") or {}
        return {
            "status": True,
            "msg": "OK",
            "storage": storage,
            "drive": storage.get("drive") or {},
            "schedule_count": len(schedules),
            "enabled_count": sum(1 for s in schedules if s.get("enabled")),
            "recent_logs": recent.get("data", []),
            "version": "1.1.1",
        }

    # ----- storage (Drive + S3-compatible) -----
    def get_storage_status(self, args):
        from acs_lib.storage import get_storage_status

        return get_storage_status()

    def list_storage_providers(self, args):
        from acs_lib.storage_providers import list_providers
        from acs_lib.paths import ok

        return ok("OK", list_providers())

    def set_storage_provider(self, args):
        from acs_lib.storage import save_storage_provider

        return save_storage_provider(self._get(args, "provider"))

    def save_s3_config(self, args):
        from acs_lib.storage import save_s3_config

        return save_s3_config(
            {
                "provider": self._get(args, "provider"),
                "endpoint": self._get(args, "endpoint"),
                "region": self._get(args, "region"),
                "access_key": self._get(args, "access_key"),
                "secret_key": self._get(args, "secret_key"),
                "bucket": self._get(args, "bucket"),
                "prefix": self._get(args, "prefix"),
                "path_style": self._get(args, "path_style", "0"),
            }
        )

    def test_storage(self, args):
        from acs_lib.storage import test_storage

        return test_storage(self._get(args, "provider") or None)

    # ----- Google Drive linking -----
    def save_oauth_client(self, args):
        from acs_lib.drive_auth import save_oauth_client

        return save_oauth_client(
            self._get(args, "client_id"),
            self._get(args, "client_secret"),
        )

    def upload_credentials(self, args):
        """Accept credentials.json content (paste or file upload via FileReader)."""
        from acs_lib.drive_auth import save_credentials_json

        raw = self._get(args, "credentials_json")
        if not raw:
            raw = self._get(args, "file")
        return save_credentials_json(raw)

    def get_auth_url(self, args):
        from acs_lib.drive_auth import get_auth_url

        return get_auth_url()

    def exchange_code(self, args):
        from acs_lib.drive_auth import exchange_code

        return exchange_code(self._get(args, "code"))

    def unlink_drive(self, args):
        from acs_lib.drive_auth import unlink_drive

        return unlink_drive()

    def drive_status(self, args):
        from acs_lib.drive_auth import drive_status

        return drive_status()

    def set_drive_folder_name(self, args):
        from acs_lib.paths import get_config, save_config, ok, fail

        name = (self._get(args, "folder_name") or "").strip()
        if not name:
            return fail("Folder name is required.")
        cfg = get_config()
        cfg["drive_folder_name"] = name
        cfg["drive_folder_id"] = ""  # force recreate/find on next upload
        save_config(cfg)
        return ok("Drive folder name updated.", {"folder_name": name})

    # ----- schedules -----
    def get_schedules(self, args):
        from acs_lib.schedule_mgr import list_schedules
        from acs_lib.paths import ok

        return ok("OK", list_schedules())

    def get_schedule(self, args):
        from acs_lib.schedule_mgr import get_schedule
        from acs_lib.paths import ok, fail

        s = get_schedule(self._get(args, "id"))
        if not s:
            return fail("Schedule not found.")
        return ok("OK", s)

    def create_schedule(self, args):
        from acs_lib.schedule_mgr import create_schedule

        payload = {
            "name": self._get(args, "schedule_name") or self._get(args, "sch_name") or "",
            "source_path": self._get(args, "source_path"),
            "excludes": self._get(args, "excludes"),
            "databases": _parse_json_field(self._get(args, "databases"), []),
            "cron": self._get(args, "cron"),
            "preset": self._get(args, "preset"),
            "enabled": self._get(args, "enabled", "1"),
            "keep_local": self._get(args, "keep_local", "0") in ("1", "true", True, 1),
            "retention_count": self._get(args, "retention_count", "0"),
        }
        # excludes may be newline or JSON
        ex = payload["excludes"]
        if isinstance(ex, str) and ex.strip().startswith("["):
            payload["excludes"] = _parse_json_field(ex, [])
        return create_schedule(payload)

    def update_schedule(self, args):
        from acs_lib.schedule_mgr import update_schedule

        payload = {"id": self._get(args, "id")}
        for key in (
            "schedule_name",
            "sch_name",
            "source_path",
            "excludes",
            "cron",
            "preset",
            "enabled",
            "keep_local",
            "retention_count",
        ):
            val = self._get(args, key, None)
            if val is not None and val != "":
                if key in ("schedule_name", "sch_name"):
                    payload["name"] = val
                else:
                    payload[key] = val
        db = self._get(args, "databases", None)
        if db is not None and db != "":
            payload["databases"] = _parse_json_field(db, [])
        if "excludes" in payload and isinstance(payload["excludes"], str):
            if payload["excludes"].strip().startswith("["):
                payload["excludes"] = _parse_json_field(payload["excludes"], [])
        if "keep_local" in payload:
            payload["keep_local"] = payload["keep_local"] in ("1", "true", True, 1)
        return update_schedule(payload)

    def start_schedule(self, args):
        from acs_lib.schedule_mgr import set_schedule_enabled

        return set_schedule_enabled(self._get(args, "id"), True)

    def stop_schedule(self, args):
        from acs_lib.schedule_mgr import set_schedule_enabled

        return set_schedule_enabled(self._get(args, "id"), False)

    def delete_schedule(self, args):
        from acs_lib.schedule_mgr import delete_schedule

        return delete_schedule(self._get(args, "id"))

    def sync_crons(self, args):
        from acs_lib.schedule_mgr import sync_all_crons

        return sync_all_crons()

    def run_now(self, args):
        """Trigger an immediate backup in background."""
        from acs_lib.schedule_mgr import get_schedule
        from acs_lib.paths import get_py_bin, PLUGIN_DIR, ok, fail
        import subprocess

        sid = self._get(args, "id")
        schedule = get_schedule(sid)
        if not schedule:
            return fail("Schedule not found.")
        py = get_py_bin()
        worker = os.path.join(PLUGIN_DIR, "backup_worker.py")
        try:
            subprocess.Popen(
                [py, worker, "--schedule-id", sid],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception as e:
            return fail("Failed to start backup: {}".format(str(e)))
        return ok("Backup started in background.")

    # ----- databases -----
    def list_databases(self, args):
        from acs_lib.db_backup import list_all_databases

        return list_all_databases()

    # ----- filesystem helpers -----
    def browse_path(self, args):
        """List directories under a path for the folder picker."""
        from acs_lib.paths import ok, fail

        path = self._get(args, "path") or "/www"
        path = os.path.abspath(path)
        if not os.path.exists(path):
            return fail("Path does not exist.")
        if not os.path.isdir(path):
            return fail("Not a directory.")
        try:
            entries = []
            for name in sorted(os.listdir(path)):
                full = os.path.join(path, name)
                if os.path.isdir(full):
                    entries.append({"name": name, "path": full, "type": "dir"})
            parent = os.path.dirname(path.rstrip("/")) or "/"
            return ok(
                "OK",
                {"path": path, "parent": parent if path != "/" else "", "entries": entries},
            )
        except PermissionError:
            return fail("Permission denied.")
        except Exception as e:
            return fail(str(e))

    # ----- logs -----
    def get_logs(self, args):
        from acs_lib.logs import get_logs

        return get_logs(
            schedule_id=self._get(args, "schedule_id") or None,
            limit=self._get(args, "limit") or 50,
        )

    def get_log_detail(self, args):
        from acs_lib.logs import get_log_detail

        return get_log_detail(self._get(args, "schedule_id"), self._get(args, "log_id"))

    def clear_logs(self, args):
        from acs_lib.logs import clear_logs

        return clear_logs(self._get(args, "schedule_id") or None)
