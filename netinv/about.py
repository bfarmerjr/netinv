# SPDX-License-Identifier: AGPL-3.0-or-later
# NetInv — Copyright (C) 2026 Bill Farmer, Jr. See LICENSE.
"""Facts for the About page: running environment, dependencies, source bundle."""
import io
import os
import platform
import re
import socket
import sqlite3
import sys
import tarfile
from importlib import metadata

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REQ_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(\[[^\]]*\])?\s*([^;]*?)\s*(?:;\s*(.*))?$")

# Not pip packages, but NetInv needs them: f-strings/typing used need 3.11+
# (tested on 3.13), and SQLite UPSERT (ON CONFLICT ... DO UPDATE) needs 3.24.
PLATFORM_MINIMUMS = {"Python": "3.11", "SQLite": "3.24"}

# Files that make up the Corresponding Source offered under AGPL section 13.
SOURCE_ITEMS = ("LICENSE", "README.md", "CHANGELOG.md", "requirements.txt", "requirements.lock",
                "run.sh", "netinv.conf.example", "deploy", "samples", "netinv")


def _norm(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def _minimum(spec):
    m = re.search(r"(>=|~=|==)\s*([^,\s]+)", spec or "")
    return m.group(2) if m else None


def _parse(req):
    m = REQ_RE.match(req)
    if not m or (m.group(4) and "extra" in m.group(4)):
        return None
    return m.group(1), m.group(3)


def dependencies():
    """Every installed package NetInv needs, with minimum and installed version.

    Direct dependencies come from requirements.txt; transitive ones from each
    package's own metadata. Minimum is the highest lower bound any requirer asks for.
    """
    direct = []
    with open(os.path.join(PROJECT_ROOT, "requirements.txt")) as f:
        for line in f:
            line = line.split("#", 1)[0].strip()
            parsed = line and _parse(line)
            if parsed:
                direct.append(parsed)

    found = {}  # normalized name -> row
    queue = [(name, spec, "NetInv") for name, spec in direct]
    while queue:
        name, spec, required_by = queue.pop(0)
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue  # e.g. backports only needed on older Pythons
        key = _norm(dist.metadata["Name"])
        row = found.get(key)
        if row is None:
            row = found[key] = {
                "name": dist.metadata["Name"], "installed": dist.version, "minimum": None,
                "required_by": [], "license": _license(dist), "direct": required_by == "NetInv",
            }
            for req in dist.requires or []:
                parsed = _parse(req)
                if parsed:
                    queue.append((parsed[0], parsed[1], row["name"]))
        if required_by not in row["required_by"]:
            row["required_by"].append(required_by)
        low = _minimum(spec)
        if low and (row["minimum"] is None or _vkey(low) > _vkey(row["minimum"])):
            row["minimum"] = low
    rows = sorted(found.values(), key=lambda r: (not r["direct"], r["name"].lower()))
    platform_rows = [
        {"name": "Python", "installed": platform.python_version(), "minimum": PLATFORM_MINIMUMS["Python"],
         "required_by": ["NetInv"], "license": "PSF-2.0", "direct": True},
        {"name": "SQLite", "installed": sqlite3.sqlite_version, "minimum": PLATFORM_MINIMUMS["SQLite"],
         "required_by": ["NetInv"], "license": "Public domain", "direct": True},
    ]
    return platform_rows + rows


def _vkey(version):
    return tuple(int(p) if p.isdigit() else 0 for p in re.split(r"[.+-]", version))


def _license(dist):
    md = dist.metadata
    if md.get("License-Expression"):
        return md["License-Expression"]
    classifiers = [c.rsplit(" :: ", 1)[-1] for c in md.get_all("Classifier") or [] if c.startswith("License ::")]
    if classifiers:
        return ", ".join(classifiers)
    first_line = (md.get("License") or "").strip().split("\n", 1)[0]
    return first_line[:60] or "—"


def _os_name():
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return platform.system()


def _server():
    try:
        import gunicorn
        if "gunicorn" in os.environ.get("SERVER_SOFTWARE", "") or _parent_cmd_has(b"gunicorn"):
            return f"gunicorn {gunicorn.__version__}"
    except ImportError:
        pass
    return "Flask development server / WSGI"


def _parent_cmd_has(word):
    try:
        with open(f"/proc/{os.getppid()}/cmdline", "rb") as f:
            return word in f.read()
    except OSError:
        return False


def _size(path):
    total = sum(os.path.getsize(p) for p in (path, path + "-wal") if os.path.exists(p))
    for unit in ("B", "KB", "MB", "GB"):
        if total < 1024 or unit == "GB":
            return f"{total:.0f} {unit}" if unit == "B" else f"{total:.1f} {unit}"
        total /= 1024


def environment(app):
    db_path = app.config["DATABASE"]
    return [
        ("Host", socket.getfqdn()),
        ("Operating system", f"{_os_name()} · kernel {platform.release()} · {platform.machine()}"),
        ("Python", f"{platform.python_implementation()} {platform.python_version()} ({sys.executable})"),
        ("Web server", _server()),
        ("Listen address", os.environ.get("NETINV_BIND", "—")),
        ("Trusted proxy hops", os.environ.get("NETINV_PROXY_HOPS", "1")),
        ("SQLite", f"{sqlite3.sqlite_version} · {db_path} ({_size(db_path)})"),
        ("Timestamps", "Stored in UTC; shown in your browser's time zone"),
    ]


def source_tarball(version):
    buf = io.BytesIO()
    prefix = f"netinv-{version}"

    def skip(info):
        if "__pycache__" in info.name or info.name.endswith(".pyc"):
            return None
        info.uid = info.gid = 0
        info.uname = info.gname = ""
        return info

    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for item in SOURCE_ITEMS:
            path = os.path.join(PROJECT_ROOT, item)
            if os.path.exists(path):
                tar.add(path, arcname=f"{prefix}/{item}", filter=skip)
    return buf.getvalue()
