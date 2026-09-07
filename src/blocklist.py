#!/usr/bin/env python3
"""
blocklist.py — content gate: decide whether a resolved track may play.

First rule: refuse tracks Spotify flags **explicit**. Built to grow — per-artist
and per-title blocklists will plug into check() next (read from a DuckDB
`blocklist` table / config), each returning a short reason string.

A reason becomes BOTH the logged `block_reason` and the request `outcome`
(`blocked_<kind>`), so the dashboard's Blocked view explains exactly why a song
was refused. Deterministic: if any rule fires, the song does not play.

Toggle the explicit rule with JUKEBOX_BLOCK_EXPLICIT (default on).
"""
import os


def _truthy(v: str) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "on")


# Read at import (the daemon restarts to pick up config changes, same as the rest
# of the pipeline). Default ON — refusing explicit lyrics is the whole point.
BLOCK_EXPLICIT = _truthy(os.environ.get("JUKEBOX_BLOCK_EXPLICIT", "1"))


def check(track: dict | None) -> str | None:
    """Return a block reason if `track` must NOT play, else None.

    Reason convention: ``"<kind>"`` or ``"<kind>:<detail>"``. The part before the
    colon is the outcome suffix (`blocked_<kind>`); the full string is logged as
    `block_reason`. Examples: ``"explicit"``, future ``"artist:Eminem"``.
    """
    if not track:
        return None
    if BLOCK_EXPLICIT and track.get("explicit"):
        return "explicit"
    # Future rules slot in here, e.g.:
    #   if track.get("artist") in artist_blocklist(): return f"artist:{track['artist']}"
    #   if track.get("name")   in title_blocklist():  return f"title:{track['name']}"
    return None


def outcome_for(reason: str) -> str:
    """Map a block reason to its DB outcome: 'explicit' -> 'blocked_explicit'."""
    kind = reason.split(":", 1)[0]
    return f"blocked_{kind}"
