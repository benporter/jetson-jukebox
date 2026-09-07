# Project Plan — Jetson Voice Jukebox for Kids

## Goal

A screenless voice jukebox the kids operate by themselves:

> Kid presses the Paw Key → speaks a song request → the song starts playing on the Sonos speakers (via Spotify) within ~1 minute, with a short spoken confirmation.

No phones, no screens, no Telegram. Everything runs locally on the Jetson except the Spotify catalog lookup and the Sonos speakers on the LAN.

## Architecture (decided)

One Python application orchestrating four local HTTP/library services. **Plain Python, graph-structured** — explicit state + node functions + a router — *not* LangGraph/LangChain (overkill and too heavy for 8GB shared memory) and *not* Ollama (wrapper overhead + documented Jetson bugs; we use llama.cpp directly).

| Layer | Tool | Role |
|---|---|---|
| Push-to-talk | `evdev` (Python) | Detect Paw Key keypress, start/stop recording |
| STT | whisper.cpp + CUDA (persistent `whisper-server`) | Transcribe audio |
| Intent parsing | llama.cpp (`llama-server`) + Qwen2.5 1.5B Q4_K_M | Transcript → structured JSON intent |
| Sonos + Spotify | `node-sonos-http-api` | `musicsearch` GET → play on Sonos |
| TTS feedback | Piper (fast) or Kokoro (better voice) | Spoken confirmation to Pebble V3 |
| Logging/history | DuckDB (`data/jukebox.duckdb`) | Local request log for later analysis — see `docs/data-logging.md` |

**v1 intent:** song requests only. **v2 roadmap:** intent router (song / volume / pause-resume), parent content blocklist, full SQLite request history. The plain-Python node pattern maps 1:1 to LangGraph nodes, so a later migration stays cheap if multi-turn/agent-loop features ever justify it.

End-to-end latency target: under 1 minute; realistically ~8–15s.

---

## Task ownership

Tasks are split into two columns:

- **🧑 YOU (Ben)** — anything requiring a human: creating accounts, physical hardware, purchasing/credentials, OS flashing, system-level installs that need your sudo/interactive input, and **decisions** I shouldn't make for you.
- **🤖 ME (Claude)** — boilerplate: scaffolding, application code, config templates, schemas, service files, glue scripts, docs.

I will **not start executing any of this yet** — this document is the plan for your review.

---

## Phase 0 — Hardware & OS bring-up  🧑 YOU

These are physical/interactive and must happen before any code runs.

- [x] Install the Samsung 990 PRO into the 2280 M.2 slot. (microSD never seated — the system runs entirely from NVMe.)
- [x] Flash **JetPack 6.2** — done; OS runs entirely from the NVMe (the microSD was not used). Ref: https://developer.nvidia.com/embedded/learn/get-started-jetson-orin-nano-devkit
- [x] CUDA toolchain confirmed — `nvcc` 12.6 (installed via `setup/install_build_deps.sh`; not present in the base image).
- [x] Peripherals verified: ReSpeaker mic (card "Array"), Pebble V3 (card "V3"), Keychron Paw Key (`3434:0400`, `/dev/input/event3-6`).
- [x] On the same LAN as Sonos; rooms discovered: **Living Room**, **Boys Room**, **Kids Room**.

## Phase 1 — Accounts & credentials  🧑 YOU

- [x] **Spotify Developer app** created — Client ID/Secret obtained and configured (Web API).
- [x] Spotify is linked to Sonos and arbitrary tracks play via the API (confirms a working/Premium-linked account).
- [x] Creds delivered via the scaffolded template → live keys in `tools/node-sonos-http-api/settings.json` (gitignored).

## Phase 2 — Software downloads & system installs  🧑 YOU (with my scripts)

System-level packages and large model downloads. I'll write the exact commands/build scripts in Phase 4–5; **you run the ones needing sudo or that pull large files**, since they're slow and machine-specific.

- [x] Base dev tools installed (`cmake`, `ffmpeg`, `python3-venv`, `portaudio19-dev`, `libopenblas-dev`; `git`/`build-essential` already present).
- [x] **Node.js** LTS (v24) installed via nvm (userland, no sudo).
- [x] Built **whisper.cpp** with CUDA (sm_87); `ggml-base.en` downloaded; GPU backend verified.
- [x] Built **llama.cpp** with CUDA (sm_87); **Qwen2.5 1.5B Q4_K_M** downloaded; intent parsing verified (~809 ms).
- [x] Cloned **node-sonos-http-api** + `npm install`; playback working.
- [ ] Install **Piper** (and optionally Kokoro) + download a kid-friendly voice model. *(not started — TTS confirmations are the remaining audio piece)*

(I'll provide a single `setup/` folder of scripts so this is mostly copy-paste, but the execution and any credential entry is yours.)

## Phase 3 — Folder structure  🧑 YOU decide / 🤖 ME propose

I propose the layout below under `/home/jetson/development/`. **Your call to approve or adjust before I scaffold it.**

```
development/
├── docs/                  # hardware.md, project_plan.md (this), future design notes
├── setup/                 # install/build scripts you run (Phase 2)
├── config/                # settings templates (sonos settings.json, .env.example)
├── models/                # downloaded GGUF / whisper / voice models (gitignored)
├── src/
│   ├── app.py             # entrypoint: button loop → pipeline
│   ├── state.py           # VoiceRequestState dataclass
│   ├── nodes/             # transcribe, classify, sonos_*, tts, log_request
│   ├── router.py          # intent → ordered node list
│   ├── clients/           # thin HTTP wrappers (whisper, llama, sonos)
│   └── config.py          # loads env/config
├── data/                  # requests.sqlite, blocklist (gitignored)
├── services/              # systemd unit files for the 3 persistent servers
├── tests/                 # per-node + end-to-end smoke tests
├── requirements.txt
├── .gitignore
└── README.md
```

Decisions (resolved):
- [x] Tree approved.
- [x] Everything lives on the NVMe (OS, models, app, data). The microSD is unused.
- [x] `git init` done with a `.gitignore` excluding models, data, and secrets.

## Phase 4 — Application code  🤖 ME (boilerplate)

Once Phases 0–3 are done, I write all of this:

> **Status:** the pipeline currently runs pragmatically as `src/listen_and_play.py` + `src/intent.py` (record → transcribe → LLM intent → Sonos), verified end-to-end via CLI. The fuller `state.py` / `clients/` / `nodes/` / `router.py` split, SQLite logging, and the `evdev` app loop below are **not yet built** (deliberately deferred — the Paw Key layer brings the app loop).

- [ ] `state.py` — `VoiceRequestState` dataclass.
- [ ] `clients/` — HTTP wrappers for whisper-server, llama-server, node-sonos-http-api (plain `requests`, ~5 lines each).
- [ ] `nodes/` — `transcribe`, `classify` (with the JSON-extraction system prompt), `sonos_play`, `log_request`, `speak_response`. (volume/pause/content-filter nodes stubbed for v2.)
- [ ] `router.py` — `route(state)` mapping intent type → ordered node list.
- [ ] `app.py` — evdev keypress loop, record-until-release from ReSpeaker, run the pipeline.
- [x] Request-log schema + insert — done as **DuckDB** (`src/db.py`, not SQLite);
      see `docs/data-logging.md`.
- [ ] `config.py` + `.env.example` template. *(config currently lives in `config/jukebox.env`.)*
- [x] `requirements.txt` — present (currently just `duckdb`; the core pipeline is stdlib + external CLIs).
- [ ] `README.md` with run instructions.

## Phase 5 — Boot architecture, resilience & persistent services  🤖 ME writes / 🧑 YOU runs

The system is an appliance: it must come back by itself after power loss,
unplugging, or being moved to another room and plugged back in — and signal
readiness audibly (no screen). Built around a single **`jukebox.target`** with
a strict "every component registers here" rule. Full design + the add-a-service
checklist live in [services/README.md](../services/README.md).

- [x] `jukebox.target` umbrella + per-component units (`jukebox-sonos`, `jukebox-llm`,
      `jukebox-leds`, `jukebox-ready`), `Restart=always` on the servers,
      `After/Wants=network-online.target` so Sonos re-discovers after a move.
- [x] **Readiness MEOW** — `jukebox-ready` waits on `setup/jukebox_healthcheck.sh`
      (the single registry of components) until all are healthy, then plays
      `assets/ready_meow.wav`. A meow = whole system initialized.
- [x] `setup/install_services.sh` — installs + enables **every** `jukebox-*.service`
      it finds and starts the target (auto-discovery = nothing slips past boot).
- [x] udev rule re-runs `jukebox-leds` on mic replug; `config/jukebox.env` centralizes
      room / audio device / ports.
- [x] 🧑 Ran `setup/install_services.sh` — all units active + enabled, meow heard; reboot-tested (came back and meowed). *(DisplayPort cold-boot quirk → manage via SSH; see `docs/runbook.md`.)*
- [x] Paw Key push-to-talk: `src/pawkey_listen.py` + `jukebox-pawkey.service`
      (access via `SupplementaryGroups=input audio` — no udev rule needed).
      🧑 re-run `setup/install_services.sh` to enable it, then hold the paw to test.
- [x] Audio output set to the Pebble V3 (`JUKEBOX_AUDIO_DEVICE=plughw:CARD=V3,DEV=0`); meow verified through it. *(Plugged direct for now; mic picks up USB-power buzz until the powered hub arrives — see `docs/runbook.md`.)*

> **STARTUP CONTRACT (applies to every future addition):** any new persistent
> server/tool MUST get a `jukebox-<name>.service` (PartOf/WantedBy `jukebox.target`),
> a health line in `setup/jukebox_healthcheck.sh`, and a re-run of
> `install_services.sh`. See the checklist in [services/README.md](../services/README.md).
> This is how we keep new functionality from slipping through the cracks.

## Phase 6 — v2 features (future, not now)

- [x] Intent **router** actions wired in `src/pipeline.py`: pause (`/pause`),
      resume (`/play`), volume ±N (`/volume/±N`). Verified live.
- [x] **Voice-specified room + volume** — intent extracts a room (→ default Living
      Room) and an absolute volume; default behavior **maintains** the room's
      current volume. (`src/intent.py`, `src/pipeline.py`)
- [x] **Request logging** — DuckDB `data/jukebox.duckdb`, one row per song request
      (transcript, intent, returned track + explicit flag, outcome). Search moved
      into `src/spotify_resolve.py`. See `docs/data-logging.md`.
- [x] **Quiet hours** — deterministic clock gate `setup/within_play_hours.sh`
      (songs play 05:00–22:00); blocked requests log `outcome='blocked_time'`.
- [x] **Explicit-lyrics gate** — `src/blocklist.py` refuses Spotify-explicit tracks
      after resolve in `pipeline._play_song`; logs `outcome='blocked_explicit'`.
      `JUKEBOX_BLOCK_EXPLICIT` (default on). See `docs/blocklist.md`.
- [ ] **Blocked-feedback sound** — record/generate a spoken "not allowed" clip,
      point `JUKEBOX_BLOCKED_SOUND` at it (hook `_play_blocked_feedback` wired).
- [ ] **Per-artist/title blocklist** — extend `blocklist.check()` with a parent-
      curated list (DuckDB table / config); logs `blocked_artist` / `blocked_title`.
- [ ] **Request history analytics** over the DuckDB log.
- [ ] Revisit LangGraph *only* if multi-turn ("like the last song"), retry loops, or human-in-the-loop ("did you mean X or Y?") become real requirements.

---

## Current status & next steps

**Working end-to-end (committed):** speak → whisper.cpp (CUDA) STT → llama.cpp
intent → Sonos **play / pause / resume / volume**, with the Paw Key push-to-talk
daemon, all under the systemd `jukebox.target` boot stack + readiness **meow**.
Mic on the powered hub is clean; WiFi fixed (antennas). Verified live — see `git log`.

**Next build increments (in order):**
1. **Blocked-feedback sound** — the audible "sorry, that song isn't allowed" clip
   for refused songs. Hook is wired (`_play_blocked_feedback` / `JUKEBOX_BLOCKED_SOUND`);
   needs the WAV (record, or generate once TTS lands). Then extend the content gate
   with a **parent-curated per-artist/title blocklist** (`blocked_artist`/`_title`).
2. **TTS confirmations** (Piper) — spoken "Playing …" / denial responses (incl.
   a spoken reason on a quiet-hours or blocklist block; reuses the feedback hook).
3. **Artist-hallucination — finish it.** Done so far: `resolve_song()` progressive
   fallback drops the artist filter on a no-match, so songs that returned *nothing*
   now play (`docs/sonos-notes.md`). Remaining: when a bogus artist matches a
   real-but-wrong track (e.g. "Let It Go" → a reggae cover), the fallback never
   fires. Fix = **transcript-grounding**: only keep the artist if it actually
   appears in the spoken transcript; otherwise search title-only.
4. **Request history analytics** over the DuckDB log.
5. Physical **enclosure** polish — assembled in a LEGO case; see `docs/enclosure_brainstorm.md`.
