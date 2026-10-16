#!/usr/bin/python
# coding: utf-8
"""
CLI worker invoked by cron.d for Autobackup to Cloud.

Usage:
  python backup_worker.py --schedule-id <id>
"""

from __future__ import print_function
import os
import sys
import argparse
import fcntl

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

# Panel class path for `public` when available
PANEL_CLASS = "/www/server/panel/class"
if os.path.isdir(PANEL_CLASS) and PANEL_CLASS not in sys.path:
    sys.path.insert(0, PANEL_CLASS)

os.chdir(PLUGIN_DIR)


def _lock_file(sid):
    from acs_lib.paths import TMP_DIR, ensure_dirs

    ensure_dirs()
    lock_path = os.path.join(TMP_DIR, "lock_{}.pid".format(sid))
    fh = open(lock_path, "w")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except IOError:
        fh.close()
        return None
    fh.write(str(os.getpid()))
    fh.flush()
    return fh


def main():
    parser = argparse.ArgumentParser(description="Autobackup to Cloud worker")
    parser.add_argument("--schedule-id", required=True, help="Schedule id to run")
    args = parser.parse_args()

    lock = _lock_file(args.schedule_id)
    if lock is None:
        print("Another backup for this schedule is already running.")
        sys.exit(0)

    try:
        from acs_lib.schedule_mgr import get_schedule
        from acs_lib.backup_engine import run_backup

        schedule = get_schedule(args.schedule_id)
        if not schedule:
            print("Schedule not found: {}".format(args.schedule_id))
            sys.exit(1)
        if not schedule.get("enabled"):
            print("Schedule is disabled: {}".format(args.schedule_id))
            sys.exit(0)

        result = run_backup(schedule, triggered_by="cron")
        print(result.get("msg", ""))
        sys.exit(0 if result.get("status") else 1)
    finally:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            lock.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
