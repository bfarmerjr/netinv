# SPDX-License-Identifier: AGPL-3.0-or-later
# NetInv — Copyright (C) 2026 Bill Farmer, Jr. See LICENSE.
"""Per-request timing and a summary of the gunicorn worker serving the page."""
import itertools
import os
import time

from flask import g

_BOOTED = time.time()  # gunicorn imports the app in each worker, so this is worker start
_requests = itertools.count(1)
_cache = {"at": 0.0, "workers": None}


def start_request():
    g.t0 = time.perf_counter()
    g.request_no = next(_requests)


def render_ms():
    return f"{(time.perf_counter() - g.t0) * 1000:.1f}"


def _parent_is_gunicorn(ppid):
    try:
        with open(f"/proc/{ppid}/cmdline", "rb") as f:
            return b"gunicorn" in f.read()
    except OSError:
        return False


def _count_children(ppid):
    """Number of live processes whose parent is ppid (the gunicorn master)."""
    count = 0
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/stat") as f:
                stat = f.read()
        except OSError:
            continue
        # Fields after the "(comm)" field: state, ppid, ...
        if int(stat.rpartition(")")[2].split()[1]) == ppid:
            count += 1
    return count


def _uptime(seconds):
    seconds = int(seconds)
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def worker_summary():
    pid, ppid = os.getpid(), os.getppid()
    n = g.get("request_no", 0)
    served = f"{n} request{'' if n == 1 else 's'}"
    uptime = _uptime(time.time() - _BOOTED)
    if not _parent_is_gunicorn(ppid):
        return f"Single process {pid} · up {uptime} · {served}"
    now = time.monotonic()
    if now - _cache["at"] > 10:
        _cache.update(at=now, workers=_count_children(ppid))
    threads = os.environ.get("NETINV_THREADS", "?")
    return (
        f"Worker {pid} of {_cache['workers']} × {threads} threads (master {ppid})"
        f" · up {uptime} · {served}"
    )
