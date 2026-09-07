# CLAUDE.md — orientation for any Claude session working in this repo

> Auto-loaded by Claude Code. If you're a fresh session (e.g. after a reboot),
> read this first, then `docs/project_plan.md`. For ground truth on "what's
> been done," run `git log --oneline`. For "is it broken / how do I fix boot,"
> see `docs/runbook.md`.
>
> **🚨 BEFORE DEBUGGING ANYTHING, READ [`docs/LESSONS.md`](docs/LESSONS.md)** —
> the consolidated index of every hard-won gotcha (mic buzzing's 4 causes, the
> IPv6/`.local` trap, `rjp`-after-any-change, Sonos/Spotify retries, keyword
> routing, etc.). It will save you hours. **What's next / parked:**
> [`docs/NEXT_STEPS.md`](docs/NEXT_STEPS.md).

## What this is

A **screenless voice jukebox for kids** on an NVIDIA Jetson Orin Nano Super.
Kid presses a button (Keychron "Big Kitty" Paw Key) → speaks → the song plays
on the Sonos speakers via Spotify, with a spoken/meow confirmation. Everything
runs locally except the Spotify catalog + Sonos speakers on the LAN.

Hardware: `docs/hardware.md`. How devices appear to the OS + I/O gotchas:
`docs/peripherals.md`. Build plan + phases: `docs/project_plan.md`.

## Architecture (local-first, lean — 8GB shared RAM is the hard constraint)

```
Paw Key (3434:0400)        ── push-to-talk: src/pawkey_listen.py (reads /dev/input), record while held
  → record mic (ReSpeaker XVF3800, ALSA card "Array", 16kHz mono)
  → whisper.cpp (CUDA)     ── STT, CLI, tools/whisper.cpp, model ggml-base.en
  → llama.cpp server :8080 ── intent → JSON {type,title,artist,room,volume,direction}
                              Qwen2.5-1.5B Q4_K_M, src/intent.py
  → quiet-hours gate       ── setup/within_play_hours.sh: songs play 05:00–22:00, else blocked_time
  → Spotify Web API search ── src/spotify_resolve.py → track id (+ explicit flag)
  → content gate           ── src/blocklist.py: refuse explicit (+ future artist/title) → blocked_explicit
  → node-sonos-http-api :5005 ── play via /{room}/spotify/now/spotify:track:ID
  → log the request        ── DuckDB data/jukebox.duckdb (src/db.py); song requests only
  → Pebble V3 speaker       ── meow + spoken feedback (Piper TTS, src/tts.py); e.g. reads back the blocked song+artist

  (side, read-only) Request dashboard ── src/dashboard/ (FastAPI :8088), reads a
     Parquet SNAPSHOT of the DB (not the live file) → never locks playback.
```

Decisions (and why) live in `docs/initial_plan.md`: **plain Python, not LangGraph**;
**llama.cpp directly, not Ollama**; **resolve track ids ourselves + direct-URI play,
not node-sonos `musicsearch`** (see gotchas).

## Run / operate

- Persistent services are systemd units under `jukebox.target` (see `services/README.md`).
  Install/refresh: `setup/install_services.sh`. Health: `setup/jukebox_healthcheck.sh --status`.
- One-shot voice test: `src/listen_and_play.py --seconds 6` (records, transcribes, plays).
- Play a song by name (CLI): `setup/sonos_play.sh "thunderstruck acdc"`.
- Config (default room, valid rooms, default volume behavior, quiet hours, audio
  device, ports): `config/jukebox.env`. Secrets (Spotify keys) live ONLY in
  `tools/node-sonos-http-api/settings.json` (gitignored).
- Request log + quiet-hours gate: `docs/data-logging.md`. Inspect the DB
  read-only (see that doc) — don't open it read-write while the daemon runs.
- **Audiobooks (Audible):** `docs/audible.md`. Keyword-routed special case
  ("audible <book>" / "continue my book"); everything else stays Spotify.
- **Albums & playlists:** `docs/collections.md`. "album"/"playlist" keywords →
  whole Spotify collection via the same `/spotify/now/` endpoint (container URI);
  songs are the default. Albums explicit-pre-scanned; playlist scan best-effort (403s).
- **Easter egg:** Stairway to Heaven (Led Zeppelin) plays a LOCAL Pebble clip, not
  the song on Sonos (`pipeline._is_stairway`, after the search step; logged
  `blocked_easteregg`/`Easter egg`). Clip `assets/no_stairway.wav` is user-supplied
  + **gitignored** (real audio is copyrighted — a placeholder honk ships locally).
- **Request dashboard:** `docs/dashboard.md`. LAN web UI at
  `http://jetson-orin-nano.local:8088` (mDNS name, survives DHCP changes;
  clickable in the SSH login banner). Reads a Parquet snapshot, never the live
  DB. `jukebox-dashboard.service`.
- Python deps (`duckdb`): `requirements.txt`, installed `--user` by
  `setup/install_build_deps.sh`.

## ⚠️ Gotchas (hard-won — don't relearn these)

- **node-sonos `musicsearch` is broken** on this Sonos S2 firmware (empty
  `/status/accounts` → bad URI → 400). Use Spotify search → track id →
  `/spotify/now/spotify:track:ID`. (`docs/sonos-notes.md`)
- **Spotify search `limit=1` ranks differently** (worse) than `limit>=3`.
  `sonos_play.sh` requests 5 and takes the top. Don't drop it back to 1.
- **Spotify search 503s / Sonos play 500s intermittently** (~1 in 3-4 in a bad
  spell) — you MUST retry both (`sonos_play.sh` does). Never pipe an unchecked HTTP
  body into a JSON parser. Also: a Sonos `/state` read right after a command shows
  a transient `STOPPED`/`TRANSITIONING` — not a failure. See `docs/sonos-notes.md`.
- **node** is installed via nvm (no system node) → services resolve it from
  `~/.nvm/versions/node/*/bin` (see `setup/sonos_server.sh`).
- **CUDA** isn't on PATH by default; `/etc/profile.d/cuda.sh` adds it. Build
  flags for the Orin GPU: `-DGGML_CUDA=1 -DCMAKE_CUDA_ARCHITECTURES=87` (sm_87).
- **External clones** (`tools/whisper.cpp`, `tools/llama.cpp`,
  `tools/node-sonos-http-api`, `tools/reSpeaker_*`) and `models/` are gitignored;
  recreate via `setup/README.md`.
- **Audio out** = Pebble V3 = `plughw:CARD=V3,DEV=0` (set in `config/jukebox.env`).
  Address ALSA devices **by name** (`CARD=V3`/`CARD=Array`), never `hw:N` — numbers
  shuffle across reboots/hub. PulseAudio grabs USB audio (exclusive `plughw` →
  "Device or resource busy") — retry past it. See `docs/peripherals.md`.
- **Paw Key** sends a normal **Enter** keycode and enumerates as 4 input devices;
  the daemon `EVIOCGRAB`s it (so Enter doesn't leak to the terminal) and needs
  `input` group access (`SupplementaryGroups=input` in the service; `sudo` for
  manual runs). Hold-to-talk. See `docs/peripherals.md`.
- **systemd services run in a stripped env** (no nvm/CUDA on PATH) and **block-
  buffer Python stdout** — use the launcher scripts + `PYTHONUNBUFFERED=1`, and
  reproduce with `env -i PATH=… HOME=…`. See `services/README.md`.
- **DuckDB is single-writer.** The daemon opens→inserts→closes per request; to
  inspect `data/jukebox.duckdb` while running, connect **read-only** or you'll get
  a lock error. Logging is best-effort and never blocks playback. (`docs/data-logging.md`)
- **The dashboard reads a SNAPSHOT, not the live DB** — by design, so it can't
  lock playback. `src/dashboard/snapshot.py` exports `requests` → Parquet
  (read-only, every ~60 s); all queries hit the Parquet. So the dashboard view is
  up to a minute stale (header shows snapshot age) and new code/config needs
  `sudo systemctl restart jukebox-dashboard`. (`docs/dashboard.md`)
- **Quiet hours are a deterministic clock gate**, not the LLM: `setup/within_play_hours.sh`
  (songs play 05:00–22:00, `JUKEBOX_PLAY_START/END`). It **fails open** on a script
  error. Editing the window or pipeline logic needs a `jukebox-pawkey` restart.
- **Content gate refuses explicit tracks** (`src/blocklist.py`, `docs/blocklist.md`):
  runs in `_play_song` AFTER resolve (so the refused track is logged) and BEFORE
  the Sonos call → `outcome='blocked_explicit'`, no playback. `JUKEBOX_BLOCK_EXPLICIT`
  (default on). The "tell the kid it's blocked" sound is a **hook only**
  (`_play_blocked_feedback` / `JUKEBOX_BLOCKED_SOUND`) — silent until a clip is
  recorded (TTS later). Per-artist/title blocklists plug into the same `check()`.
- **Peripheral missing after reassembly** = suspect the **USB cable** first, not
  software. A device that's **lit/powered but absent from `lsusb`** has no data
  link (charge-only or defective cable — even "data-rated" ones fail). A meow on
  boot only proves the *speaker*, not the mic/button. Reboots won't fix a bad
  cable. See `docs/runbook.md` "peripheral disappears after reassembly".
- **Mic `(buzzing)` has FOUR causes** (`docs/runbook.md` "(buzzing) — FOUR root
  causes"). Triage with the **LED** (lit = powered → coupling/loop/port; dark =
  brownout) and `setup/mic_check.sh` (crest >8 = healthy speech, ~2.8 = dead):
  - **A** coupling from the Pebble on the Jetson rail → put the speaker on the hub.
  - **B** XVF3800 **brownout** (mic on a Jetson port / bus-powered hub): dark LED,
    DSP starves while `xvf_host` control still answers (control responding ≠ mic
    working). Fix = powered hub + full power-cycle.
  - **C** **ground loop** after a room move: hub on a *different outlet* than the
    Jetson → ‑41 dB hum, LED lit. Fix = **everything on one power strip** (common
    ground). See the relocation checklist in `docs/runbook.md`.
  - **D** **noisy hub port**: LED lit, single strip (not B/C), neighbor devices
    innocent — only **moving the mic to a different port on the same hub** helps
    (‑41 → ‑61 dB). Some ports inject more switching noise. mic→port1, not port2.
- **Relocating the unit** triggers ground loop (C above), WiFi reconnect, and Sonos
  re-discovery at once — follow the **relocation checklist** in `docs/runbook.md`.
- **Audiobook favorites don't reach local `FV:2`.** The new Sonos app saves
  per-book Audible favorites to a CLOUD store; the local bridge (and any local API)
  only sees `FV:2` (verified by browsing all 3 speakers' ContentDirectory). So
  "play a specific book by name" can't be done locally — only via the Sonos Cloud
  Control API (`docs/sonos-cloud-api.md`). The local path is "continue my book" →
  play the `Audible.com` container favorite to resume the active book. (`docs/audible.md`)

## STARTUP CONTRACT (do not let this slip)

Any new persistent server/tool MUST be wired into boot, or it won't survive a
reboot. Three steps, every time (full checklist in `services/README.md`):
1. Add `services/jukebox-<name>.service` (`PartOf=`/`WantedBy=jukebox.target`).
2. Add a health line to `setup/jukebox_healthcheck.sh` (the component registry).
3. Re-run `setup/install_services.sh`.

## Conventions

- **Commit at every successful increment** (the user treats it as an informal
  hook — don't ask first). Keep secrets out of commits.
- Branch off `main` only if asked; this repo currently commits straight to `main`.
- **⚠️ Editing `src/` or `config/` does NOT affect the running system until the
  daemon restarts.** `jukebox-pawkey` imports the pipeline once at startup, so a
  live paw-press runs whatever code was loaded at the last boot/restart. After any
  code/config change, tell the user to `sudo systemctl restart jukebox-pawkey`
  (you can't sudo non-interactively). This repeatedly caused "I fixed it but it
  still does the old thing" — stale live tests against old code.
- **git remote:** `origin` → `https://github.com/benporter/jetson-jukebox.git`,
  branch `main` (GitHub auth is configured on the box; `git push` works). No
  secrets in commits (Spotify keys stay in gitignored `settings.json`). **Personal
  identifiers are kept out of the tree:** real room names + Wi-Fi SSID live only in
  the gitignored `config/jukebox.env`; committed code/docs use generic placeholders
  (`Kids Room`, `YOUR_WIFI_SSID`). Private LAN IPs and the author name are kept.
- **Shell niceties** (live in `setup/jukebox_shell.sh`, sourced from `~/.bashrc`):
  aliases `rjp` (restart jukebox-pawkey), `rjs` (restart jukebox-sonos), `rjd`
  (restart jukebox-dashboard), and `cc` (`cd /home && claude --continue`), plus the
  SSH login banner with the clickable dashboard URL. Edit the script, not `~/.bashrc`.

## Status snapshot (2026-06-13 — verify with `git log`)

Working & committed: STT (whisper.cpp CUDA), LLM intent, Sonos play/pause/resume/
volume (`src/pipeline.py`), voice-specified room + volume (maintains current
volume by default), progressive Spotify search fallback (drops a hallucinated
artist on no-match — `spotify_resolve.resolve_song`), Paw Key push-to-talk daemon,
boot stack (`jukebox.target`) + readiness meow, Pebble audio (mic on the powered
hub), WiFi fixed (antennas), DuckDB request logging (`src/db.py`), deterministic
quiet-hours gate (05:00–22:00), **explicit-lyrics content gate**
(`src/blocklist.py` → `blocked_explicit`), **request dashboard** (`src/dashboard/`,
`jukebox-dashboard.service`, snapshot-backed, LAN :8088, shows the explicit flag).
Assembled in a LEGO case; runs in a relocatable spot (one power strip — see
ground-loop note). Pushed to public GitHub (`origin/main`).
Also: **audiobooks (Audible)** keyword-routed — "continue my book" resumes the
active book locally (Path 1, built); "audible <book>" awaits the Sonos Cloud API
for per-book selection (Path 2 — see `docs/sonos-cloud-api.md`).
**Albums & playlists** built (`docs/collections.md`): "album"/"playlist" keywords
→ whole Spotify collection (same `/spotify/now/` container endpoint), public
playlists by name + a private name→URI map (`JUKEBOX_PLAYLISTS`).
Not yet built / next: **Sonos Cloud API** for audiobook name-selection (Path 2),
**spoken blocked-feedback** is built — explicit blocks read back the retrieved
song+artist via Piper TTS (`src/tts.py`; run `setup/install_piper.sh` to fetch the
binary+voice; falls back to `assets/blocked.wav` beep until then); next is
a spoken clip, **per-artist/title blocklist** (slots into `blocklist.check()`),
**transcript-grounding** for artist, TTS confirmations, enclosure polish.
