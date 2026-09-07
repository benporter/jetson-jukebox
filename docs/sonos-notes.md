# Sonos / Spotify integration notes

Findings from getting the first track to play on Sonos via the Jetson.

## TL;DR — the working play path

1. **Resolve the track ourselves** using the Spotify Web API (client-credentials token → `/v1/search`).
2. **Play via the direct-URI endpoint** of `node-sonos-http-api`:
   `GET http://localhost:5005/{Room}/spotify/now/spotify:track:{trackId}`

This works reliably. Use `setup/sonos_play.sh "song name"` as the convenience wrapper.

## Spotify Developer app (for replication)

The Web API search uses **client-credentials** (Client ID + Secret only, no user
login). Create an app at https://developer.spotify.com/dashboard, check **Web API**,
and enter any placeholder **Redirect URI** (e.g. `https://example.org/callback`) —
the form requires one but client-credentials never uses it. Keys go in
`tools/node-sonos-http-api/settings.json` (gitignored; template at
`config/sonos-settings.example.json`). Separately, the Spotify account must be
**linked in the Sonos app** for `/spotify/now/` playback to work (it already was here).

## What does NOT work: `musicsearch`

`GET /{Room}/musicsearch/spotify/song/...` returns a `400`. Root cause:

- `musicsearch` builds the Sonos track URI using a Spotify **account serial number** it scrapes from the player's `http://{player}:1400/status/accounts` endpoint.
- On modern **Sonos S2 firmware** that endpoint returns an empty `<ZPSupportInfo></ZPSupportInfo>`, so the library can't read the account serial. It falls back to a hardcoded `sn=14` hack (see `lib/music_services/spotifyDef.js`), producing a malformed URI that Sonos rejects with 400.
- The Spotify catalog **search itself is fine** — token + `/v1/search` work perfectly in isolation. The failure is purely in the library's Sonos-URI construction.

The `/spotify/now/` endpoint uses a simpler URI form that the firmware accepts, which is why it works.

## Architecture implication (refines Layer 4 of the plan)

The Python `sonos_play` node will **not** use `node-sonos-http-api`'s `musicsearch`. Instead:

```
intent {title, artist}
  → Spotify Web API search (q="track artist", market=<country>, top result)
  → trackId
  → GET /{room}/spotify/now/spotify:track:{trackId}
```

This is also a cleaner fit, since the LLM intent step already yields a structured title+artist to search with.

## Progressive search fallback (artist hallucination)

The 1.5B intent model frequently **invents an artist the child never said**
("Born to Be Wild" → Red Hot Chili Peppers, "Let It Go" → Adele, "It's Your
Birthday" → KidsBop). A `track:TITLE artist:WRONG` query then returns nothing and
the song silently fails to play — this was our top "songs won't play reliably"
complaint. `src/spotify_resolve.py::resolve_song()` fixes the no-match case with a
**progressive fallback**: it tries the precise `track:TITLE artist:ARTIST` first,
then **drops the artist filter** (`track:TITLE`), then looser queries — returning
the first hit. A correct artist is still honored (precise is tried first); a wrong
one no longer blackholes the search. The DB logs the query that actually matched
(`spotify_query`).

⚠️ **Known residual:** if the bogus artist happens to match a *real-but-wrong*
track (e.g. an obscure "Let It Go (Reggae Version)"), the precise query "succeeds"
and the fallback never fires → wrong song. The fuller fix is to **only trust the
artist if it actually appears in the transcript** (transcript-grounding) — not yet
built. See `docs/project_plan.md` next-increments.

## ⚠️ Transient flakiness: Spotify 503 / Sonos 500 — you MUST retry

The Spotify/Sonos backends are intermittently flaky, and it bit us hard (it
looked like a Paw Key / code bug for a while — it wasn't). Both must be retried:

- **Spotify `/v1/search` returns empty `HTTP 503`s** — roughly **1 in 3–4 calls**
  during a bad spell. The token endpoint (`accounts.spotify.com`) stays fine; only
  search (`api.spotify.com`) flaps. The danger: an empty 503 body piped into a JSON
  parser throws `JSONDecodeError: Expecting value: line 1 column 1 (char 0)`.
- **The Sonos `/spotify/now/` play intermittently `500`s** (`Got status 500 when
  invoking /MediaRenderer/AVTransport/Control` in `addURIToQueue`). Also transient.

**Rule: never feed an unchecked HTTP body to a parser.** `setup/sonos_play.sh`
now (a) captures the search HTTP code via `curl -w '%{http_code}'` and retries
until it gets a real `200` with a body, and (b) retries the play until
`"status":"success"`. Both with a short backoff. Expect added latency (several
seconds) during a 503 storm — that's the retries working, not a hang.

If you add new Spotify/Sonos calls (e.g. pause/resume/volume in `src/pipeline.py`),
apply the same retry discipline — they can flap too.

## ⚠️ Sonos state-read race (don't misread it as failure)

Right after a play/pause command, `GET /{room}/state` often reports `STOPPED` or
`TRANSITIONING` with an empty track for a second or two, *even though the command
succeeded*. The action's own `"status":"success"` is the source of truth; the
settled state shows up shortly after. Don't treat a transitional read as a failure.

## Confirmed environment facts

- Sonos rooms (exact names): `Living Room`, `Boys Room`, `Kids Room`.
- Sonos device IPs seen on the LAN: `192.168.1.8`, `192.168.1.132`, `192.168.1.154` (port `1400`).
- Spotify **is** linked as a service on the Sonos system (direct-URI playback succeeds).
- `node-sonos-http-api` runs on port **5005**; Spotify keys live in `tools/node-sonos-http-api/settings.json` (gitignored).
- Working **Favorites** on the system include: `Let It Go - From "Frozen"`, `K-LOVE`, `Audible.com`, `Purple Haze`, plus a few EDM tracks. Favorites play via `GET /{room}/favorite/{name}` and are a good parent-curated fallback.
- Country auto-detect via `ipinfo.io` returns `US`.
