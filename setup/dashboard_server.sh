#!/usr/bin/env bash
#
# dashboard_server.sh — launch the jukebox request dashboard (FastAPI/uvicorn).
#
# Always-on LAN service (jukebox-dashboard.service). Reads a read-only Parquet
# snapshot of the request DB, so it never locks the writer (see
# src/dashboard/snapshot.py). Config in config/jukebox.env.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

# shellcheck disable=SC1091
[[ -f "$REPO/config/jukebox.env" ]] && source "$REPO/config/jukebox.env"

BIND="${JUKEBOX_DASH_BIND:-0.0.0.0}"
PORT="${JUKEBOX_DASH_PORT:-8088}"

# uvicorn + fastapi are installed --user; make the repo importable as `src.*`.
export PYTHONPATH="$REPO${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONUNBUFFERED=1

exec python3 -m uvicorn src.dashboard.app:app --host "$BIND" --port "$PORT" \
     --no-access-log --workers 1
