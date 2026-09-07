#!/usr/bin/env python3
"""
spotify_resolve.py — resolve a search query to a single Spotify track.

The one place we turn "song name [artist]" into a concrete track. Pulled out of
sonos_play.sh so the pipeline gets the full track object (id, name, artist, uri,
explicit) to LOG and — later — to gate on (blocklist / quiet hours) before play.

Credentials come from node-sonos-http-api's settings.json (gitignored). The
Spotify search API intermittently returns empty 503s (~1 in 3-4 in a bad spell),
so we retry and only ever parse a real 200 body — never feed an empty 503 to the
JSON parser (see docs/sonos-notes.md).

CLI (used by sonos_play.sh): prints the resolved track as one JSON object, or
nothing + exit 1 on no match:
    python3 src/spotify_resolve.py "thunderstruck acdc"
"""
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SETTINGS = Path(os.environ.get(
    "SETTINGS", REPO / "tools/node-sonos-http-api/settings.json"))
MARKET = os.environ.get("MARKET", "US")


def _credentials() -> tuple[str, str]:
    s = json.loads(SETTINGS.read_text())
    sp = s.get("spotify", {})
    cid, sec = sp.get("clientId", ""), sp.get("clientSecret", "")
    if not cid or not sec:
        raise RuntimeError(f"spotify clientId/clientSecret missing in {SETTINGS}")
    return cid, sec


def _token(cid: str, sec: str, timeout: float = 15.0) -> str:
    auth = base64.b64encode(f"{cid}:{sec}".encode()).decode()
    req = urllib.request.Request(
        "https://accounts.spotify.com/api/token",
        data=b"grant_type=client_credentials",
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "Authorization": f"Basic {auth}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp).get("access_token", "")


def resolve(query: str, market: str = MARKET, retries: int = 6) -> dict | None:
    """Return the top track for `query` as a dict, or None if there's no match.

    dict keys: id, name, artist, uri, explicit. Raises RuntimeError only on a
    hard failure (no creds / token / search unavailable after retries) so the
    caller can distinguish "no match" (None) from "couldn't search" (raises).
    """
    query = (query or "").strip()
    if not query:
        return None
    cid, sec = _credentials()
    token = _token(cid, sec)
    if not token:
        raise RuntimeError("could not obtain Spotify access token")

    params = urllib.parse.urlencode({
        "q": query, "type": "track",
        # Spotify ranks limit=1 worse than limit>=3 — ask for a few, take the top.
        "limit": "5", "market": market,
    })
    url = f"https://api.spotify.com/v1/search?{params}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})

    body = None
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.status == 200:
                    body = json.load(resp)
                    break
        except urllib.error.HTTPError as e:
            # 503 (and friends) are the transient case — retry; don't parse body.
            print(f"  spotify search HTTP {e.code} (attempt {attempt}) — retrying…",
                  file=sys.stderr)
        except (urllib.error.URLError, OSError) as e:
            print(f"  spotify search error {e} (attempt {attempt}) — retrying…",
                  file=sys.stderr)
        time.sleep(1)
    if body is None:
        raise RuntimeError("Spotify search unavailable after retries")

    items = body.get("tracks", {}).get("items", [])
    if not items:
        return None
    t = items[0]
    artist = ", ".join(a["name"] for a in t.get("artists", []))
    return {
        "id": t["id"],
        "name": t["name"],
        "artist": artist,
        "uri": t.get("uri", f"spotify:track:{t['id']}"),
        "explicit": bool(t.get("explicit", False)),
    }


def resolve_song(title: str, artist: str = "", extra_query: str = "",
                 market: str = MARKET):
    """Resolve a song with progressive fallback. Returns (track_dict|None, used_query).

    Tries the most precise query first, then widens — crucially, it **drops the
    artist filter** so a hallucinated/wrong/misheard artist (a common failure with
    the small intent model, e.g. "Born to Be Wild" tagged Red Hot Chili Peppers)
    can't blackhole the search. The precise query is tried first, so a correct
    artist is still honored when it matches.

    Raises RuntimeError (from resolve) only on a hard search failure, so the caller
    can tell "no match anywhere" (None) from "couldn't search" (raises).
    """
    title = (title or "").strip()
    artist = (artist or "").strip()
    extra_query = (extra_query or "").strip()

    candidates = []
    if title and artist:
        candidates.append(f"track:{title} artist:{artist}")  # precise
    if title:
        candidates.append(f"track:{title}")                  # drop the artist filter
    if title and artist:
        candidates.append(f"{title} {artist}")                # loose, unfiltered
    if title:
        candidates.append(title)
    if extra_query:
        candidates.append(extra_query)
    # de-dupe, preserve order
    seen = set()
    candidates = [c for c in candidates if c and not (c in seen or seen.add(c))]

    for q in candidates:
        track = resolve(q, market=market)
        if track:
            return track, q
    return None, (candidates[0] if candidates else "")


# --- Collections: albums & playlists ----------------------------------------
# Same Spotify search, different `type`; same Sonos play endpoint
# (/{room}/spotify/now/spotify:album:ID | spotify:playlist:ID — the bridge wraps
# non-track URIs as a container automatically).

def _playlist_map() -> dict:
    """Parent-curated 'spoken name' -> spotify:playlist:URI map, for PRIVATE
    playlists that public search can't find. From JUKEBOX_PLAYLISTS, e.g.
    "bedtime=spotify:playlist:abc,party=spotify:playlist:xyz"."""
    out = {}
    for pair in os.environ.get("JUKEBOX_PLAYLISTS", "").split(","):
        if "=" in pair:
            name, uri = pair.split("=", 1)
            name, uri = name.strip().lower(), uri.strip()
            if name and uri:
                out[name] = uri
    return out


def _api_get(url: str, token: str, retries: int = 4):
    """Authed Spotify GET with the same 503-retry discipline as search."""
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.status == 200:
                    return json.load(resp)
        except urllib.error.HTTPError as e:
            # 4xx (esp. 403: Spotify restricts enumerating user playlists' tracks
            # under client-credentials) is permanent — don't burn retries on it.
            if 400 <= e.code < 500:
                raise RuntimeError(f"Spotify GET HTTP {e.code} (no retry): {url}")
            print(f"  spotify GET HTTP {e.code} (attempt {attempt})", file=sys.stderr)
        except (urllib.error.URLError, OSError) as e:
            print(f"  spotify GET error {e} (attempt {attempt})", file=sys.stderr)
        time.sleep(1)
    raise RuntimeError(f"Spotify GET unavailable after retries: {url}")


def resolve_album(query: str, market: str = MARKET):
    """Top album for a query → {kind, id, uri, name, artist} or None."""
    query = (query or "").strip()
    if not query:
        return None
    token = _token(*_credentials())
    params = urllib.parse.urlencode({"q": query, "type": "album",
                                     "limit": "5", "market": market})
    body = _api_get(f"https://api.spotify.com/v1/search?{params}", token)
    items = body.get("albums", {}).get("items", [])
    if not items:
        return None
    a = items[0]
    return {"kind": "album", "id": a["id"],
            "uri": a.get("uri", f"spotify:album:{a['id']}"), "name": a["name"],
            "artist": ", ".join(x["name"] for x in a.get("artists", []))}


def resolve_playlist(query: str, market: str = MARKET):
    """Top playlist for a query → {kind, id, uri, name, artist} or None.
    Checks the parent name→URI map first (private playlists), then public search."""
    query = (query or "").strip()
    if not query:
        return None
    mapped = _playlist_map().get(query.lower())
    if mapped:
        return {"kind": "playlist", "id": mapped.rsplit(":", 1)[-1],
                "uri": mapped, "name": query, "artist": ""}
    # Your OWN playlists (incl. private) via one-time user OAuth — see
    # docs/spotify-playlists-research.md. Optional and degrades gracefully: if auth
    # was never set up, or the lookup errors, fall through to public search below.
    try:
        import spotify_user
        if spotify_user.available():
            mine = spotify_user.resolve_playlist(query)
            if mine:
                return mine
    except Exception as e:
        print(f"  (user-playlist lookup skipped: {e})", file=sys.stderr)
    token = _token(*_credentials())
    params = urllib.parse.urlencode({"q": query, "type": "playlist",
                                     "limit": "5", "market": market})
    body = _api_get(f"https://api.spotify.com/v1/search?{params}", token)
    items = [p for p in body.get("playlists", {}).get("items", []) if p]
    if not items:
        return None
    p = items[0]
    return {"kind": "playlist", "id": p["id"],
            "uri": p.get("uri", f"spotify:playlist:{p['id']}"), "name": p["name"],
            "artist": (p.get("owner") or {}).get("display_name", "")}


def resolve_collection(kind: str, query: str, market: str = MARKET):
    return resolve_album(query, market) if kind == "album" \
        else resolve_playlist(query, market)


def collection_explicit(coll: dict, max_tracks: int = 120, market: str = MARKET):
    """Scan an album/playlist for Spotify-flagged explicit tracks.

    Returns (has_explicit, n_explicit, n_checked). Best-effort: on any scan error
    returns (False, 0, 0) so it **fails open** — the per-song gate is the strict
    one, and collections are usually parent-curated. The pipeline blocks playback
    when has_explicit is True (consistent with the single-song explicit refusal).
    """
    try:
        token = _token(*_credentials())
        kind, cid = coll["kind"], coll["id"]
        n = n_expl = 0
        if kind == "album":
            url = (f"https://api.spotify.com/v1/albums/{cid}/tracks"
                   f"?limit=50&market={market}")
            while url and n < max_tracks:
                body = _api_get(url, token)
                for t in body.get("items", []):
                    n += 1
                    n_expl += 1 if t.get("explicit") else 0
                url = body.get("next")
        else:  # playlist — fields= keeps the payload tiny
            url = (f"https://api.spotify.com/v1/playlists/{cid}/tracks"
                   f"?limit=100&market={market}&fields=next,items(track(explicit))")
            while url and n < max_tracks:
                body = _api_get(url, token)
                for it in body.get("items", []):
                    t = it.get("track") or {}
                    n += 1
                    n_expl += 1 if t.get("explicit") else 0
                url = body.get("next")
        return (n_expl > 0, n_expl, n)
    except Exception as e:
        print(f"(explicit scan failed, allowing: {e})", file=sys.stderr)
        return (False, 0, 0)


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or sys.stdin.read().strip()
    track = resolve(q)
    if not track:
        print(f"no Spotify match for: {q}", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(track, ensure_ascii=False))
