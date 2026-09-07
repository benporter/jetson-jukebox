#!/usr/bin/env python3
"""
audible_resolve.py — resolve a spoken audiobook request to a Sonos favorite.

Audible is the **special case** (Spotify handles everything else). Unlike Spotify,
there is no public Audible catalog search API, and `musicsearch` is broken on this
S2 firmware — the only reliable play path is a **Sonos favorite** played by exact
title (`/{room}/favorite/<title>`). So the model is a **parent-curated shelf**:
the parent favorites allowed audiobooks in the Sonos app, and this module
fuzzy-matches the child's spoken title against those favorites.

"Audiobook" favorites are auto-detected by URI scheme: anything that ISN'T clearly
Spotify / internet-radio / http-stream is treated as a candidate (Audible books
surface as cloud-container favorites). An explicit allowlist
(JUKEBOX_AUDIBLE_FAVORITES, comma-separated exact titles) overrides detection.

CLI:  python3 src/audible_resolve.py "harry potter"
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
import urllib.request
from difflib import SequenceMatcher

SONOS_API = os.environ.get("SONOS_API", "http://127.0.0.1:5005")
MATCH_CUTOFF = float(os.environ.get("JUKEBOX_AUDIBLE_CUTOFF", "0.5"))

# URI schemes that are clearly NOT audiobooks (so we exclude them from matching).
_NON_AUDIOBOOK_SCHEMES = (
    "x-sonos-spotify:",      # Spotify track/album
    "x-sonosapi-stream:",    # internet radio
    "x-sonosapi-radio:",     # radio
    "x-sonosapi-hls:",       # radio/hls
    "x-rincon-stream:",      # line-in / stream
    "pndrradio:",            # Pandora radio
    "x-sonos-http:",         # http track (e.g. Amazon Music single)
)


def _get(path: str, timeout: float = 15.0):
    url = f"{SONOS_API}/{path}"
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.load(resp)


def _norm(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)   # drop punctuation/apostrophes
    return re.sub(r"\s+", " ", s).strip()


def _is_audiobook_candidate(fav: dict) -> bool:
    uri = (fav.get("uri") or "").lower()
    # The generic "Audible.com" container (empty uri) is a last-resort "open
    # Audible"; treat it as a candidate too.
    if not uri:
        return True
    return not uri.startswith(_NON_AUDIOBOOK_SCHEMES)


def _candidates() -> list[str]:
    """Favorite titles eligible to be audiobooks (allowlist or auto-detected)."""
    allow = [t.strip() for t in os.environ.get("JUKEBOX_AUDIBLE_FAVORITES", "").split(",")
             if t.strip()]
    favs = _get("favorites/detailed")
    titles = [f.get("title", "") for f in favs]
    if allow:
        allow_l = {t.lower() for t in allow}
        return [t for t in titles if t.lower() in allow_l]
    return [f.get("title", "") for f in favs if _is_audiobook_candidate(f)]


def _score(query_n: str, title_n: str) -> float:
    """0..1 match score. Rewards the spoken words being a subset of the title
    (so 'harry potter' strongly matches 'Harry Potter and the Sorcerer's Stone')
    and falls back to overall string similarity."""
    if not query_n or not title_n:
        return 0.0
    q_tokens = set(query_n.split())
    t_tokens = set(title_n.split())
    if q_tokens and q_tokens <= t_tokens:
        # all spoken words appear in the title — very likely the right book
        coverage = len(q_tokens) / max(1, len(t_tokens))
        return 0.85 + 0.15 * coverage
    ratio = SequenceMatcher(None, query_n, title_n).ratio()
    overlap = len(q_tokens & t_tokens) / max(1, len(q_tokens))
    return max(ratio, 0.6 * overlap)


def resolve_audiobook(query: str) -> tuple[str | None, list[str]]:
    """Return (best favorite title, all candidate titles considered).

    None if nothing clears the cutoff. Raises on a Sonos API failure so the
    caller can distinguish "no match" from "couldn't reach Sonos".
    """
    query_n = _norm(query)
    candidates = _candidates()
    best, best_score = None, 0.0
    for title in candidates:
        sc = _score(query_n, _norm(title))
        if sc > best_score:
            best, best_score = title, sc
    return (best if best_score >= MATCH_CUTOFF else None), candidates


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]).strip()
    if not q:
        print("usage: audible_resolve.py <book title>", file=sys.stderr)
        sys.exit(2)
    match, cands = resolve_audiobook(q)
    print(json.dumps({"query": q, "match": match, "candidates": cands}, indent=2))
    sys.exit(0 if match else 1)
