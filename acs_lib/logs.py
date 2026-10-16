#!/usr/bin/python
# coding: utf-8
"""Per-schedule backup run logs."""

from __future__ import print_function
import os
import json

from .paths import LOGS_DIR, ensure_dirs, new_id, now_str, read_json, write_json, ok, fail

MAX_LOGS_PER_SCHEDULE = 100
GLOBAL_INDEX = os.path.join(LOGS_DIR, "index.json")


def _schedule_log_file(sid):
    return os.path.join(LOGS_DIR, "{}.json".format(sid))


def _load_index():
    return read_json(GLOBAL_INDEX, {"entries": []})


def _save_index(data):
    # keep last 500 global entries
    entries = data.get("entries", [])
    data["entries"] = entries[-500:]
    write_json(GLOBAL_INDEX, data)


def start_log(schedule_id, schedule_name):
    ensure_dirs()
    entry = {
        "id": new_id(),
        "schedule_id": schedule_id,
        "schedule_name": schedule_name,
        "status": "running",
        "started_at": now_str(),
        "finished_at": "",
        "message": "Backup started",
        "steps": [{"time": now_str(), "msg": "Backup started"}],
        "archive": "",
        "size": 0,
        "drive_file_id": "",
        "drive_link": "",
        "error": "",
    }
    path = _schedule_log_file(schedule_id)
    logs = read_json(path, {"logs": []})
    logs["logs"].insert(0, entry)
    logs["logs"] = logs["logs"][:MAX_LOGS_PER_SCHEDULE]
    write_json(path, logs)

    idx = _load_index()
    idx["entries"].insert(
        0,
        {
            "id": entry["id"],
            "schedule_id": schedule_id,
            "schedule_name": schedule_name,
            "status": "running",
            "started_at": entry["started_at"],
            "message": entry["message"],
        },
    )
    _save_index(idx)
    return entry


def append_step(schedule_id, log_id, msg):
    path = _schedule_log_file(schedule_id)
    logs = read_json(path, {"logs": []})
    for entry in logs["logs"]:
        if entry.get("id") == log_id:
            entry.setdefault("steps", []).append({"time": now_str(), "msg": msg})
            entry["message"] = msg
            break
    write_json(path, logs)


def finish_log(schedule_id, log_id, status, message="", **extra):
    path = _schedule_log_file(schedule_id)
    logs = read_json(path, {"logs": []})
    for entry in logs["logs"]:
        if entry.get("id") == log_id:
            entry["status"] = status
            entry["finished_at"] = now_str()
            entry["message"] = message or status
            entry.setdefault("steps", []).append({"time": now_str(), "msg": message or status})
            for k, v in extra.items():
                entry[k] = v
            break
    write_json(path, logs)

    idx = _load_index()
    for e in idx.get("entries", []):
        if e.get("id") == log_id:
            e["status"] = status
            e["message"] = message or status
            e["finished_at"] = now_str()
            break
    _save_index(idx)


def get_logs(schedule_id=None, limit=50):
    ensure_dirs()
    limit = int(limit or 50)
    if schedule_id:
        logs = read_json(_schedule_log_file(schedule_id), {"logs": []})
        return ok("OK", logs.get("logs", [])[:limit])
    idx = _load_index()
    return ok("OK", idx.get("entries", [])[:limit])


def get_log_detail(schedule_id, log_id):
    logs = read_json(_schedule_log_file(schedule_id), {"logs": []})
    for entry in logs.get("logs", []):
        if entry.get("id") == log_id:
            return ok("OK", entry)
    return fail("Log not found.")


def clear_logs(schedule_id=None):
    ensure_dirs()
    if schedule_id:
        path = _schedule_log_file(schedule_id)
        write_json(path, {"logs": []})
        idx = _load_index()
        idx["entries"] = [e for e in idx.get("entries", []) if e.get("schedule_id") != schedule_id]
        _save_index(idx)
        return ok("Logs cleared for schedule.")
    for name in os.listdir(LOGS_DIR):
        if name.endswith(".json"):
            try:
                os.remove(os.path.join(LOGS_DIR, name))
            except Exception:
                pass
    write_json(GLOBAL_INDEX, {"entries": []})
    return ok("All logs cleared.")
