# Playing playlists (esp. your OWN custom ones) — research & decision

> **Deep-dive written 2026-07-15** so it survives sessions. Question from Ben:
> *"I'd like to play playlists — probably my own custom ones. Look into Spotify
> and/or Sonos APIs. We've been pushing a track id to Sonos; maybe there's a way
> to tell Spotify to play on the Sonos device instead. If this path fails and we
> research again in 6–12 months, I want to know what worked and what didn't."*
>
> Pair with `docs/collections.md` (what's built today) and `docs/LESSONS.md`.
> **Verify against the live APIs before assuming any negative below still holds —
> APIs change. The *reasoning* is the durable part.**

---

## TL;DR / decision

- ✅ **Playing a playlist already works today** via the Sonos container endpoint
  `GET /{room}/spotify/now/spotify:playlist:{ID}` — including your **private**
  playlists, because **Sonos plays them under its own linked Spotify account**
  (see "Why playback already works", below). The only gap is *discovery*: we
  can't look your **private** playlists up **by name** today.
- 🎯 **The right fix for "play *my* playlists by name" = user-OAuth discovery, not
  a new playback path.** Switch the *discovery* half from client-credentials to
  the **Authorization Code flow** (one-time consent + stored refresh token), then
  `GET /me/playlists` lists all your own private/collaborative playlists so we can
  auto-build the spoken-name → URI map. **Playback stays exactly as it is.**
  → This is **Path A** below. Recommended.
- ❌ **"Tell Spotify to play on the Sonos device" (Spotify Connect transfer-
  playback) does NOT work for Sonos** and is a dead end for this project. Sonos is
  a Spotify **`is_restricted`** device: it usually isn't even listed by the Web
  API, and when it is, the API can't drive it. It also needs **Spotify Premium** +
  per-user OAuth. → **Path B** below. **Do not re-chase this** without new
  evidence Spotify changed the restriction (5+ years and counting).
- ⚠️ **Sonos Cloud Control API** can't queue an arbitrary Spotify playlist either —
  only `loadFavorite` (things you've saved as Sonos favorites) and `loadCloudQueue`
  (you host your own queue). No better than what we have for playlists.
  → **Path C** below.

**The one insight to remember: _decouple discovery from playback._**
Discovery = "spoken name → Spotify URI" (this is where user-OAuth helps).
Playback = "hand a URI to Sonos" (already solved, account-linked, no Premium).
They are independent; only discovery needs improving.

---

## Why playback already works (and why that's lucky)

Sonos has a **Spotify account linked inside the Sonos app** (Settings → Services).
When we call `GET /{room}/spotify/now/spotify:playlist:{ID}`, the node-sonos-http-api
bridge hands that URI to the Sonos player, and **the Sonos player fetches it from
Spotify using *its own* linked account** — not our API credentials.

Consequences (all verified on this S2 firmware, `docs/collections.md`):
- A **private** playlist URI **plays fine** — Sonos is authenticated as the account
  that owns it. We just can't *find* the URI by name via search.
- **No Spotify Premium is needed on our API side** for playback — Sonos handles the
  entitlement. (Whether the *linked Sonos account* needs Premium is a Sonos/Spotify
  matter, independent of our code.)
- Albums and playlists ride the **same** endpoint as tracks — the bridge auto-wraps
  any non-`track` URI as a container (`x-rincon-cpcontainer`).

So the entire problem reduces to: **how do we turn a spoken playlist name into the
right `spotify:playlist:{ID}` URI?**

---

## The discovery problem, precisely

We currently authenticate to the Spotify Web API with the **client-credentials
flow** (app-level, no user). That token can only *search the public catalog*:

| Playlist kind | Found by name today? | How |
|---|---|---|
| Spotify-curated / public (KIDZ BOP, Disney Hits…) | ✅ yes | public search |
| **Your own, set to Public** | ✅ yes | public search |
| **Your own, Private / Collaborative** | ❌ no | must hand-map in `JUKEBOX_PLAYLISTS` |
| Someone else's private | ❌ no (and shouldn't) | n/a |

The hand-maintained `JUKEBOX_PLAYLISTS="bedtime=spotify:playlist:...,"` map is the
current workaround for private playlists. It works but is manual: every new
playlist means editing config + `rjp`. **Path A removes that chore.**

---

## Path A — user-OAuth discovery of *your own* playlists ✅ RECOMMENDED

**Idea:** authorize the Web API **once** as Ben (not as an anonymous app), keep a
refresh token on disk, and call `GET /me/playlists` to enumerate every playlist
Ben **owns or follows** — including private ones — building the spoken-name → URI
map automatically. Playback is unchanged (still the Sonos container endpoint).

### Why this is the right call
- Solves "play *my* playlists by name" for **private** playlists without making
  them public and without hand-editing config.
- **Read-only** — scopes below grant no playback/modify power, so it's low-risk on
  a kids' box. It reads playlist *names + URIs*, nothing more.
- **No Premium requirement** — reading playlists works on free accounts; and
  playback stays on Sonos's account anyway.
- Reuses the existing Sonos playback path 100%. Small, contained change.

### What it requires (Spotify Web API, current as of 2026-07)
- A **redirect URI** registered on the Spotify app dashboard (e.g.
  `http://127.0.0.1:8090/callback` — a throwaway loopback for the one-time consent).
- **Authorization Code flow** (one interactive browser consent, once):
  scopes **`playlist-read-private`** + **`playlist-read-collaborative`**
  (NOT `user-read-private`, which is profile data; and NOT any `*-modify-*` or
  `user-modify-playback-state` — we never want playback-control scope here).
- Exchange the `code` → `{access_token, refresh_token}`. **Access tokens expire in
  1 hour; the refresh token is long-lived** (but "not indefinitely" — Spotify may
  invalidate it; handle refresh failure by prompting a one-time re-consent).
- Store the refresh token in a **gitignored** creds file, same discipline as the
  Sonos Cloud creds: `config/spotify-user-tokens.json`, `chmod 600`, **never
  committed** (add to `.gitignore` alongside `config/sonos-cloud*.json`).

### Endpoints
```
POST https://accounts.spotify.com/api/token         # code→tokens, and refresh
GET  https://api.spotify.com/v1/me/playlists?limit=50&offset=0   # paginate via .next
     → items[].{name, id, uri, owner.display_name, public, collaborative}
```
Only `/me/playlists` needs the *user* token. **Public search + album/track resolve
keep using the existing client-credentials token** — don't disturb what works.

### ✅ Built (2026-07-15) — how to turn it on
The code is in place; it stays dormant until you authorize once.
- **One-time setup:** register `http://127.0.0.1:8090/callback` as a Redirect URI
  on the Spotify app (developer.spotify.com/dashboard — the same app whose
  clientId/secret are in `tools/node-sonos-http-api/settings.json`), then run
  **`python3 setup/spotify_user_auth.py`** and paste back the redirect URL. It saves
  `config/spotify-user-tokens.json` (gitignored, 0600). Then **`rjp`** so the daemon
  loads the new resolve path.
- **Verify:** `python3 src/spotify_user.py` lists your playlists;
  `python3 src/spotify_user.py "bedtime"` tests a fuzzy lookup.

What got built:
1. `setup/spotify_user_auth.py` — one-shot, **headless-friendly** consent (paste the
   redirect URL; no local browser/open port needed). Writes the tokens file 0600.
2. `src/spotify_user.py` — `available()` (tokens present?), `_access_token()`
   (load + auto-refresh), `my_playlists()` (paginate `/me/playlists`, **cached to
   `data/spotify-playlists-cache.json`**, 6 h TTL), `resolve_playlist()` (fuzzy
   match, reuses the Audible `_score()` subset-match). Read-only scopes only.
3. `spotify_resolve.resolve_playlist()` now checks **`JUKEBOX_PLAYLISTS` map → your
   own playlists (user token) → public search**, and **degrades gracefully** — if
   auth was never run or the lookup errors, it silently falls back to public search.
   The manual map stays as an override/offline path.

### Watch-outs
- **`/me/playlists` returns owned *and followed* playlists**, paginated 50/page —
  page through `.next`. A big library = several calls; cache it.
- Refresh-token rotation: some flows return a **new** refresh token on refresh —
  persist it if present.
- Don't broaden scopes. If a future feature wants Spotify-side playback control
  (it shouldn't — see Path B), that's a separate, deliberate decision.
- Explicit-scan caveat is unchanged: even as the *owner*, enumerating a playlist's
  tracks for the explicit gate may behave differently than album scans; keep the
  fail-open behavior and lean on curated/allowlisted playlists for guaranteed-safe
  (`docs/collections.md`).

---

## Path B — "play on the Sonos device" via Spotify Connect ❌ DEAD END

This is the path Ben wondered about: use the **Spotify Web API Player** to
*transfer playback to the Sonos speaker* and tell Spotify to start the playlist
there (`PUT /me/player` / `PUT /me/player/play` with a `device_id`). **It does not
work with Sonos, and hasn't for 5+ years.** Documented here so we don't re-chase it.

### Why it fails
- **Sonos is a Spotify `is_restricted` device.** Restricted devices can't be
  commanded through the Web API even when visible — the API returns them (if at
  all) with `is_restricted: true`, meaning "you may see it, you may not drive it."
- **Sonos usually isn't even listed** by `GET /me/player/devices`. The Connect Web
  API discovers devices via *local network* association tied to the app session;
  Sonos frequently never appears. Reports of it *sometimes* appearing exist (if you
  first select the Sonos in the **official** Spotify app, it attaches to your
  account "for a while" then drops) — but that's flaky, session-dependent, and
  unusable as a reliable trigger for a kids' appliance.
- **Spotify's own community guidance:** *"Sonos speakers are currently not
  supported to be controlled through the Spotify Web API (restricted device)… use
  the Sonos API to control Sonos devices instead."*
- **A 5+ year open GitHub issue** (`spotify/web-api` #1337, comments 2019→) asks
  Spotify to remove `is_restricted` for Sonos; **no official fix**. Users note the
  official app can drive Sonos, so it's a *policy/restriction* choice, not a
  technical impossibility — but it's Spotify's to change, not ours.

### Extra costs even if it worked
- **Requires Spotify Premium** (all Player transfer/play commands are Premium-only).
- **Requires per-user OAuth** with **`user-modify-playback-state`** — a
  playback-control scope we'd rather **not** put on a kids' box.
- Adds a second, fragile control plane competing with the Sonos bridge we already
  trust.

### Re-test criteria (for the 6–12-month revisit)
Only worth revisiting if **all** of these flip:
1. `GET /me/player/devices` (with a Premium user token) **lists the Sonos** with
   **`is_restricted: false`**, **and**
2. `PUT /me/player` transfer to that `device_id` actually starts audio on the
   speaker, **and**
3. it survives the speaker going idle / re-grouping.
If #1 still shows the Sonos absent or `is_restricted: true`, **stop — nothing
changed.** Quick check: get a Premium user token with `user-read-playback-state`,
`curl` `/v1/me/player/devices`, look for a Sonos entry and its `is_restricted`.

---

## Path C — Sonos Cloud Control API ⚠️ limited (same conclusion as audiobooks)

The Sonos **Control API** (cloud, `developer.sonos.com/reference/control-api/`) can
group players and start audio, but for *content* it's constrained:
- **`loadFavorite`** — plays something you've saved as a **Sonos favorite**. Could
  work if every desired playlist is saved as a Sonos favorite first (manual), and
  it shares the audiobook-favorites caveat: the new Sonos app may store favorites
  in a **cloud** area the local `FV:2` can't see (`docs/audible.md`,
  `docs/sonos-cloud-api.md`).
- **`loadCloudQueue`** — you host your **own** cloud-queue endpoint that serves
  track metadata; heavy to build, and still not "hand Spotify a playlist URI."
- **You cannot queue an arbitrary Spotify playlist by URI** through the Control API.

Net: for **playlists**, the Control API is **no better** than the local container
endpoint we already use — and more work. (It remains the only path for
**per-audiobook selection by name** — that's a *different* problem, tracked in
`docs/sonos-cloud-api.md` / NEXT_STEPS Path 2.)

---

## Comparison at a glance

| Approach | Finds my PRIVATE playlists by name? | Premium? | Playback-control scope on the box? | Effort | Verdict |
|---|---|---|---|---|---|
| **Today:** client-creds search + `JUKEBOX_PLAYLISTS` map | Only via manual map | No | No | none (built) | works, manual |
| **A: user-OAuth `/me/playlists`** | ✅ automatically | No | **No** (read-only) | small | ✅ **do this** |
| **B: Spotify Connect → Sonos** | (n/a) | **Yes** | **Yes** (unwanted) | high + fragile | ❌ dead end |
| **C: Sonos Cloud `loadFavorite`** | Only if pre-saved as favorite | No* | No | med | ⚠️ no gain |

\* Sonos-side account entitlement aside.

---

## Recommendation

1. **Keep the current playback path** (`/spotify/now/spotify:playlist:{ID}`) — it's
   correct and already handles private playlists.
2. **When we want hands-free discovery of Ben's own playlists → build Path A**
   (user-OAuth `/me/playlists`, read-only scopes, refresh token in a gitignored
   creds file, auto name→URI map with the manual map kept as override).
3. **Do not build Path B.** Record it as tried-and-rejected; re-test only against
   the three flip conditions above.
4. Leave **Path C** to the audiobook problem, where it's the *only* option.

Until Path A is built, the **manual `JUKEBOX_PLAYLISTS` map** (or setting a
playlist to Public) remains the way to reach a private playlist by name.

---

## Sources (fetched 2026-07-15)

- Spotify Web API — [Transfer Playback](https://developer.spotify.com/documentation/web-api/reference/transfer-a-users-playback) (scope `user-modify-playback-state`, Premium-only)
- Spotify Web API — [Authorization Code Flow](https://developer.spotify.com/documentation/web-api/tutorials/code-flow) · [Refreshing tokens](https://developer.spotify.com/documentation/web-api/tutorials/refreshing-tokens) · [Authorization scopes](https://developer.spotify.com/documentation/web-api/concepts/authorization)
- Spotify Community — [Sonos speakers not showing in GET /player/devices](https://community.spotify.com/t5/Spotify-for-Developers/Sonos-speakers-not-showing-in-GET-player-devices/td-p/5175462) (restricted device; use the Sonos API)
- GitHub `spotify/web-api` — [#1337 Sonos devices in API devices list](https://github.com/spotify/web-api/issues/1337) (5+ yr open, `is_restricted`, no official fix)
- Sonos Developer — [Control API reference](https://developer.sonos.com/reference/control-api/) · [loadFavorite](https://developer.sonos.com/reference/control-api/favorites/loadfavorite/) · [Play audio (Cloud queue)](https://docs.sonos.com/docs/cloud-queue-play-audio)
