# Boot architecture & the "add a component" rule

The jukebox must come up by itself after power loss, unplugging, or being moved
to another room and plugged back in. systemd owns that. Everything hangs off one
umbrella unit: **`jukebox.target`**.

```
jukebox.target                         (enabled → starts at boot)
├── jukebox-sonos.service   node-sonos-http-api  :5005   Restart=always
├── jukebox-llm.service     llama.cpp server     :8080   Restart=always
├── jukebox-leds.service    ReSpeaker ring → off (idle = dark)   oneshot
├── jukebox-pawkey.service  Paw Key push-to-talk daemon          Restart=always
└── jukebox-ready.service   waits for health → plays the MEOW    oneshot
```

- **Resilience:** the long-running servers use `Restart=always`, so a crash or a
  network blip self-heals. `jukebox-sonos` waits for `network-online.target` and
  re-discovers Sonos on start, so a reboot after moving rooms just works.
- **Readiness:** `jukebox-ready` polls `setup/jukebox_healthcheck.sh` until every
  component answers, then plays `assets/ready_meow.wav`. **A meow = the whole
  system is initialized and ready.** (Drop in a real `meow.wav` to replace the
  synthesized placeholder; set the speaker via `JUKEBOX_AUDIO_DEVICE` in
  `config/jukebox.env`.)
- **Replug:** the udev rule (`setup/respeaker/…rules`) re-runs `jukebox-leds` when
  the mic is plugged back in.

## Install / update

```bash
setup/install_services.sh      # installs every services/jukebox-*.service, enables all, starts target
```
Idempotent — re-run anytime. It auto-discovers and enables **every**
`jukebox-*.service`, which is the mechanism that stops new components from
slipping past startup.

Handy:
```bash
setup/jukebox_healthcheck.sh --status      # is everything up?
systemctl status 'jukebox-*'               # service states
journalctl -u jukebox-ready -b             # readiness/meow log this boot
```

## ✅ Checklist: adding a new server/tool (DO ALL THREE)

Whenever we add a persistent server (e.g. a whisper-server, a TTS server, the
push-to-talk daemon), it MUST be wired into startup:

1. **Unit** — create `services/jukebox-<name>.service` with:
   - `PartOf=jukebox.target` and `[Install] WantedBy=jukebox.target`
   - `Restart=always` if it's a long-running server
   - `User=jetson` (add `SupplementaryGroups=audio` if it plays sound)
2. **Health probe** — add one `"<name>|<kind>|<target>"` line to `COMPONENTS` in
   `setup/jukebox_healthcheck.sh` (`kind=url` → HTTP 200 from target; `kind=unit`
   → `systemctl is-active` the unit). Use `unit` for daemons with no HTTP endpoint
   (e.g. the Paw Key). Readiness then waits for it and `--status` reports it.
3. **Install** — run `setup/install_services.sh` (enables it) and reboot-test.

## ⚠️ Gotchas when authoring a jukebox service (we hit all of these)

System services run in a **stripped-down environment** as `User=jetson`. Things
that "just work" in your shell often break in the unit:

- **No `nvm`, minimal `PATH`, no CUDA on PATH.** Don't call `node`/`nvcc`
  directly. Use a launcher script that sets things up — `setup/sonos_server.sh`
  resolves the nvm node from `~/.nvm/versions/node/*/bin`; `setup/llama_server.sh`
  exports `/usr/local/cuda/bin` + `LD_LIBRARY_PATH`. Point `ExecStart` at those.
- **Group access is not the login user's groups.** `jetson` is in `audio` but NOT
  `input`. Grant per-service with `SupplementaryGroups=` (the Paw Key daemon uses
  `input audio`). USB device access (LED) comes from the udev `MODE=0666` rule.
- **Python stdout is block-buffered when it's not a TTY** → a daemon's `print()`s
  never reach the journal, so it looks silent/dead while actually running. Set
  `Environment=PYTHONUNBUFFERED=1` (we added this to `jukebox-pawkey.service`).
  Without it we were flying blind during debugging.
- **`EnvironmentFile=-/…/config/jukebox.env`** loads shared config (room, audio
  device, ports). systemd parses `KEY="value"` (quotes handled); the `-` prefix
  makes a missing/garbled file non-fatal.

### Reproduce the service environment to debug (very useful)
A command that works in your shell but fails in the service is almost always an
env difference. Reproduce systemd's minimal env directly:
```bash
env -i PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
       HOME=/home/jetson  setup/sonos_play.sh "thunderstruck acdc"
```
Add `bash -x` to trace. This is exactly how we isolated the Spotify-503 crash.

### Debugging a service generally
```bash
journalctl -u jukebox-<name> -b --no-pager | tail -40   # logs this boot
systemctl status jukebox-<name>
sudo systemctl stop jukebox-pawkey   # free an exclusive resource (e.g. EVIOCGRAB) for manual runs
```
