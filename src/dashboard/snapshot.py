#!/usr/bin/env python3
"""
snapshot.py — decouple the dashboard from the live request DB.

The dashboard MUST NOT lock the writer's database. DuckDB is single-writer:
`jukebox-pawkey` opens `data/jukebox.duckdb` read-write (briefly) per request.
So the dashboard never reads the live file on a page view. Instead, a refresher
touches the live DB **read-only, once every N seconds**, and exports the
`requests` table to a Parquet snapshot. Every API query then reads the Parquet
snapshot — zero contact with the live file, zero contention with playback.

That bounds live-DB contact to one short read per interval (the daemon already
retries on lock, see src/db.py), instead of one per HTTP request.

Atomic writes: export to a temp file, then os.replace() onto the snapshot path,
so a query never sees a half-written Parquet.
"""
import os
import time
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parent.parent.parent
LIVE_DB = Path(os.environ.get("JUKEBOX_DB", REPO / "data/jukebox.duckdb"))
SNAP_DIR = Path(os.environ.get("JUKEBOX_DASH_SNAP_DIR", REPO / "data/dashboard"))
SNAPSHOT = SNAP_DIR / "requests.parquet"


def refresh_snapshot(retries: int = 5, backoff: float = 0.4) -> bool:
    """Export the live `requests` table to the Parquet snapshot (read-only).

    Returns True on success, False if the live DB is missing/empty/locked after
    retries. Never raises — the dashboard keeps serving the previous snapshot.
    """
    if not LIVE_DB.exists():
        return False
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SNAPSHOT.with_suffix(".parquet.tmp")
    last_err = None
    for attempt in range(retries):
        con = None
        try:
            # read_only=True takes only a shared lock; the brief overlap with the
            # writer's exclusive lock is what the retry loop below absorbs.
            con = duckdb.connect(str(LIVE_DB), read_only=True)
            con.execute(
                "COPY (SELECT * FROM requests) TO ? (FORMAT PARQUET)", [str(tmp)]
            )
            con.close()
            con = None
            os.replace(tmp, SNAPSHOT)  # atomic swap
            return True
        except Exception as e:  # lock contention, missing table, etc.
            last_err = e
            if con is not None:
                try:
                    con.close()
                except Exception:
                    pass
            time.sleep(backoff * (attempt + 1))
    # Clean up a stray temp file; report but don't crash.
    try:
        tmp.unlink(missing_ok=True)
    except Exception:
        pass
    print(f"[dashboard] snapshot refresh failed: {last_err}", flush=True)
    return False


def snapshot_age_seconds() -> float | None:
    """Seconds since the snapshot was last written, or None if it doesn't exist."""
    try:
        return max(0.0, time.time() - SNAPSHOT.stat().st_mtime)
    except FileNotFoundError:
        return None


if __name__ == "__main__":
    ok = refresh_snapshot()
    print(f"snapshot {'written' if ok else 'NOT written'} -> {SNAPSHOT}")
