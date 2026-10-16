#!/usr/bin/python
# coding: utf-8
"""Backup schedule CRUD + cron.d sync."""

from __future__ import print_function
import os
import re
import shlex

from .paths import (
    SCHEDULES_FILE,
    PLUGIN_DIR,
    CRON_PREFIX,
    read_json,
    write_json,
    new_id,
    now_str,
    get_py_bin,
    ok,
    fail,
)

# 5-field cron only (minute hour dom month dow)
CRON_RE = re.compile(
    r"^(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)$"
)

PRESETS = {
    "hourly": "0 * * * *",
    "every_6h": "0 */6 * * *",
    "daily": "0 2 * * *",
    "weekly": "0 3 * * 0",
    "monthly": "0 4 1 * *",
}


def list_schedules():
    data = read_json(SCHEDULES_FILE, {"schedules": []})
    return data.get("schedules", [])


def save_schedules(schedules):
    write_json(SCHEDULES_FILE, {"schedules": schedules})


def get_schedule(sid):
    for s in list_schedules():
        if s.get("id") == sid:
            return s
    return None


def _cron_path(sid):
    return "/etc/cron.d/{}{}".format(CRON_PREFIX, sid)


def _validate_cron(expr):
    expr = (expr or "").strip()
    if not expr:
        return False, "Cron expression is required."
    if not CRON_RE.match(expr):
        return False, "Invalid cron expression. Use 5 fields: min hour dom month dow"
    return True, expr


def _write_cron(schedule):
    """Install or remove /etc/cron.d entry for a schedule."""
    path = _cron_path(schedule["id"])
    if not schedule.get("enabled"):
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass
        return

    py = get_py_bin()
    worker = os.path.join(PLUGIN_DIR, "backup_worker.py")
    # cron.d requires a user field
    line = (
        "{cron} root {py} {worker} --schedule-id {sid} >/dev/null 2>&1\n"
    ).format(
        cron=schedule["cron"],
        py=py,
        worker=shlex.quote(worker),
        sid=schedule["id"],
    )
    header = (
        "# Managed by Autobackup to Cloud plugin — do not edit\n"
        "SHELL=/bin/bash\n"
        "PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin\n"
        "MAILTO=\"\"\n"
    )
    try:
        with open(path, "w") as f:
            f.write(header + line)
        os.chmod(path, 0o644)
    except Exception as e:
        raise RuntimeError("Failed to write cron file: {}".format(str(e)))


def _remove_cron(sid):
    path = _cron_path(sid)
    if os.path.exists(path):
        try:
            os.remove(path)
        except Exception:
            pass


def _parse_retention(value):
    """Return (count, error). 0 means keep every backup on storage."""
    if value is None or str(value).strip() == "":
        return 0, None
    try:
        count = int(str(value).strip())
    except ValueError:
        return 0, "Keep on storage must be a whole number."
    if count < 0:
        return 0, "Keep on storage cannot be negative."
    return count, None


def create_schedule(payload):
    name = (payload.get("name") or "").strip()
    if not name:
        return fail("Schedule name is required.")

    source_path = (payload.get("source_path") or "").strip()
    if not source_path:
        return fail("Source folder path is required.")
    if not os.path.exists(source_path):
        return fail("Source path does not exist: {}".format(source_path))

    cron = payload.get("cron") or ""
    preset = (payload.get("preset") or "").strip()
    if preset and preset in PRESETS:
        cron = PRESETS[preset]
    valid, cron_or_err = _validate_cron(cron)
    if not valid:
        return fail(cron_or_err)
    cron = cron_or_err

    excludes = payload.get("excludes") or []
    if isinstance(excludes, str):
        excludes = [x.strip() for x in excludes.replace("\r", "").split("\n") if x.strip()]

    databases = payload.get("databases") or []
    if isinstance(databases, str):
        try:
            import json

            databases = json.loads(databases) if databases else []
        except Exception:
            databases = []

    enabled = payload.get("enabled", True)
    if isinstance(enabled, str):
        enabled = enabled.lower() in ("1", "true", "yes", "on")

    def _as_bool(v, default=False):
        if isinstance(v, bool):
            return v
        if v is None:
            return default
        return str(v).strip().lower() in ("1", "true", "yes", "on")

    retention, err = _parse_retention(payload.get("retention_count"))
    if err:
        return fail(err)

    schedule = {
        "id": new_id(),
        "name": name,
        "source_path": source_path,
        "excludes": excludes,
        "databases": databases,  # [{type, name}, ...]
        "cron": cron,
        "preset": preset or "custom",
        "enabled": bool(enabled),
        "keep_local": _as_bool(payload.get("keep_local"), False),
        "retention_count": retention,
        "created_at": now_str(),
        "updated_at": now_str(),
        "last_run_at": "",
        "last_status": "",
    }

    schedules = list_schedules()
    schedules.append(schedule)
    save_schedules(schedules)
    try:
        _write_cron(schedule)
    except Exception as e:
        # roll back persist if cron fails critically — still keep schedule, mark disabled
        schedule["enabled"] = False
        schedules[-1] = schedule
        save_schedules(schedules)
        return fail("Schedule saved but cron install failed: {}".format(str(e)), schedule)

    return ok("Schedule created.", schedule)


def update_schedule(payload):
    sid = (payload.get("id") or "").strip()
    if not sid:
        return fail("Schedule id is required.")
    schedules = list_schedules()
    idx = None
    for i, s in enumerate(schedules):
        if s.get("id") == sid:
            idx = i
            break
    if idx is None:
        return fail("Schedule not found.")

    s = schedules[idx]
    if "name" in payload and payload["name"]:
        s["name"] = payload["name"].strip()
    if "source_path" in payload and payload["source_path"]:
        path = payload["source_path"].strip()
        if not os.path.exists(path):
            return fail("Source path does not exist: {}".format(path))
        s["source_path"] = path
    if "excludes" in payload:
        excludes = payload["excludes"]
        if isinstance(excludes, str):
            excludes = [x.strip() for x in excludes.replace("\r", "").split("\n") if x.strip()]
        s["excludes"] = excludes
    if "databases" in payload:
        databases = payload["databases"]
        if isinstance(databases, str):
            try:
                import json

                databases = json.loads(databases) if databases else []
            except Exception:
                databases = []
        s["databases"] = databases
    if "cron" in payload or "preset" in payload:
        cron = payload.get("cron") or s.get("cron")
        preset = (payload.get("preset") or "").strip()
        if preset and preset in PRESETS:
            cron = PRESETS[preset]
            s["preset"] = preset
        elif "cron" in payload:
            s["preset"] = "custom"
        valid, cron_or_err = _validate_cron(cron)
        if not valid:
            return fail(cron_or_err)
        s["cron"] = cron_or_err
    if "enabled" in payload:
        enabled = payload["enabled"]
        if isinstance(enabled, str):
            enabled = enabled.lower() in ("1", "true", "yes", "on")
        s["enabled"] = bool(enabled)
    if "keep_local" in payload:
        kl = payload["keep_local"]
        if isinstance(kl, bool):
            s["keep_local"] = kl
        else:
            s["keep_local"] = str(kl).strip().lower() in ("1", "true", "yes", "on")
    if "retention_count" in payload:
        retention, err = _parse_retention(payload["retention_count"])
        if err:
            return fail(err)
        s["retention_count"] = retention

    s["updated_at"] = now_str()
    schedules[idx] = s
    save_schedules(schedules)
    try:
        _write_cron(s)
    except Exception as e:
        return fail("Updated but cron sync failed: {}".format(str(e)), s)
    return ok("Schedule updated.", s)


def set_schedule_enabled(sid, enabled):
    return update_schedule({"id": sid, "enabled": enabled})


def delete_schedule(sid):
    sid = (sid or "").strip()
    if not sid:
        return fail("Schedule id is required.")
    schedules = list_schedules()
    new_list = [s for s in schedules if s.get("id") != sid]
    if len(new_list) == len(schedules):
        return fail("Schedule not found.")
    save_schedules(new_list)
    _remove_cron(sid)
    return ok("Schedule deleted.")


def mark_run(sid, status, when=None):
    schedules = list_schedules()
    for s in schedules:
        if s.get("id") == sid:
            s["last_run_at"] = when or now_str()
            s["last_status"] = status
            break
    save_schedules(schedules)


def sync_all_crons():
    """Re-write all cron.d files from schedules.json (repair)."""
    for s in list_schedules():
        try:
            _write_cron(s)
        except Exception:
            pass
    return ok("Cron entries synced.")
