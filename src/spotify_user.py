#!/usr/bin/env python3
"""
spotify_user.py — resolve the user's OWN playlists (incl. PRIVATE) by name.

Discovery only — playback is unchanged. This adds the one thing client-credentials
auth can't do: find your *private* / collaborative playlists by spoken name. It
uses the Spotify **Authorization Code flow** (one-time consent via
`setup/spotify_user_auth.py`, refresh token cached in
`config/spotify-user-tokens.json`) to call `GET /me/playlists` with **read-only**
scopes (`playlist-read-private`, `playlist-read-collaborative`). It never gets a
playback-control scope. The resolved `spotify:playlist:ID` still plays through the
Sonos container endpoint under Sonos's own linked account (no Premium needed on our
side). Full rationale + the rejected "Spotify Connect → Sonos" path:
`docs/spotify-playlists-research.md`.

Degrades gracefully: if the tokens file is absent (auth never run) `available()`
is False and `spotify_resolve.resolve_playlist()` falls back to public search — so
the box keeps working without user-OAuth configured. Same pattern as Piper TTS.

CLI:
    python3 src/spotify_user.py                 # list my playlists (name → uri)
    python3 src/spotify_user.py "bedtime"       # resolve one by fuzzy name
    python3 src/spotify_user.py --refresh        # force-refresh the cache
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from difflib import SequenceMatcher
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SETTINGS = Path(os.environ.get(
    "SETTINGS", REPO / "tools/node-sonos-http-api/settings.json"))
TOKENS = Path(os.environ.get(
    "JUKEBOX_SPOTIFY_USER_TOKENS", REPO / "config/spotify-user-tokens.json"))
CACHE = Path(os.environ.get(
    "JUKEBOX_SPOTIFY_PLAYLIST_CACHE", REPO / "data/spotify-playlists-cache.json"))
CACHE_TTL = float(os.environ.get("JUKEBOX_SPOTIFY_PLAYLIST_CACHE_TTL", "21600"))  # 6h
MATCH_CUTOFF = float(os.environ.get("JUKEBOX_SPOTIFY_PLAYLIST_CUTOFF", "0.6"))

# Read-only. Do NOT add playback/modify scopes — this box never controls Spotify
# playback directly (see the Connect dead-end in docs/spotify-playlists-research.md).
SCOPES = "playlist-read-private playlist-read-collaborative"
REDIRECT_URI = os.environ.get(
    "JUKEBOX_SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8090/callback")
TOKEN_URL = "https://accounts.spotify.com/api/token"
AUTH_URL = "https://accounts.spotify.com/authorize"


def available() -> bool:
    """True if user-OAuth has been set up (tokens file present)."""
    return TOKENS.exists()


def client_creds() -> tuple[str, str]:
    """Spotify app clientId/secret — the SAME app node-sonos-http-api uses for
    search (its settings.json). The redirect URI must be registered on that app."""
    s = json.loads(SETTINGS.read_text())
    sp = s.get("spotify", {})
    cid, sec = sp.get("clientId", ""), sp.get("clientSecret", "")
    if not cid or not sec:
        raise RuntimeError(f"spotify clientId/clientSecret missing in {SETTINGS}")
    return cid, sec


# --- token storage / refresh -------------------------------------------------

def _load_tokens() -> dict:
    if not TOKENS.exists():
        raise RuntimeError(
            f"no Spotify user tokens at {TOKENS} — run "
            f"`python3 setup/spotify_user_auth.py` once to authorize.")
    return json.loads(TOKENS.read_text())


def save_tokens(d: dict) -> None:
    """Write tokens 0600 (they're a credential — gitignored + owner-only)."""
    TOKENS.parent.mkdir(parents=True, exist_ok=True)
    TOKENS.write_text(json.dumps(d, indent=2))
    try:
        os.chmod(TOKENS, 0o600)
    except OSError:
        pass


def _post_token(data: dict, timeout: float = 15.0) -> dict:
    cid, sec = client_creds()
    auth = base64.b64encode(f"{cid}:{sec}".encode()).decode()
    req = urllib.request.Request(
        TOKEN_URL,
        data=urllib.parse.urlencode(data).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "Authorization": f"Basic {auth}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def exchange_code(code: str) -> dict:
    """One-time: auth `code` → tokens dict. Used by the setup helper."""
    body = _post_token({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
    })
    return _store_from_response(body, prev={})


def _store_from_response(body: dict, prev: dict) -> dict:
    tok = {
        "access_token": body["access_token"],
        # Spotify only returns a new refresh_token sometimes — keep the old one.
        "refresh_token": body.get("refresh_token") or prev.get("refresh_token", ""),
        "expires_at": time.time() + float(body.get("expires_in", 3600)) - 60,
        "scope": body.get("scope", SCOPES),
    }
    save_tokens(tok)
    return tok


def _access_token() -> str:
    tok = _load_tokens()
    if tok.get("access_token") and time.time() < tok.get("expires_at", 0):
        return tok["access_token"]
    # expired → refresh
    rt = tok.get("refresh_token")
    if not rt:
        raise RuntimeError("no refresh_token stored — re-run spotify_user_auth.py")
    try:
        body = _post_token({"grant_type": "refresh_token", "refresh_token": rt})
    except urllib.error.HTTPError as e:
        raise RuntimeError(
            f"Spotify token refresh failed (HTTP {e.code}) — the grant was likely "
            f"revoked; re-run `python3 setup/spotify_user_auth.py`.")
    return _store_from_response(body, prev=tok)["access_token"]


# --- playlist fetch ----------------------------------------------------------

def _api_get(url: str, token: str, retries: int = 4):
    """Authed GET with the same 503-retry discipline as spotify_resolve."""
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.status == 200:
                    return json.load(resp)
        except urllib.error.HTTPError as e:
            if 400 <= e.code < 500:
                raise RuntimeError(f"Spotify GET HTTP {e.code} (no retry): {url}")
            print(f"  spotify GET HTTP {e.code} (attempt {attempt})", file=sys.stderr)
        except (urllib.error.URLError, OSError) as e:
            print(f"  spotify GET error {e} (attempt {attempt})", file=sys.stderr)
        time.sleep(1)
    raise RuntimeError(f"Spotify GET unavailable after retries: {url}")


def _fetch_playlists() -> list[dict]:
    """Live `GET /me/playlists` (owned + followed), paginated → [{name,id,uri,...}]."""
    token = _access_token()
    out, url = [], "https://api.spotify.com/v1/me/playlists?limit=50"
    while url:
        body = _api_get(url, token)
        for p in body.get("items", []):
            if not p:
                continue
            out.append({
                "name": p.get("name", ""),
                "id": p.get("id", ""),
                "uri": p.get("uri", f"spotify:playlist:{p.get('id','')}"),
                "owner": (p.get("owner") or {}).get("display_name", ""),
                "public": bool(p.get("public")),
                "collaborative": bool(p.get("collaborative")),
            })
        url = body.get("next")
    return out


def my_playlists(force: bool = False) -> list[dict]:
    """The user's playlists, cached to `data/` so a paw-press doesn't hit the API
    every time. Refreshes when the cache is older than CACHE_TTL or `force`."""
    if not force and CACHE.exists():
        try:
            blob = json.loads(CACHE.read_text())
            if time.time() - blob.get("fetched_at", 0) < CACHE_TTL:
                return blob.get("playlists", [])
        except (json.JSONDecodeError, OSError):
            pass  # bad cache → refetch
    playlists = _fetch_playlists()
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(
            {"fetched_at": time.time(), "playlists": playlists}, indent=2))
    except OSError:
        pass  # cache is a nicety, not required
    return playlists


# --- fuzzy match (mirrors audible_resolve so behavior is consistent) ---------

def _norm(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _score(query_n: str, title_n: str) -> float:
    if not query_n or not title_n:
        return 0.0
    q_tokens = set(query_n.split())
    t_tokens = set(title_n.split())
    if q_tokens and q_tokens <= t_tokens:
        coverage = len(q_tokens) / max(1, len(t_tokens))
        return 0.85 + 0.15 * coverage
    ratio = SequenceMatcher(None, query_n, title_n).ratio()
    overlap = len(q_tokens & t_tokens) / max(1, len(q_tokens))
    return max(ratio, 0.6 * overlap)


def resolve_playlist(query: str, force: bool = False) -> dict | None:
    """Fuzzy-match a spoken name against the user's own playlists. Returns
    {kind:'playlist', id, uri, name, artist} (shape matches
    spotify_resolve.resolve_playlist) or None if nothing clears the cutoff."""
    query_n = _norm(query)
    if not query_n:
        return None
    best, best_score = None, 0.0
    for p in my_playlists(force=force):
        sc = _score(query_n, _norm(p["name"]))
        if sc > best_score:
            best, best_score = p, sc
    if not best or best_score < MATCH_CUTOFF:
        return None
    return {"kind": "playlist", "id": best["id"], "uri": best["uri"],
            "name": best["name"], "artist": best.get("owner", "")}


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--refresh"]
    force = "--refresh" in sys.argv
    if not available():
        print("user-OAuth not set up — run: python3 setup/spotify_user_auth.py",
              file=sys.stderr)
        sys.exit(2)
    if not args:
        pls = my_playlists(force=force)
        print(f"{len(pls)} playlist(s):")
        for p in sorted(pls, key=lambda x: x["name"].lower()):
            vis = "public" if p["public"] else ("collab" if p["collaborative"] else "private")
            print(f"  [{vis:7}] {p['name']}  ->  {p['uri']}")
        sys.exit(0)
    match = resolve_playlist(" ".join(args), force=force)
    print(json.dumps(match, ensure_ascii=False, indent=2) if match else "no match")
    sys.exit(0 if match else 1)
