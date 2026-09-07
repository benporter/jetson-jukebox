# Albums & playlists

The jukebox plays whole **Spotify albums and playlists**, not just single tracks.
Both ride the **same Sonos endpoint** as songs — the bridge wraps any non-`track`
Spotify URI as a container automatically:

```
GET /{room}/spotify/now/spotify:track:{id}      ← song
GET /{room}/spotify/now/spotify:album:{id}      ← album
GET /{room}/spotify/now/spotify:playlist:{id}   ← playlist
```

(Confirmed working on this Sonos S2 firmware — the `x-rincon-cpcontainer` container
URI plays fine despite the bridge tagging it with a `musicTrack` metadata class.)

## How a child triggers it — keyword, songs stay the default

A **song is the default** (no keyword). Albums and playlists are triggered by the
words **"album"** / **"playlist"** anywhere in the request — deterministic in code,
before the LLM (same approach as the Audible keyword). The keyword + surrounding
articles ("the", "my", …) are stripped; the rest is the search query:

| Said | Routes to | Query |
|---|---|---|
| "play let it go" | song | let it go |
| "play the **frozen** album" | album | frozen |
| "play the **led zeppelin** playlist" | playlist | led zeppelin |
| "play **my bedtime** playlist in the boys room" | playlist (Boys Room) | bedtime |

Why a keyword (not "just like any song"): "play Frozen" is genuinely ambiguous —
the song *Let It Go*, the *Frozen* album, or a *Frozen* playlist. The keyword makes
the intent explicit and predictable for a kid. Room is parsed too ("in the boys
room"); volume defaults to maintain-current.

## API calls (resolve)

Same Spotify search, different `type` (`src/spotify_resolve.py`):

```
GET /v1/search?q={query}&type=album&market=US     → albums[0].uri    (resolve_album)
GET /v1/search?q={query}&type=playlist&market=US  → playlists[0].uri (resolve_playlist)
```

## "My own playlist" / other people's playlists

> **Want your OWN private playlists found by name automatically?** See
> **`docs/spotify-playlists-research.md`** — the deep-dive on why "tell Spotify to
> play on the Sonos device" (Spotify Connect) is a **dead end** for Sonos, and how
> **user-OAuth `/me/playlists`** (read-only) is the real fix. The manual map below
> is today's workaround.

We use **client-credentials** auth (app-level, no user login), so:

- **Public** playlists — Spotify's curated ones (KIDZ BOP, Disney Hits…) **and your
  own if you set them to public** — are found by name. Works with zero setup.
- **Private** playlists can't be found by public search. Three options (best first):
  1. **User-OAuth discovery (recommended):** run `python3 setup/spotify_user_auth.py`
     once (read-only Spotify consent). Then **all** your private/collaborative
     playlists resolve **by name automatically** — no per-playlist config. Resolve
     order becomes **map → your own playlists → public search**; it degrades
     gracefully if not set up. Details: `docs/spotify-playlists-research.md`.
  2. **Make the playlist public** in Spotify → instantly searchable by name.
  3. **Map it** in `config/jukebox.env`:
     `JUKEBOX_PLAYLISTS="bedtime=spotify:playlist:abc,party=spotify:playlist:xyz"`.
     The spoken name → URI map is checked before the user/public lookups.
- (Playing a private playlist URI still works because Sonos plays it under its
  linked Spotify account; we just can't *discover* it by name without the map.)

## Explicit-content gate (important nuance)

The per-song explicit refusal (`docs/blocklist.md`) extends to collections, but
unevenly:

- **Albums: fully gated.** When `JUKEBOX_BLOCK_EXPLICIT=1`, the album's tracks are
  pre-scanned (`/v1/albums/{id}/tracks`); if **any** track is explicit the album is
  refused (`outcome='blocked_explicit'`, `block_reason='explicit:N/M tracks'`) and
  the "not allowed" feedback plays.
- **Playlists: best-effort only.** Spotify **403s** track enumeration of
  user-created playlists under client-credentials, so we usually **can't scan them**
  — the gate **fails open** and the playlist plays unscreened. **Mitigation:** stick
  to trusted/curated playlists, or restrict kids to a parent-mapped
  `JUKEBOX_PLAYLISTS` allowlist for guaranteed-safe ones.

## Logging

Requests log to DuckDB with `intent_type` = `album` / `playlist`
(`result_track_name` = the collection name, `result_artist` = album artist or
playlist owner), so they show in the dashboard's **Type** column alongside songs
and audiobooks.

## Config

```
# JUKEBOX_PLAYLISTS="name=spotify:playlist:ID,..."   # private-playlist name→URI map
JUKEBOX_BLOCK_EXPLICIT="1"                            # gates albums (and playlists where scannable)
```

Changes need a `sudo systemctl restart jukebox-pawkey` (`rjp`).
