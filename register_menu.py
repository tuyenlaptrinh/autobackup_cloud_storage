#!/usr/bin/env python
# coding: utf-8
"""Register / unregister left-menu entry for Autobackup to Cloud."""
from __future__ import print_function

import json
import os
import sys
import tempfile

PANEL = "/www/server/panel"
MENU_FILE = os.path.join(PANEL, "config", "menu.json")
LOCAL_MENU = os.path.join(PANEL, "config", "local_menu.json")

MENU_ID = "memuAutobackupCloud"
PLUGIN_NAME = "autobackup_cloud_storage"

# Opens Soft settings for this plugin (classic Soft JS). Falls back to App Store.
OPEN_HREF = (
    "javascript:;(function(){"
    "try{"
    "if(window.bt&&bt.soft&&bt.soft.get_soft_find){"
    "bt.soft.get_soft_find('%s',function(){"
    "if(window.soft&&soft.set_soft_config)soft.set_soft_config('%s');"
    "});"
    "}else if(window.soft&&soft.set_soft_config){"
    "soft.set_soft_config('%s');"
    "}else{location.href='/soft';}"
    "}catch(e){location.href='/soft';}"
    "})();"
) % (PLUGIN_NAME, PLUGIN_NAME, PLUGIN_NAME)

MENU_ITEM = {
    "title": "Cloud Backup",
    "href": OPEN_HREF,
    "class": "menu_day",
    "id": MENU_ID,
    "sort": 17,
}


def _load_menu(path):
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_menu(path, data):
    directory = os.path.dirname(path)
    if not os.path.isdir(directory):
        return False
    fd, tmp = tempfile.mkstemp(prefix="menu_", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(tmp, path)
        return True
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        return False


def _refresh_local_cache():
    # Force Soft / panel to rebuild menu cache on next load
    try:
        if os.path.exists(LOCAL_MENU):
            os.remove(LOCAL_MENU)
    except Exception:
        pass


def add_menu():
    items = _load_menu(MENU_FILE)
    items = [x for x in items if not (isinstance(x, dict) and x.get("id") == MENU_ID)]
    # Insert before App Store / Settings when possible
    insert_at = len(items)
    for i, x in enumerate(items):
        if isinstance(x, dict) and x.get("id") in ("memuAsoft", "memuAconfig", "dologin"):
            insert_at = i
            break
    items.insert(insert_at, dict(MENU_ITEM))
    ok = _save_menu(MENU_FILE, items)
    _refresh_local_cache()
    return ok


def remove_menu():
    items = _load_menu(MENU_FILE)
    new_items = [x for x in items if not (isinstance(x, dict) and x.get("id") == MENU_ID)]
    if len(new_items) == len(items) and not items:
        _refresh_local_cache()
        return True
    ok = _save_menu(MENU_FILE, new_items)
    _refresh_local_cache()
    return ok


def main():
    action = (sys.argv[1] if len(sys.argv) > 1 else "").strip().lower()
    if action in ("install", "add", "register"):
        ok = add_menu()
        print("menu register:", "ok" if ok else "skip")
        return 0 if ok else 1
    if action in ("uninstall", "remove", "unregister"):
        ok = remove_menu()
        print("menu unregister:", "ok" if ok else "skip")
        return 0 if ok else 1
    print("Usage: register_menu.py install|uninstall")
    return 2


if __name__ == "__main__":
    sys.exit(main())
