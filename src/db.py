#!/usr/bin/env python3
"""
db.py — DuckDB request logging for the jukebox.

Logs one row per SONG request to data/jukebox.duckdb: the raw transcript, the
parsed intent, the track Spotify search returned (incl. its explicit flag), and
whether it actually played. Powers usage review now, and the planned night/morning
gate (`requested_at`) and explicit/artist blocklist (`result_explicit`, `outcome`,
`block_reason`) later.

Design notes:
- **RETENTION IS PERMANENT — never purge.** This table is append-only by intent
  (the owner wants the full request history to accumulate forever as a dataset).
  There is deliberately NO retention window, DELETE, DROP, TRUNCATE, or vacuum
  anywhere in this codebase. Do NOT add a "cleanup"/rotation job. The data is
  tiny (a few hundred bytes/row → single-digit MB over years) and storage is
  ample. The dashboard's row `limit` is a DISPLAY cap only, not a data cap.
- **Open → insert → close per call.** DuckDB is single-writer; holding the file
  open would block you from querying it live. Requests are seconds apart at most,
  so per-call connections are free and keep the DB inspectable between writes.
- **Logging never breaks playback.** Every write is best-effort; on any error we
  warn to stderr and carry on (same principle as the LED).
- Timestamps are LOCAL time (datetime.now()) so the future quiet-hours gate can
  reason in wall-clock: WHERE hour(requested_at) >= 20.

Inspect it live (read-only, won't fight the daemon's writer):
    python3 -c "import duckdb;[print(r) for r in duckdb.connect('data/jukebox.duckdb',read_only=True).execute('select requested_at,transcript,result_track_name,result_explicit,outcome from requests order by requested_at desc limit 20').fetchall()]"
"""
import os
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("JUKEBOX_DB", REPO / "data/jukebox.duckdb"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    request_id        UUID,
    requested_at      TIMESTAMP,   -- local time of the request
    source            VARCHAR,     -- pawkey / cli / test
    held_seconds      DOUBLE,      -- how long the paw was held (mis-tap / truncation)
    transcript        VARCHAR,     -- raw STT text
    intent_type       VARCHAR,     -- always 'song' here (only songs are logged)
    intent_title      VARCHAR,
    intent_artist     VARCHAR,
    intent_room       VARCHAR,     -- room the child named ('' if none)
    intent_volume     INTEGER,     -- explicit volume asked for, else NULL
    intent_json       JSON,        -- full raw intent (forward-compatible)
    spotify_query     VARCHAR,     -- the search string sent to Spotify
    result_track_id   VARCHAR,     -- track search returned
    result_track_name VARCHAR,
    result_artist     VARCHAR,
    result_uri        VARCHAR,
    result_explicit   BOOLEAN,     -- spine of the future explicit-lyrics blocklist
    outcome           VARCHAR,     -- played / no_match / play_failed / blocked_* (future)
    played            BOOLEAN,
    played_at         TIMESTAMP,
    room              VARCHAR,     -- effective room it went to
    volume_applied    INTEGER,
    block_reason      VARCHAR,     -- future: 'explicit', 'artist:X', 'after 20:30'
    error_message     VARCHAR      -- on play_failed (Spotify 503 / Sonos 500 etc.)
);
"""

_COLUMNS = [
    "request_id", "requested_at", "source", "held_seconds", "transcript",
    "intent_type", "intent_title", "intent_artist", "intent_room",
    "intent_volume", "intent_json", "spotify_query", "result_track_id",
    "result_track_name", "result_artist", "result_uri", "result_explicit",
    "outcome", "played", "played_at", "room", "volume_applied",
    "block_reason", "error_message",
]


def _connect(read_only: bool = False, retries: int = 4):
    import duckdb  # imported lazily so the pipeline runs even if duckdb is absent
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    last = None
    for attempt in range(retries):
        try:
            con = duckdb.connect(str(DB_PATH), read_only=read_only)
            if not read_only:
                con.execute(SCHEMA)
            return con
        except duckdb.IOException as e:   # file locked by another process
            last = e
            time.sleep(0.5)
    raise last


def init() -> None:
    """Create the DB + table if missing (idempotent)."""
    con = _connect()
    con.close()


def log_request(rec: dict) -> None:
    """Insert one song-request row. Best-effort: never raises into the pipeline."""
    try:
        rec = dict(rec)
        rec.setdefault("request_id", str(uuid.uuid4()))
        rec.setdefault("requested_at", datetime.now())
        values = [rec.get(c) for c in _COLUMNS]
        placeholders = ", ".join(["?"] * len(_COLUMNS))
        con = _connect()
        try:
            con.execute(
                f"INSERT INTO requests ({', '.join(_COLUMNS)}) VALUES ({placeholders})",
                values,
            )
        finally:
            con.close()
    except Exception as e:  # logging must never break playback
        print(f"(db log failed: {e})", file=sys.stderr)


if __name__ == "__main__":
    init()
    con = _connect(read_only=True)
    n = con.execute("SELECT count(*) FROM requests").fetchone()[0]
    print(f"db at {DB_PATH} — {n} request(s) logged")
    con.close()
