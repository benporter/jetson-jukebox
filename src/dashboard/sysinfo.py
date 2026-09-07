#!/usr/bin/env python3
"""
sysinfo.py — disk & storage health for the dashboard.

The jukebox writes one DuckDB row per request and a small Parquet snapshot, so
disk growth is tiny — but a full root volume would crash recording/playback, so
the dashboard shows a fuel gauge and warns before it's a problem.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from . import snapshot
from .snapshot import LIVE_DB, SNAPSHOT

WARN_PCT = int(os.environ.get("JUKEBOX_DISK_WARN_PCT", "10"))  # warn under N% free


def _size(p: Path) -> int:
    try:
        return p.stat().st_size
    except OSError:
        return 0


def disk_info() -> dict:
    total, used, free = shutil.disk_usage("/")
    free_pct = round(free / total * 100, 1) if total else 0.0
    if free_pct < max(1, WARN_PCT // 2):
        level = "critical"
    elif free_pct < WARN_PCT:
        level = "warn"
    else:
        level = "ok"
    return {
        "total_bytes": total,
        "used_bytes": used,
        "free_bytes": free,
        "free_pct": free_pct,
        "warn_pct": WARN_PCT,
        "level": level,
        "db_bytes": _size(LIVE_DB),
        "db_wal_bytes": _size(LIVE_DB.with_name(LIVE_DB.name + ".wal")),
        "snapshot_bytes": _size(SNAPSHOT),
        "snapshot_age": snapshot.snapshot_age_seconds(),
    }
