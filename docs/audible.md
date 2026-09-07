# Audiobooks (Audible)

Audible is the **special case** in the pipeline — Spotify handles everything else.
A spoken keyword routes a request to the audiobook path; there is no fallback to
Spotify for it and no Spotify call.

## How requests route (deterministic, before the LLM)

In `pipeline.act_on_transcript`, before the LLM runs:

1. **Resume** — if the transcript contains a resume phrase ("**continue my book**",
   "keep reading", "play my book", … — `JUKEBOX_AUDIBLE_RESUME_PHRASES`) →
   `_resume_audiobook` (Path 1 below).
2. **Specific book** — else if the cleaned text starts with a keyword
   ("**audible**", "audiobook", "book", "story" — `JUKEBOX_AUDIBLE_KEYWORDS`) →
   `_play_audiobook` with the remaining words as the title (+ optional chapter).
3. Otherwise → the normal Spotify song path, untouched.

⚠️ "book"/"story" are kid-natural but can false-trigger on songs that start with
them ("**Story** of My Life"). Trim `JUKEBOX_AUDIBLE_KEYWORDS` to just
`audible,audiobook` to be strict.

## The hard constraint we discovered

There's no public Audible catalog search API, and `musicsearch` is broken on this
S2 firmware. The only reliable local play path is a **Sonos favorite by exact
title** (`/{room}/favorite/<title>`, case-insensitive exact match).

**But** — verified by browsing all three speakers' `ContentDirectory` directly —
the **current Sonos app stores per-book audiobook favorites in a cloud store that
does NOT sync to the local `FV:2` favorites container.** So individual book
favorites are **invisible to the Jetson**; favoriting more books doesn't help
locally. The only Audible item in `FV:2` is the **`Audible.com`** service
container.

## ✅ Re-verified 2026-07-18 (assumptions challenged against the live box)

Re-checked everything above directly, and pinned the *mechanism* the earlier notes
only guessed at:

- **FV:2 still has no per-book favorites.** Current `FV:2` = `Audible.com`,
  `CH 52 - BPM`, `K-LOVE`, `Let It Go`, `Purple Haze`, `Watermät - Bullit`. The
  Warriors books favorited in the app never appeared. **Confirmed.**
- **Root cause pinned:** `GET http://<speaker>:1400/status/accounts` returns an
  **empty** `<ZPSupportInfo></ZPSupportInfo>`. With no local service-account list,
  local **SMAPI browse/search is unavailable**, which is why a UPnP
  `ContentDirectory#Browse` of the Audible container returns **UPnP error 701 (no
  such object)**. So you **cannot enumerate or pick a specific book _locally_** on
  this firmware — not a code bug, a firmware/account-sync behavior. **Confirmed.**
- **Correction — the play service id is `sid=239`, not `61191`.** `61191` is only
  the *marketplace container* favorite (`Audible.com`). Actual audiobook audio
  streams over the Audible HLS service **`sid=239`**.
- **NEW — chapters are first-class, directly-addressable URIs.** Dissecting a book
  playing live (Wings of Fire, ASIN `B01BFPVOV2`), each chapter is:
  ```
  x-sonosapi-hls-static:refchapter:<ASIN>_270137_<market>_<startMs>_<endMs>?sid=239&flags=24616&sn=<acct>
  # Ch.3 = ...B01BFPVOV2_270137_com_1056000_1847000...   (ms 1,056,000 → 1,847,000)
  # Ch.4 = ...B01BFPVOV2_270137_com_1847000_2851000...   (chains: prev end = next start)
  ```
  `startMs_endMs` are cumulative offsets from book start; `sn` = the Sonos-side
  Audible account serial (constant per household); `270137` = an
  unidentified constant (see Path C caveat). **Chapter navigation works:** with the
  book active, `nextTrack` was Chapter 4, so `/{room}/next` and `/previous` step
  between chapters (see Chapters, below).

That split is why there are two paths:

## Path 1 — "continue my book" (resume) — 🔴 BUILT BUT DOES NOT WORK (2026-07-18)

Intended to play the `Audible.com` container favorite (`JUKEBOX_AUDIBLE_CONTAINER`)
to make Audible **resume the active book**. Code calls
`_sonos(room, "favorite/Audible.com")` (`pipeline._resume_audiobook`, ~line 344).

**Re-test result: the container will not play by any local automation method.**
- The bridge favorite endpoint **500s** — jishi's `replaceWithFavorite` tries to
  `addURIToQueue` the container (empty `uri`) and Sonos rejects the enqueue.
- A direct UPnP `SetAVTransportURI` with `x-rincon-cpcontainer:10fe3064refmarketplace%3Acom`
  **500s with UPnP errorCode 714** (unresolvable resource) — the container needs a
  SMAPI service session/token to resolve, and `/status/accounts` is empty (dead
  locally). The Sonos app can play it because it holds that session; we can't.

So the Wings of Fire book seen in Boys Room was started **from the Sonos/Audible
app**, not by our code. **Path 1 needs a real fix or replacement** — likely the
Sonos Cloud Control API (`loadFavorite` on a favorited book) even for "resume,"
since the local container-resume path is not automatable on this firmware.
- Trigger (unchanged): any phrase in `JUKEBOX_AUDIBLE_RESUME_PHRASES`.

## Path 2 — specific book by name — Sonos Cloud Control API (planned)

"audible <book>" currently resolves against `FV:2` audiobook favorites
(`src/audible_resolve.py`), which is empty of real books — so it `no_match`s until
the **Sonos Cloud Control API** is wired in. **Honest scope (re-verified):** the
Cloud API can play a book **only if it's been saved as a Sonos favorite**
(`/households/{id}/favorites` → `loadFavorite`); it **cannot browse the Audible
library**, and it gives **no true chapter selection** — only `skipToNextTrack`
through chapters. So Path 2 = "pick one of a **parent-curated, favorited** set of
books by name," not "any book in the library." Full setup + build plan:
**`docs/sonos-cloud-api.md`**.

## Chapters (verified mechanism)

Chapters are real tracks on the active book (not in the Sonos queue — that's a
separate music queue). With a book playing:
- "audible **next/previous chapter**" → `/{room}/next` / `/previous` (**works** —
  verified: `nextTrack` was the next chapter).
- "audible <book> **chapter N**" → start the book, then `next` ×(N−1).
- **Untested (candidates for direct jump):** `/{room}/trackseek/{N}` may jump
  straight to chapter N if the service exposes chapters as a numbered track list
  (currentTrack showed `trackNo: 3`); and a chapter's `refchapter:` URI can in
  principle be played directly via `setavtransporturi` (see Path C). Both need one
  live play-test to confirm.
Sonos also auto-resumes a book's saved position, so "chapter N" fights the resume
point unless we seek explicitly.

## Path C — arbitrary book **and** chapter via the Audible API (experimental)

The one path that could deliver the *ideal* ("pick the book **and** the chapter"
for any book in the library, no favoriting): combine Audible's own account API with
the `refchapter:` URI scheme above.
- **Audible private API** (e.g. the `mkb79/audible` Python lib): `GET /1.0/library`
  → every owned book's **ASIN + title**; `GET /1.0/content/{asin}/metadata?
  response_groups=chapter_info` → per-chapter **`start_offset_ms` / `length_ms`**,
  which map exactly onto the URI's `startMs_endMs`.
- Construct `x-sonosapi-hls-static:refchapter:<ASIN>_270137_com_<start>_<end>?sid=239&flags=24616&sn=<acct>`
  and play via the local bridge (`setavtransporturi`) — **no Cloud API, no
  favoriting, full library + any chapter.**
### ❌ Path C is DEAD — decisive test run 2026-07-18

Harvested a **second** book's live `refchapter:` URI and compared the constant:

| Book | ASIN | middle field |
|---|---|---|
| Wings of Fire (Sutherland) | `B01BFPVOV2` | **270137** |
| Warriors (Erin Hunter) | `0062977911` | **13099271** |

**Different → it's a per-book Sonos content key, not a constant.** `sid=239`,
`flags=24616`, `sn=10`, market `com` are all constant across books; only the ASIN
**and** this key change. That key is assigned by Sonos internally when it resolves
the book over SMAPI — **not derivable from Audible's API** — so we cannot construct
a playable chapter URI for an arbitrary book. Synthesizing `refchapter:` URLs is
therefore impossible from data we can obtain locally. Path C is closed; don't
re-attempt without evidence Sonos exposes that key (it won't while
`/status/accounts` is empty).

(Also — even the ASIN format differs: `B01…` vs an ISBN-style `0062977911`, both
valid Audible ASINs. The blocker is the middle key, not the ASIN.)

## Logging

Audiobook requests log to the same DuckDB table as songs with
`intent_type='audiobook'` (resume rows use `intent_title='(resume)'`,
`result_track_name='Audible.com'`), so they appear in the dashboard.

## Config (`config/jukebox.env`)

```
JUKEBOX_AUDIBLE_KEYWORDS="audible,audiobook,book,story"
# JUKEBOX_AUDIBLE_FAVORITES=""        # restrict matching to exact titles
JUKEBOX_AUDIBLE_CONTAINER="Audible.com"
JUKEBOX_AUDIBLE_RESUME_PHRASES="continue my book,keep reading,play my book,..."
```

Changes need a `sudo systemctl restart jukebox-pawkey` (`rjp`).
