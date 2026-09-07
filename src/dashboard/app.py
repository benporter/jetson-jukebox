#!/usr/bin/env python3
"""
app.py — FastAPI app for the jukebox request dashboard.

Always-on LAN service (jukebox-dashboard.service). Serves a static page + a JSON
API over the Parquet snapshot (see snapshot.py / queries.py). A background task
refreshes the snapshot every JUKEBOX_DASH_SNAPSHOT_SECONDS so the dashboard never
reads the live writer DB on a request.

Run:  uvicorn src.dashboard.app:app --host 0.0.0.0 --port 8088
"""
from __future__ import annotations

import asyncio
import contextlib
import os
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import queries, snapshot, sysinfo

STATIC_DIR = Path(__file__).resolve().parent / "static"
SNAPSHOT_SECONDS = int(os.environ.get("JUKEBOX_DASH_SNAPSHOT_SECONDS", "60"))


async def _snapshot_loop():
    """Refresh the Parquet snapshot on a timer (runs in a worker thread so the
    brief DuckDB read never blocks the event loop)."""
    while True:
        await asyncio.to_thread(snapshot.refresh_snapshot)
        await asyncio.sleep(SNAPSHOT_SECONDS)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    # Prime a snapshot immediately so the first page load has data.
    await asyncio.to_thread(snapshot.refresh_snapshot)
    task = asyncio.create_task(_snapshot_loop())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="Jukebox Dashboard", lifespan=lifespan)


@app.get("/healthz")
def healthz():
    return {"ok": True, "snapshot_age": snapshot.snapshot_age_seconds()}


@app.get("/api/requests")
def api_requests(
    status: str = Query("all"),
    room: str | None = Query(None),
    q: str | None = Query(None),
    dt_from: str | None = Query(None, alias="from"),
    dt_to: str | None = Query(None, alias="to"),
    limit: int = Query(1000, ge=1, le=100000),
):
    return queries.fetch_requests(
        status=status, room=room, q=q, dt_from=dt_from, dt_to=dt_to, limit=limit
    )


@app.get("/api/stats")
def api_stats(
    status: str = Query("all"),
    room: str | None = Query(None),
    q: str | None = Query(None),
    dt_from: str | None = Query(None, alias="from"),
    dt_to: str | None = Query(None, alias="to"),
):
    return queries.fetch_stats(
        status=status, room=room, q=q, dt_from=dt_from, dt_to=dt_to
    )


@app.get("/api/disk")
def api_disk():
    return sysinfo.disk_info()


@app.get("/api/rooms")
def api_rooms():
    return {"rooms": queries.distinct_rooms()}


# Static assets (vendored Grid.js, app.js) and the dashboard page.
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def index():
    return FileResponse(str(STATIC_DIR / "index.html"))
