#!/usr/bin/env python3
"""
queries.py — read-only queries over the Parquet snapshot.

Every function opens a fresh in-memory DuckDB connection and reads
`data/dashboard/requests.parquet` (the snapshot written by snapshot.py). Nothing
here ever touches the live writer DB, so the dashboard cannot lock playback.
"""
from __future__ import annotations

import duckdb

from . import snapshot

# Columns surfaced to the UI table, in display order.
COLUMNS = [
    "requested_at",
    "source",
    "intent_type",
    "held_seconds",
    "transcript",
    "intent_title",
    "intent_artist",
    "spotify_query",
    "result_track_name",
    "result_artist",
    "result_explicit",
    "outcome",
    "room",
    "volume_applied",
    "block_reason",
    "error_message",
]

# Map a UI "status" chip to a SQL predicate over the row.
_STATUS_SQL = {
    "all": "TRUE",
    "played": "played = TRUE",
    "failed": "outcome IN ('no_match', 'play_failed')",
    "blocked": "outcome LIKE 'blocked%'",
}


def _con() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(database=":memory:")


def _have_snapshot() -> bool:
    return snapshot.SNAPSHOT.exists()


def _where(status: str, room: str | None, q: str | None,
           dt_from: str | None, dt_to: str | None) -> tuple[str, list]:
    """Build a WHERE clause + params from the filter inputs."""
    clauses = [_STATUS_SQL.get(status, "TRUE")]
    params: list = []
    if room:
        clauses.append("room = ?")
        params.append(room)
    if q:
        clauses.append(
            "(lower(transcript) LIKE ? OR lower(intent_title) LIKE ? "
            "OR lower(intent_artist) LIKE ? OR lower(result_track_name) LIKE ? "
            "OR lower(result_artist) LIKE ?)"
        )
        like = f"%{q.lower()}%"
        params.extend([like] * 5)
    if dt_from:
        clauses.append("requested_at >= ?::TIMESTAMP")
        params.append(dt_from)
    if dt_to:
        clauses.append("requested_at <= ?::TIMESTAMP")
        params.append(dt_to)
    return " AND ".join(clauses), params


def fetch_requests(status: str = "all", room: str | None = None,
                   q: str | None = None, dt_from: str | None = None,
                   dt_to: str | None = None, limit: int = 1000) -> dict:
    """Return filtered request rows (newest first) plus metadata.

    `limit` caps how many rows the TABLE renders — it is a display cap only, never
    a data cap: the DB keeps every request forever (see the retention note in
    src/db.py). The KPI counts in fetch_stats() are uncapped, so totals stay
    correct no matter how many rows exist. To pull the full history, don't page
    this API — export the DB directly (setup/export_requests.py; docs/dashboard.md).
    """
    age = snapshot.snapshot_age_seconds()
    if not _have_snapshot():
        return {"rows": [], "count": 0, "columns": COLUMNS, "snapshot_age": age,
                "snapshot_ready": False}

    where, params = _where(status, room, q, dt_from, dt_to)
    cols = ", ".join(COLUMNS)
    sql = (
        f"SELECT {cols} FROM read_parquet(?) WHERE {where} "
        f"ORDER BY requested_at DESC LIMIT ?"
    )
    con = _con()
    try:
        cur = con.execute(sql, [str(snapshot.SNAPSHOT), *params, int(limit)])
        names = [d[0] for d in cur.description]
        rows = [dict(zip(names, r)) for r in cur.fetchall()]
    finally:
        con.close()

    # JSON-safe: stringify timestamps.
    for row in rows:
        for k in ("requested_at",):
            if row.get(k) is not None:
                row[k] = str(row[k])
    return {"rows": rows, "count": len(rows), "columns": COLUMNS,
            "snapshot_age": age, "snapshot_ready": True}


def fetch_stats(status: str = "all", room: str | None = None,
                q: str | None = None, dt_from: str | None = None,
                dt_to: str | None = None) -> dict:
    """Accurate (non-row-capped) counts + tuning lists for the selected range.

    The KPI strip uses these server-side counts rather than counting the capped
    table rows, so the numbers are correct even with thousands of requests.
    """
    if not _have_snapshot():
        return {"total": 0, "played": 0, "failed": 0, "blocked": 0,
                "no_match": 0, "play_failed": 0,
                "top_failed_titles": [], "top_blocked_artists": [],
                "snapshot_ready": False}

    where, params = _where(status, room, q, dt_from, dt_to)
    src = "read_parquet(?)"
    con = _con()
    try:
        agg = con.execute(
            f"""
            SELECT
              count(*)                                              AS total,
              count(*) FILTER (WHERE played)                        AS played,
              count(*) FILTER (WHERE outcome IN ('no_match','play_failed')) AS failed,
              count(*) FILTER (WHERE outcome LIKE 'blocked%')       AS blocked,
              count(*) FILTER (WHERE outcome = 'no_match')          AS no_match,
              count(*) FILTER (WHERE outcome = 'play_failed')       AS play_failed
            FROM {src} WHERE {where}
            """,
            [str(snapshot.SNAPSHOT), *params],
        ).fetchone()

        failed_titles = con.execute(
            f"""
            SELECT coalesce(nullif(intent_title,''),'(none)') AS title, count(*) AS n
            FROM {src}
            WHERE outcome IN ('no_match','play_failed') AND ({where})
            GROUP BY 1 ORDER BY n DESC, title LIMIT 10
            """,
            [str(snapshot.SNAPSHOT), *params],
        ).fetchall()

        blocked_artists = con.execute(
            f"""
            SELECT coalesce(nullif(result_artist,''),'(unknown)') AS artist, count(*) AS n
            FROM {src}
            WHERE outcome LIKE 'blocked%' AND ({where})
            GROUP BY 1 ORDER BY n DESC, artist LIMIT 10
            """,
            [str(snapshot.SNAPSHOT), *params],
        ).fetchall()
    finally:
        con.close()

    keys = ["total", "played", "failed", "blocked", "no_match", "play_failed"]
    out = dict(zip(keys, agg))
    out["top_failed_titles"] = [{"title": t, "n": n} for t, n in failed_titles]
    out["top_blocked_artists"] = [{"artist": a, "n": n} for a, n in blocked_artists]
    out["snapshot_ready"] = True
    return out


def distinct_rooms() -> list[str]:
    if not _have_snapshot():
        return []
    con = _con()
    try:
        rows = con.execute(
            "SELECT DISTINCT room FROM read_parquet(?) "
            "WHERE room IS NOT NULL AND room <> '' ORDER BY room",
            [str(snapshot.SNAPSHOT)],
        ).fetchall()
    finally:
        con.close()
    return [r[0] for r in rows]
