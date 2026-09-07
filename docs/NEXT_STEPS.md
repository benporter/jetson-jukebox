# 🧭 Next steps & open loops

> Snapshot for a fresh session of **what's parked and what's worth doing next**,
> from the user's stated intentions + judgment as of the 2026-06/07 work. Pair
> with `docs/project_plan.md` (longer-range plan) and `docs/LESSONS.md` (gotchas).
> Verify against `git log` before assuming any item is un/done.

## ✅ Built & working this stretch (so you don't re-do it)
Web dashboard (snapshot-backed, disk gauge, Type column) · explicit-lyrics gate
(+ spoken read-back of the retrieved track) · quiet-hours spoken bedtime line ·
albums & playlists (keyword-routed) · **user-OAuth playlist discovery** (find your
own private playlists by name — `setup/spotify_user_auth.py`, read-only, needs the
one-time consent to activate) · audiobooks Path 1 ("continue my book" resume) ·
Stairway Easter egg (local clip) · Piper TTS (voice `en_US-ryan-medium`) · SSH
banner + `rjp`/`rjs`/`cc` aliases · IPv6-disabled Wi-Fi (fixed `.local`).
All pushed to `origin/main`.

---

## 🅰️ Parked — explicitly, waiting on the user

1. **Sonos Cloud Control API (audiobooks Path 2)** — the only way to pick a
   **specific audiobook by name** ("audible warriors book three"); local `FV:2`
   can't see cloud audiobook favorites. User was mid-setup: creating a **Direct
   Control Integration** at developer.sonos.com. **Next action is the user's**:
   hand over Client ID/Secret + a fresh OAuth `code` (or run a local
   `setup/sonos_oauth.py` helper we'd build so secrets skip the chat). Then I build
   `src/sonos_cloud.py` (token refresh, list/play favorites by name). Full guide +
   endpoints already written: **`docs/sonos-cloud-api.md`**. Creds files
   (`config/sonos-cloud*.json`) are already gitignored.
2. **Reliable hostname access** — user **declined the router DHCP-reservation**
   route for now and reaches the box by **IP** (`192.168.1.174`). If `.local`
   stays flaky, revisit: DHCP reservation + `/etc/hosts` alias (`jukebox`). Not
   blocking anything.
3. **Verify audiobook Path 1 actually RESUMES** — we never confirmed whether
   playing the `Audible.com` container resumes the active book vs. lands at an
   Audible menu (useless screenless). Needs one deliberate play-test. If it
   doesn't resume cleanly, Path 2 becomes the real fix.

## 🅱️ Proposed next builds (my recommendation, roughly prioritized)

1. **Per-artist / per-title blocklist** — the natural next guardrail; the schema
   and gate already support it. Extend `blocklist.check()` with a parent-curated
   list (DuckDB `blocklist` table or config), logging `blocked_artist` /
   `blocked_title`; surface + curate it in the dashboard. Reuses the spoken
   read-back. (`docs/blocklist.md`)
2. **Transcript-grounding for artist hallucination** — only trust an artist that
   actually appears in the spoken transcript. Kills the residual "bogus artist
   matches a real-but-wrong track" case that progressive fallback can't. The
   long-standing correctness win for "the wrong song played."
3. **Dashboard as the curation surface** — it's read-only today. Natural growth:
   review blocked/failed requests and *act* (add to blocklist, mark a playlist
   safe, map a private playlist name→URI). Keep the writer discipline in mind
   (single-writer DuckDB; the dashboard would need a tiny guarded write path, not
   the live-DB lock).
4. **TTS confirmations beyond blocks** — spoken "Playing <song>" / room / errors,
   reusing `src/tts.py` + the cache. Cheap now that Piper is in. Watch RAM.
5. **Playlist explicit-scan gap** — playlists fail-open on Spotify 403. If kid
   safety matters, lean on a **parent `JUKEBOX_PLAYLISTS` allowlist** as the
   trusted path, and/or note unscanned playlists in the dashboard.

## 🅲 Nice-to-haves / longer range
- Enclosure polish; request-history analytics; a "favorites shortcut" (say a kid's
  name → their playlist). Voice cloning for a specific voice identity would need
  XTTS (~2 GB, fights the 8 GB budget) — **declined**; staying with Piper.

## 🔁 Standing reminder
After any code/config change the daemon must reload: **`rjp`**. Don't test against
a stale daemon (see `docs/LESSONS.md`).
