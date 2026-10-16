#!/usr/bin/python
# coding: utf-8
"""Create zip archives (with zip -x excludes) and upload to Drive."""

from __future__ import print_function
import os
import shutil
import subprocess
import time

from .paths import TMP_DIR, ensure_dirs
from .db_backup import dump_databases
from .storage import upload_backup, get_storage_config, prune_backups
from .storage_providers import get_provider
from . import logs as logmod
from . import schedule_mgr


def _run_zip(source_path, archive_path, excludes, work_dir=None):
    """
    Build a zip using system `zip` so -x patterns match user expectations.
    Example excludes: ['*/node_modules/*', '*.log', 'file.jpg']
    """
    ensure_dirs()
    source_path = os.path.abspath(source_path)
    parent = os.path.dirname(source_path.rstrip("/")) or "/"
    base = os.path.basename(source_path.rstrip("/")) or source_path

    cmd = ["zip", "-r", "-q", archive_path, base]
    for ex in excludes or []:
        ex = ex.strip().strip('"').strip("'")
        if not ex:
            continue
        cmd.extend(["-x", ex])

    p = subprocess.Popen(
        cmd,
        cwd=parent,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    out, err = p.communicate()
    if p.returncode not in (0, 12) and not os.path.exists(archive_path):
        msg = (err or out or b"").decode("utf-8", "ignore")
        raise RuntimeError("zip failed (code {}): {}".format(p.returncode, msg))

    # Append databases/ folder from work_dir if present
    if work_dir:
        db_dir = os.path.join(work_dir, "databases")
        if os.path.isdir(db_dir) and os.listdir(db_dir):
            p2 = subprocess.Popen(
                ["zip", "-r", "-q", archive_path, "databases"],
                cwd=work_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            out2, err2 = p2.communicate()
            if p2.returncode not in (0, 12) and not os.path.exists(archive_path):
                raise RuntimeError(
                    "zip (databases) failed: {}".format(
                        (err2 or out2 or b"").decode("utf-8", "ignore")
                    )
                )

    if not os.path.exists(archive_path):
        raise RuntimeError("Archive was not created.")
    return archive_path


def run_backup(schedule, triggered_by="cron"):
    """Execute a full backup for one schedule dict."""
    ensure_dirs()
    sid = schedule["id"]
    name = schedule.get("name") or sid
    log = logmod.start_log(sid, name)
    log_id = log["id"]
    work_dir = os.path.join(TMP_DIR, "job_{}_{}".format(sid, int(time.time())))
    try:
        os.makedirs(work_dir)

        source = schedule.get("source_path") or ""
        if not source or not os.path.exists(source):
            raise RuntimeError("Source path missing: {}".format(source))

        logmod.append_step(sid, log_id, "Packing files from {}".format(source))
        stamp = time.strftime("%Y%m%d_%H%M%S")
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)[:40]
        archive_name = "{}_{}.zip".format(safe_name, stamp)
        archive_path = os.path.join(work_dir, archive_name)

        databases = schedule.get("databases") or []
        if databases:
            logmod.append_step(sid, log_id, "Dumping {} database(s)".format(len(databases)))
            dump_databases(databases, work_dir)

        excludes = schedule.get("excludes") or []
        _run_zip(source, archive_path, excludes, work_dir=work_dir)

        size = os.path.getsize(archive_path)
        logmod.append_step(
            sid, log_id, "Archive ready ({:.2f} MB)".format(size / (1024.0 * 1024.0))
        )

        cfg = get_storage_config()
        provider_id = schedule.get("storage_provider") or cfg.get("storage_provider") or "gdrive"
        provider_name = get_provider(provider_id).get("name") or provider_id
        logmod.append_step(sid, log_id, "Uploading to {}".format(provider_name))
        uploaded = upload_backup(
            archive_path,
            remote_name=archive_name,
            schedule_name=name,
            provider_id=provider_id,
        )

        try:
            keep_remote = int(schedule.get("retention_count") or 0)
        except (TypeError, ValueError):
            keep_remote = 0
        if keep_remote > 0:
            try:
                removed = prune_backups(
                    safe_name,
                    keep_remote,
                    schedule_name=name,
                    provider_id=provider_id,
                    uploaded=uploaded,
                )
                if removed:
                    logmod.append_step(
                        sid,
                        log_id,
                        "Removed {} old backup(s) from storage (keeping {}): {}".format(
                            len(removed), keep_remote, ", ".join(removed)
                        ),
                    )
            except Exception as e:
                logmod.append_step(
                    sid, log_id, "Warning: could not remove old backups: {}".format(e)
                )

        if not schedule.get("keep_local", False):
            shutil.rmtree(work_dir, ignore_errors=True)

        logmod.finish_log(
            sid,
            log_id,
            "success",
            "Backup completed via {} ({})".format(provider_name, triggered_by),
            archive=archive_name,
            size=size,
            drive_file_id=uploaded.get("id", ""),
            drive_link=uploaded.get("webViewLink", ""),
            storage_provider=provider_id,
        )
        schedule_mgr.mark_run(sid, "success")
        return {
            "status": True,
            "msg": "Backup completed",
            "size": size,
            "drive_file_id": uploaded.get("id"),
            "drive_link": uploaded.get("webViewLink", ""),
            "archive": archive_name,
            "storage_provider": provider_id,
        }
    except Exception as e:
        err = str(e)
        logmod.finish_log(sid, log_id, "failed", err, error=err)
        schedule_mgr.mark_run(sid, "failed")
        shutil.rmtree(work_dir, ignore_errors=True)
        return {"status": False, "msg": err}
