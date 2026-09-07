#!/usr/bin/env python3
"""
spotify_user_auth.py — one-time Spotify user consent for playlist discovery.

Run this ONCE to let the jukebox see your OWN (incl. private) playlists by name.
It performs the Spotify Authorization Code flow with READ-ONLY scopes and stores a
refresh token at config/spotify-user-tokens.json (gitignored, chmod 600). After
this, "play my <name> playlist" resolves your private playlists automatically.
See docs/spotify-playlists-research.md.

This box is headless, so we use the copy-the-redirect-URL method (no local browser
or open port required):

  1. One-time dashboard step: add the redirect URI below to your Spotify app at
     https://developer.spotify.com/dashboard  (Edit Settings → Redirect URIs).
     Use the SAME Spotify app whose clientId/secret are in
     tools/node-sonos-http-api/settings.json.
        Redirect URI:  http://127.0.0.1:8090/callback
  2. Run this script. It prints an authorize URL — open it in ANY browser and
     approve. Your browser will redirect to http://127.0.0.1:8090/callback?code=…
     which won't load (nothing is listening — that's fine).
  3. Copy the FULL address from the browser's URL bar and paste it here.

Usage:  python3 setup/spotify_user_auth.py
"""
from __future__ import annotations

import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import spotify_user as su  # noqa: E402


def main() -> int:
    try:
        cid, _ = su.client_creds()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        print("Set up Spotify search first (tools/node-sonos-http-api/settings.json).",
              file=sys.stderr)
        return 2

    authorize = su.AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": cid,
        "response_type": "code",
        "redirect_uri": su.REDIRECT_URI,
        "scope": su.SCOPES,
        "show_dialog": "true",
    })

    print("\n=== Spotify user authorization (one-time) ===\n")
    print("FIRST, add this exact Redirect URI to your Spotify app at")
    print("https://developer.spotify.com/dashboard (Edit Settings → Redirect URIs):")
    print(f"    {su.REDIRECT_URI}\n")
    print("Then open this URL in any browser and click Agree:\n")
    print(f"    {authorize}\n")
    print("Your browser will jump to a 127.0.0.1 address that FAILS to load — that's")
    print("expected. Copy the FULL address from the URL bar and paste it below.\n")

    try:
        pasted = input("Paste the redirect URL (or just the code): ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\naborted.", file=sys.stderr)
        return 1

    code = pasted
    if "code=" in pasted:
        q = urllib.parse.urlparse(pasted).query or pasted.split("?", 1)[-1]
        params = urllib.parse.parse_qs(q)
        if params.get("error"):
            print(f"authorization denied: {params['error'][0]}", file=sys.stderr)
            return 1
        code = (params.get("code") or [""])[0]
    if not code:
        print("no code found in what you pasted.", file=sys.stderr)
        return 1

    try:
        su.exchange_code(code)
    except Exception as e:
        print(f"token exchange failed: {e}", file=sys.stderr)
        print("Common cause: the Redirect URI above isn't registered on the app,",
              file=sys.stderr)
        print("or the code was already used (get a fresh one from the authorize URL).",
              file=sys.stderr)
        return 1

    print(f"\n✅ Authorized. Tokens saved to {su.TOKENS} (chmod 600).")
    try:
        pls = su.my_playlists(force=True)
        print(f"   Found {len(pls)} playlist(s). A few:")
        for p in pls[:8]:
            print(f"     • {p['name']}")
        print("\nTest a lookup:  python3 src/spotify_user.py \"<a playlist name>\"")
    except Exception as e:
        print(f"   (saved, but listing playlists failed: {e})", file=sys.stderr)
    print("\nNo restart needed — resolve_playlist() picks it up on the next request.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
