#!/usr/bin/env python3
"""
export_requests.py — dump the FULL request history for use elsewhere.

Reads the live DuckDB **read-only** (safe to run while the jukebox is playing —
never locks the writer) and writes every row of the `requests` table to a file.
Retention is permanent (see src/db.py), so this always gives you the complete
dataset, not a window.

Usage:
    python3 setup/export_requests.py                      # -> data/exports/requests-<count>.csv
    python3 setup/export_requests.py --format parquet     # csv | parquet | json | jsonl
    python3 setup/export_requests.py --out ~/mytoy/data.csv
    python3 setup/export_requests.py --format jsonl --out -   # '-' = stdout (pipe it)

Formats:
    csv     spreadsheet / pandas.read_csv — the default, most portable
    parquet columnar, typed, compact — best for pandas/polars/DuckDB analysis
    json    one big JSON array (easy to load whole)
    jsonl   one JSON object per line (stream-friendly, great for scripts/LLMs)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO / "data/jukebox.duckdb"


def main() -> int:
    ap = argparse.ArgumentParser(description="Export the full jukebox request history.")
    ap.add_argument("--format", "-f", default="csv",
                    choices=["csv", "parquet", "json", "jsonl"])
    ap.add_argument("--db", default=str(DEFAULT_DB), help="path to jukebox.duckdb")
    ap.add_argument("--out", "-o", default=None,
                    help="output file, or '-' for stdout. Default: data/exports/…")
    args = ap.parse_args()

    db = Path(args.db)
    if not db.exists():
        print(f"no DB at {db}", file=sys.stderr)
        return 1

    import duckdb
    con = duckdb.connect(str(db), read_only=True)   # read-only: won't touch the writer
    try:
        n = con.execute("SELECT count(*) FROM requests").fetchone()[0]

        # stdout path (great for piping into another project)
        if args.out == "-":
            _write_stream(con, args.format, sys.stdout)
            return 0

        if args.out:
            out = Path(args.out).expanduser()
        else:
            out = REPO / "data/exports" / f"requests-{n}.{args.format}"
        out.parent.mkdir(parents=True, exist_ok=True)

        if args.format in ("csv", "parquet"):
            # DuckDB writes these natively (typed, fast, no Python row loop).
            fmt = "FORMAT CSV, HEADER" if args.format == "csv" else "FORMAT PARQUET"
            con.execute(
                f"COPY (SELECT * FROM requests ORDER BY requested_at) "
                f"TO ? ({fmt})", [str(out)])
        else:
            with out.open("w") as fh:
                _write_stream(con, args.format, fh)
    finally:
        con.close()

    print(f"exported {n} request(s) -> {out}")
    return 0


def _write_stream(con, fmt: str, fh) -> None:
    """Write json / jsonl to an open file handle (stdout or a real file)."""
    cur = con.execute("SELECT * FROM requests ORDER BY requested_at")
    names = [d[0] for d in cur.description]
    rows = ({k: _jsonable(v) for k, v in zip(names, r)} for r in cur.fetchall())
    if fmt == "jsonl":
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    else:  # json array
        json.dump(list(rows), fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def _jsonable(v):
    """UUIDs, timestamps, etc. → strings so json.dumps is happy."""
    import datetime
    import uuid
    if isinstance(v, (datetime.datetime, datetime.date, uuid.UUID)):
        return str(v)
    return v


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        # downstream pipe closed early (e.g. `| head`) — not an error.
        sys.exit(0)
