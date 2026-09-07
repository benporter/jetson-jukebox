# ⚠️ Hard-won lessons & gotchas — READ THIS FIRST

> **New/fresh session? Start here, then `CLAUDE.md`.** This is the consolidated
> index of every trap we've hit and paid for. Each entry is a one-liner + a
> pointer to the full detail. If you're about to debug something physical,
> network-y, or "it worked yesterday," scan this first — the answer is very
> likely already below.

Legend: 🔴 = cost us real hours and *will* recur · 🟡 = good to know.

---

## 🛠️ Operating rules that prevent most "ghost" bugs

- 🔴 **Editing `src/` or `config/` does NOTHING until the daemon restarts.**
  `jukebox-pawkey` loads the pipeline + reads config **once at startup**. A live
  paw-press runs whatever was loaded then. After ANY code/config change:
  **`rjp`** (`sudo systemctl restart jukebox-pawkey`). This caused *many* "I fixed
  it but it still does the old thing" episodes. To check if a restart is pending:
  compare `systemctl show jukebox-pawkey -p ActiveEnterTimestamp --value` to the
  file's mtime — daemon start must be *newer*.
- 🔴 **`rjp` needs your sudo password — don't walk away before entering it.** We
  lost a test round when `rjp` was "run" but the password prompt was never
  answered (user walked to the other room), so the old code was still live and the
  new feature "didn't work." Wait for the shell prompt to return. I can verify the
  restart actually took (MainPID changed) from here before you go test.
- 🟡 **Aliases** (in `setup/jukebox_shell.sh`, sourced from `~/.bashrc`): `rjp`
  (restart pawkey), `rjs` (restart sonos), `rjd` (restart dashboard), `cc`
  (`cd /home && claude --continue`). Edit that script, not `~/.bashrc`.
- 🟡 **Commit at every successful increment** (user treats it as a hook — don't
  ask). Secrets never in commits. Commits straight to `main`, then push.

---

## 🔌 Hardware / audio (the mic `(buzzing)` saga)

Mic STT hearing `(buzzing)` / garbled has **FOUR distinct causes** — don't confuse
them. Triage with the **LED** (lit = powered; dark = brownout) and
`setup/mic_check.sh` (crest >8 = healthy speech, ~2.8 = dead/noise). Full detail:
`docs/runbook.md` → "(buzzing) — FOUR root causes".

- 🔴 **A — Pebble coupling:** speaker on the Jetson USB rail injects hum → put the
  speaker on the powered hub.
- 🔴 **B — XVF3800 brownout:** mic on a Jetson port / bus-powered hub → **dark
  LED**, identical stats every capture, crest ~2.8, but `xvf_host` control still
  answers (*control responding ≠ mic working*). Fix = powered hub + full
  power-cycle (unplug ~10 s).
- 🔴 **C — ground loop:** hub on a *different wall outlet* than the Jetson → ~−41 dB
  hum, **LED lit**. Fix = everything on **one power strip** (common ground).
- 🔴 **D — noisy hub port (2026-06):** LED lit, single strip (not B/C), neighbor
  devices innocent — only **moving the mic to a different port on the same hub**
  helped (−41 → −61 dB). Some hub ports inject more switching noise. Our layout:
  **mic→port 1** (clean), port 2 empty (noisy), speaker→3, paw→4.
- 🔴 **Peripheral missing after reassembly = suspect the USB CABLE first**, not
  software. Lit-but-absent-from-`lsusb` = charge-only/defective cable (even
  "data-rated" ones fail). A boot meow only proves the *speaker*, not mic/button.
- 🔴 **Replugging ANYTHING on the hub → `rjp`.** The paw daemon `EVIOCGRAB`s the
  button's input devices at startup; re-plugging re-enumerates USB and invalidates
  those grabs → daemon goes **deaf** (no `🐾 listening…` on press) even though the
  event numbers look unchanged.
- 🟡 **Address ALSA devices by NAME** (`CARD=V3` / `CARD=Array`), never `hw:N` —
  numbers shuffle across reboots/ports.
- 🟡 **UPS / surge protector will NOT fix buzzing.** It's a USB-rail / grounding /
  port problem downstream of mains, not a dirty-mains problem. (Asked & answered.)

WiFi: 🔴 **the dev kit ships with NO antennas at all** (bare u.FL ports) — not
"disconnected." Adding an MHF4 pair took −76/−91 dBm → −34 dBm. Check this FIRST
if WiFi is weak. (`docs/runbook.md`, `docs/hardware.md`)

---

## 🌐 Networking — the `.local` / IPv6 trap

- 🔴 **`.local` hostname hangs from a Mac while the IP works fine = IPv6 mDNS.**
  Root cause: `setup/wifi_autoconnect.sh` rebuilds the `YOUR_SSID` profile with NM's
  default `ipv6.method=auto`, which SLAACs IPv6 ULA (`fd23:…`) addresses; avahi
  then advertises AAAA and macOS **prefers IPv6** → the dashboard (IPv4-only bind)
  and new SSH hang, while an already-open SSH session survives. This is an
  **IPv4-only appliance.** Fix: `sudo nmcli connection modify YOUR_SSID ipv6.method
  disabled` + reboot (the helper now bakes this in). Client-side: flush mDNS
  (`sudo dscacheutil -flushcache; sudo killall -HUP mDNSResponder`).
  Full writeup: `docs/runbook.md` → IPv6 mDNS section.
- 🟡 **Reliable name access is a router DHCP reservation + `/etc/hosts` alias**,
  not mDNS — some APs drop IPv4 multicast across the wired/wireless boundary.
  (User declined the router route for now; reaching the box by **IP** is fine.)
- 🟡 The SSH banner shows the dashboard URL by **both** hostname and IP (the IP
  line works even when `.local` doesn't).

---

## 🔊 Sonos / Spotify

- 🔴 **node-sonos `musicsearch` is broken** on this S2 firmware (empty
  `/status/accounts` → bad URI → 400). We resolve track IDs ourselves and play via
  `/{room}/spotify/now/spotify:track:ID`. (`docs/sonos-notes.md`)
- 🔴 **Spotify search 503s / Sonos play 500s intermittently (~1 in 3–4).** You MUST
  retry both, and NEVER feed an unchecked HTTP body to a JSON parser (empty 503 →
  `JSONDecodeError`). A `/state` read right after a command showing
  `STOPPED`/`TRANSITIONING` is a transient race, not a failure.
- 🔴 **Albums & playlists play through the SAME `/spotify/now/` endpoint** as songs
  — the bridge auto-wraps non-`track` URIs as a container (`x-rincon-cpcontainer`).
  Confirmed working on this S2 firmware. (`docs/collections.md`)
- 🔴 **Client-credentials auth can't see PRIVATE playlists** and **403s on
  enumerating user playlists' tracks** → the album explicit-scan works but the
  **playlist explicit-scan fails open**. Prefer curated playlists or a parent
  `JUKEBOX_PLAYLISTS` name→URI allowlist. (`docs/collections.md`)
- 🔴 **Audiobook favorites don't reach the local `FV:2`.** The new Sonos app saves
  per-book Audible favorites to a CLOUD store the local bridge can't see (verified
  by browsing all 3 speakers' ContentDirectory — only 6 items in `FV:2`). So
  "play a specific book by name" is impossible locally; only the **Sonos Cloud
  Control API** (`docs/sonos-cloud-api.md`) can. Local path = "continue my book"
  plays the `Audible.com` container to resume the active book. (`docs/audible.md`)
- 🔴 **"Tell Spotify to play on the Sonos device" (Spotify Connect transfer-
  playback) does NOT work** — Sonos is a Spotify `is_restricted` device: usually
  absent from `GET /me/player/devices`, and undriveable via the Web API even when
  listed. 5+ yr open issue, no fix; also needs Premium + a playback-control OAuth
  scope. **Don't re-chase it.** The right fix for "find my *own* playlists by name"
  is user-OAuth `/me/playlists` (read-only) feeding the SAME Sonos container
  playback path. Full writeup + re-test criteria: `docs/spotify-playlists-research.md`.
- 🟡 **The 1.5B intent model hallucinates artists** ("Let It Go"→Adele, "Baby
  Shark"→Shark). `spotify_resolve.resolve_song()` uses a **progressive fallback**
  (drops the artist filter on no-match). Residual: a bogus artist that matches a
  real-but-wrong track. Full fix (unbuilt) = transcript-grounding.

---

## 🗣️ Voice / STT / intent routing

- 🔴 **Whole-word matching for keyword/filler stripping — never prefix.** STT often
  hears "**played** the frozen album"; a prefix match let "play" eat the "play"
  inside "played", leaving the stub **"ed the frozen"**, which Spotify resolved to
  a *doom-metal* album. Fixed: match fillers as whole words, and strip the
  "played…" forms. (`pipeline._clean_query`; commit `6299263`)
- 🔴 **Deterministic keyword routing happens BEFORE the LLM** and is the pattern for
  every "special case": Audible ("audible"/"book"/"story", + "continue my book"
  resume phrases), albums/playlists ("album"/"playlist"). Don't trust the small
  model to switch services. Songs are the keyword-free default. Room is parsed
  deterministically too (`_extract_room`, apostrophe-tolerant).
- 🟡 **"book"/"story" keywords can false-trigger** on songs that start with them
  ("**Story** of My Life"). Trim `JUKEBOX_AUDIBLE_KEYWORDS` to be strict.
- 🟡 The system can only catch what **actually resolved** — if STT mishears
  ("Place their way to heaven" → a wrong track), gates/eggs won't fire. This is
  exactly why the **spoken read-back of the retrieved track** exists (below).

---

## 🔒 Guardrails, TTS & the Easter egg

- 🔴 **DuckDB is single-writer.** Daemon opens→inserts→closes per request. To
  inspect `data/jukebox.duckdb` while running, connect **read-only** or you'll
  lock it. The **dashboard reads a Parquet SNAPSHOT, never the live DB** — that's
  the whole reason it can't interfere with playback. (`docs/dashboard.md`,
  `docs/data-logging.md`)
- 🟡 **Quiet hours = deterministic clock gate**, not the LLM
  (`setup/within_play_hours.sh`, 05:00–22:00). It **fails OPEN** on a script error
  — a gate bug must never brick the jukebox.
- 🟡 **Explicit gate:** refuses Spotify-`explicit` tracks (`src/blocklist.py`),
  runs AFTER resolve (so the refused track is logged) and BEFORE the Sonos call.
- 🟡 **TTS (Piper) degrades gracefully:** `src/tts.py` speaks the retrieved
  song+artist on an explicit block, and the quiet-hours bedtime line — but if
  Piper isn't installed it **falls back to the static beep**, so blocking still
  works. `tts.available()` is checked live (no restart to enable once installed).
  Install: `setup/install_piper.sh [voice]`. Voice via `JUKEBOX_PIPER_VOICE`
  (currently `en_US-ryan-medium`). Synth is cached in `data/tts-cache/`.
- 🟡 **Downloading external binaries/models is gated** by the safety classifier — I
  can't run `setup/install_piper.sh` unattended; the user runs it (`! setup/…`) or
  approves the download.
- 🟡 **Easter egg** (Stairway to Heaven → local "No Stairway!" clip on the Pebble,
  not Sonos): copyrighted clip lives at `assets/no_stairway.wav`, **gitignored** —
  never committed. Same pattern for any user-supplied audio.

---

## 🧰 Environment quick-facts

- Jetson Orin Nano Super, **8 GB shared RAM is the hard constraint** (llama-server
  ~1.6 GB; only a few hundred MB truly free). Keep new always-on services tiny.
- No system `node` (nvm) or CUDA on PATH under systemd — services use launcher
  scripts + stripped-env handling.
- `data/` is gitignored (DB, snapshots, tts-cache). `tools/piper/` gitignored.
  Secrets only in gitignored `tools/node-sonos-http-api/settings.json` and
  `config/sonos-cloud*.json`.
- Repo on GitHub (`origin/main`). **Personal identifiers stay out of the tree:**
  real room names and the Wi-Fi SSID live only in the **gitignored**
  `config/jukebox.env` (the committed `config/jukebox.env.example` uses generic
  placeholders like `Kids Room` / `YOUR_WIFI_SSID`); the daemon reads the real env
  at runtime, so scrubbing the tracked files doesn't change behavior. Private LAN
  IPs and the author name (Ben Porter) are intentionally kept; no secrets committed.
