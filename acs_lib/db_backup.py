#!/usr/bin/python
# coding: utf-8
"""List and dump MySQL / PostgreSQL databases (aaPanel-aware)."""

from __future__ import print_function
import os
import re
import glob
import gzip
import shutil
import subprocess
import time
import tempfile

from .paths import ok, TMP_DIR, ensure_dirs


def _run(cmd, env=None):
    try:
        p = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            shell=isinstance(cmd, str),
        )
        out, err = p.communicate()
        if isinstance(out, bytes):
            out = out.decode("utf-8", "ignore")
        if isinstance(err, bytes):
            err = err.decode("utf-8", "ignore")
        return p.returncode, out, err
    except Exception as e:
        return 1, "", str(e)


def _truthy(val):
    if isinstance(val, bool):
        return val
    if val is None:
        return False
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def _mysql_root_password():
    try:
        import public  # type: ignore

        pwd = public.M("config").where("id=?", (1,)).getField("mysql_root")
        if pwd:
            return str(pwd)
    except Exception:
        pass
    for path in (
        "/www/server/panel/data/db.pl",
        "/www/server/panel/data/mysql_root.pl",
    ):
        try:
            if os.path.exists(path):
                with open(path, "r") as f:
                    pwd = f.read().strip()
                if pwd:
                    return pwd
        except Exception:
            pass
    return ""


def _find_mysql_bin(name):
    candidates = [
        "/www/server/mysql/bin/{}".format(name),
        "/usr/bin/{}".format(name),
        "/usr/local/bin/{}".format(name),
        name,
    ]
    for c in candidates:
        if c == name or (os.path.exists(c) and os.access(c, os.X_OK)):
            return c
    return name


def list_mysql_databases():
    pwd = _mysql_root_password()
    mysql = _find_mysql_bin("mysql")
    attempts = []
    if pwd:
        attempts.append([mysql, "-uroot", "-p{}".format(pwd), "-N", "-e", "SHOW DATABASES;"])
    attempts.append([mysql, "-uroot", "-N", "-e", "SHOW DATABASES;"])
    attempts.append([mysql, "-N", "-e", "SHOW DATABASES;"])

    out = ""
    for cmd in attempts:
        code, out, err = _run(cmd)
        if code == 0 and out.strip():
            break
    else:
        # Fallback: databases registered in aaPanel
        return _panel_mysql_list()

    skip = {"information_schema", "performance_schema", "mysql", "sys"}
    dbs = []
    for line in out.splitlines():
        name = line.strip()
        if name and name not in skip:
            dbs.append({"type": "mysql", "name": name})
    return dbs or _panel_mysql_list()


def _panel_mysql_list():
    dbs = []
    try:
        import public  # type: ignore

        rows = public.M("databases").field("name,type,db_type").select() or []
        for row in rows:
            name = row.get("name") if isinstance(row, dict) else None
            if not name:
                continue
            dtype = str(row.get("type") or row.get("db_type") or "mysql").lower()
            if dtype in ("", "0", "mysql", "mariadb"):
                dbs.append({"type": "mysql", "name": name})
    except Exception:
        pass
    return dbs


def _find_psql():
    candidates = [
        "/www/server/pgsql/bin/psql",
        "/www/server/pgsql/bin/pg_dump",  # sibling check below
    ]
    # Versioned package paths
    candidates.extend(sorted(glob.glob("/usr/lib/postgresql/*/bin/psql"), reverse=True))
    candidates.extend(
        [
            "/usr/pgsql-16/bin/psql",
            "/usr/pgsql-15/bin/psql",
            "/usr/pgsql-14/bin/psql",
            "/usr/bin/psql",
            "/usr/local/bin/psql",
        ]
    )
    for c in candidates:
        if c.endswith("pg_dump"):
            sibling = os.path.join(os.path.dirname(c), "psql")
            if os.path.exists(sibling) and os.access(sibling, os.X_OK):
                return sibling
            continue
        if os.path.exists(c) and os.access(c, os.X_OK):
            return c
    # which
    code, out, _ = _run(["bash", "-lc", "command -v psql"])
    if code == 0 and out.strip():
        return out.strip()
    return ""


def _find_pg_dump():
    psql = _find_psql()
    if psql:
        sibling = os.path.join(os.path.dirname(psql), "pg_dump")
        if os.path.exists(sibling):
            return sibling
    for c in (
        "/www/server/pgsql/bin/pg_dump",
        "/usr/bin/pg_dump",
    ):
        if os.path.exists(c):
            return c
    return "pg_dump"


def _pgsql_root_password():
    """aaPanel stores postgres (root) password in several possible places."""
    # Common panel data files
    for path in (
        "/www/server/panel/data/postgresAS.json",
        "/www/server/panel/data/pgsql_root.pl",
        "/www/server/panel/data/postgres_root.pl",
        "/www/server/pgsql/data/pgpass",
    ):
        try:
            if not os.path.exists(path):
                continue
            with open(path, "r") as f:
                raw = f.read().strip()
            if not raw:
                continue
            if raw.startswith("{") or raw.startswith("["):
                import json

                data = json.loads(raw)
                if isinstance(data, dict):
                    for key in ("password", "root", "postgres", "pgsql_root", "db_password"):
                        if data.get(key):
                            return str(data[key])
            else:
                return raw
        except Exception:
            pass

    try:
        import public  # type: ignore

        # Newer panels may keep it in config / dedicated table
        for table, field in (
            ("config", "pgsql_root"),
            ("config", "postgres_root"),
        ):
            try:
                pwd = public.M(table).where("id=?", (1,)).getField(field)
                if pwd:
                    return str(pwd)
            except Exception:
                pass

        # Some builds: panelPgsql helper
        try:
            import panelPgsql  # type: ignore

            obj = panelPgsql.panelPgsql()
            if hasattr(obj, "get_root_pwd"):
                pwd = obj.get_root_pwd()
                if isinstance(pwd, dict):
                    pwd = pwd.get("msg") or pwd.get("password") or ""
                if pwd and str(pwd) not in ("True", "False"):
                    return str(pwd)
        except Exception:
            pass
    except Exception:
        pass
    return ""


def _pgsql_port():
    for path in (
        "/www/server/pgsql/data/postgresql.conf",
        "/www/server/pgsql/postgresql.conf",
    ):
        try:
            if not os.path.exists(path):
                continue
            with open(path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("port") and "=" in line:
                        val = line.split("=", 1)[1].split("#")[0].strip()
                        if val.isdigit():
                            return val
        except Exception:
            pass
    return "5432"


def _panel_pgsql_list():
    """Databases registered in aaPanel UI (even if live psql auth fails)."""
    dbs = []
    seen = set()

    def _add(name):
        name = (name or "").strip()
        if not name or name in seen:
            return
        if name in ("postgres", "template0", "template1"):
            return
        seen.add(name)
        dbs.append({"type": "postgres", "name": name})

    try:
        import public  # type: ignore

        # Newer aaPanel: databases table with type/db_type markers
        try:
            rows = public.M("databases").select() or []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                name = row.get("name") or row.get("db_name") or ""
                dtype = str(row.get("type") or "").lower()
                db_type = row.get("db_type")
                # db_type: 0=mysql, 1=pgsql in some builds; or string markers
                is_pg = (
                    dtype in ("pgsql", "postgres", "postgresql", "pg")
                    or str(db_type) in ("1", "pgsql", "postgres")
                    or "pgsql" in dtype
                    or "postgre" in dtype
                )
                if is_pg:
                    _add(name)
        except Exception:
            pass

        # Dedicated pgsql tables used by PostgreSQL Manager plugin / panel modules
        for table in ("pgsql", "pg_databases", "database_pgsql"):
            try:
                rows = public.M(table).select() or []
            except Exception:
                continue
            for row in rows:
                if isinstance(row, dict):
                    _add(row.get("name") or row.get("db_name") or row.get("ps"))
    except Exception:
        pass

    # JSON sidecars some panel builds keep
    for path in (
        "/www/server/panel/data/pgsql_list.json",
        "/www/server/panel/data/db_pgsql.json",
        "/www/server/panel/plugin/pgsql_manager/database.json",
    ):
        try:
            if not os.path.exists(path):
                continue
            import json

            with open(path, "r") as f:
                data = json.load(f)
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        _add(item.get("name") or item.get("db_name"))
                    elif isinstance(item, str):
                        _add(item)
            elif isinstance(data, dict):
                for item in data.get("list") or data.get("data") or []:
                    if isinstance(item, dict):
                        _add(item.get("name") or item.get("db_name"))
        except Exception:
            pass

    return dbs


def list_postgres_databases():
    psql = _find_psql()
    port = _pgsql_port()
    pwd = _pgsql_root_password()
    results = []
    panel_dbs = _panel_pgsql_list()

    if psql:
        sql = "SELECT datname FROM pg_database WHERE datistemplate = false ORDER BY datname;"
        attempts = []

        # 1) peer auth as postgres OS user (non-interactive sudo)
        attempts.append(
            (["sudo", "-n", "-u", "postgres", psql, "-Atc", sql], None)
        )

        # 2) password auth on localhost
        env_base = os.environ.copy()
        if pwd:
            env_base["PGPASSWORD"] = pwd
        for user in ("postgres", "pgsql"):
            attempts.append(
                (
                    [
                        psql,
                        "-h",
                        "127.0.0.1",
                        "-p",
                        str(port),
                        "-U",
                        user,
                        "-d",
                        "postgres",
                        "-Atc",
                        sql,
                    ],
                    dict(env_base),
                )
            )

        # 3) local socket
        attempts.append(
            ([psql, "-U", "postgres", "-d", "postgres", "-Atc", sql], dict(env_base))
        )
        attempts.append(([psql, "-d", "postgres", "-Atc", sql], None))

        # 4) via aaPanel ExecShell (inherits panel environment)
        try:
            import public  # type: ignore

            shell_cmds = [
                "sudo -n -u postgres {} -Atc \"{}\"".format(psql, sql),
            ]
            if pwd:
                shell_cmds.append(
                    "PGPASSWORD={} {} -h 127.0.0.1 -p {} -U postgres -d postgres -Atc \"{}\"".format(
                        pwd.replace("'", "'\\''"), psql, port, sql
                    )
                )
            for sc in shell_cmds:
                try:
                    out, err = public.ExecShell(sc)
                    out = (out or "").strip()
                    if out and "error" not in out.lower():
                        skip = {"postgres", "template0", "template1"}
                        for line in out.splitlines():
                            name = line.strip()
                            if name and name not in skip and " " not in name:
                                results.append({"type": "postgres", "name": name})
                        if results:
                            return results
                except Exception:
                    pass
        except Exception:
            pass

        skip = {"postgres", "template0", "template1"}
        for cmd, env in attempts:
            code, out, err = _run(cmd, env=env)
            if code != 0 or not out.strip():
                continue
            for line in out.splitlines():
                name = line.strip()
                if name and name not in skip:
                    results.append({"type": "postgres", "name": name})
            if results:
                return results

    # Fallback / merge with panel-registered names
    if not results:
        return panel_dbs
    # Merge any panel-only names
    have = {d["name"] for d in results}
    for d in panel_dbs:
        if d["name"] not in have:
            results.append(d)
    return results


def list_all_databases():
    mysql = list_mysql_databases()
    postgres = list_postgres_databases()
    return ok(
        "OK",
        {
            "mysql": mysql,
            "postgres": postgres,
            "debug": {
                "psql": _find_psql(),
                "pg_port": _pgsql_port(),
                "has_pg_password": bool(_pgsql_root_password()),
                "mysql_count": len(mysql),
                "postgres_count": len(postgres),
            },
        },
    )


def dump_mysql(db_name, dest_file):
    ensure_dirs()
    pwd = _mysql_root_password()
    mysqldump = _find_mysql_bin("mysqldump")
    cmd = [
        mysqldump,
        "-uroot",
        "--single-transaction",
        "--quick",
        "--routines",
        "--triggers",
    ]
    if pwd:
        cmd.append("-p{}".format(pwd))
    cmd.append(db_name)
    code, out, err = _run(cmd)
    if code != 0:
        code, out, err = _run([mysqldump, "-uroot", "--single-transaction", "--quick", db_name])
    if code != 0:
        raise RuntimeError("mysqldump failed for {}: {}".format(db_name, err or out))
    if dest_file.endswith(".gz"):
        with gzip.open(dest_file, "wb", compresslevel=6) as f:
            f.write(out.encode("utf-8") if isinstance(out, str) else out)
    else:
        with open(dest_file, "w") as f:
            f.write(out)
    return dest_file


def _gzip_file(src_path, dest_gz):
    with open(src_path, "rb") as fin, gzip.open(dest_gz, "wb", compresslevel=6) as fout:
        shutil.copyfileobj(fin, fout)
    try:
        os.remove(src_path)
    except Exception:
        pass


def dump_postgres(db_name, dest_file):
    """Dump PostgreSQL DB. Prefer plain SQL (and .sql.gz) over custom -Fc."""
    ensure_dirs()
    pg_dump = _find_pg_dump()
    pwd = _pgsql_root_password()
    port = _pgsql_port()
    env = os.environ.copy()
    if pwd:
        env["PGPASSWORD"] = pwd

    want_gz = dest_file.endswith(".gz")
    plain_sql = dest_file.endswith(".sql") or dest_file.endswith(".sql.gz")
    write_target = dest_file
    if want_gz:
        # Dump plain SQL first, then gzip into dest_file
        fd, write_target = tempfile.mkstemp(prefix="pgdump_", suffix=".sql", dir=TMP_DIR)
        os.close(fd)

    if plain_sql:
        commands = [
            ["sudo", "-n", "-u", "postgres", pg_dump, "-f", write_target, db_name],
            [
                pg_dump,
                "-h",
                "127.0.0.1",
                "-p",
                str(port),
                "-U",
                "postgres",
                "-f",
                write_target,
                db_name,
            ],
        ]
    else:
        commands = [
            ["sudo", "-n", "-u", "postgres", pg_dump, "-Fc", "-f", write_target, db_name],
            [
                pg_dump,
                "-h",
                "127.0.0.1",
                "-p",
                str(port),
                "-U",
                "postgres",
                "-Fc",
                "-f",
                write_target,
                db_name,
            ],
            ["sudo", "-n", "-u", "postgres", pg_dump, "-f", write_target, db_name],
            [
                pg_dump,
                "-h",
                "127.0.0.1",
                "-p",
                str(port),
                "-U",
                "postgres",
                "-f",
                write_target,
                db_name,
            ],
        ]

    last_err = ""
    try:
        for cmd in commands:
            code, out, err = _run(cmd, env=env)
            if code == 0 and os.path.exists(write_target) and os.path.getsize(write_target) > 0:
                if want_gz:
                    _gzip_file(write_target, dest_file)
                    write_target = dest_file
                return dest_file
            last_err = err or out
        raise RuntimeError("pg_dump failed for {}: {}".format(db_name, last_err))
    finally:
        if want_gz and write_target != dest_file and os.path.exists(write_target):
            try:
                os.remove(write_target)
            except Exception:
                pass


def _db_dump_basename(db_name):
    """{database-name}-{YYYYMMDD_HHMMSS}.sql.gz"""
    stamp = time.strftime("%Y%m%d_%H%M%S")
    return "{}-{}.sql.gz".format(db_name, stamp)


def dump_databases(databases, work_dir):
    """Dump selected DBs into work_dir/databases/ as {name}-{time}.sql.gz."""
    ensure_dirs()
    db_dir = os.path.join(work_dir, "databases")
    if not os.path.exists(db_dir):
        os.makedirs(db_dir)
    files = []
    for item in databases or []:
        dtype = (item.get("type") or "").lower()
        name = item.get("name") or ""
        if not name or not re.match(r"^[A-Za-z0-9_\-]+$", name):
            continue
        dest = os.path.join(db_dir, _db_dump_basename(name))
        if dtype == "mysql":
            dump_mysql(name, dest)
            files.append(dest)
        elif dtype in ("postgres", "postgresql", "pgsql"):
            dump_postgres(name, dest)
            files.append(dest)
    return files
