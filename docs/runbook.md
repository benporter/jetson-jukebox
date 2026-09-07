# Runbook — operating & debugging the jukebox (esp. boot failures)

For a fresh Claude session or a human. Assumes the systemd stack from
`setup/install_services.sh` is installed (units under `jukebox.target`).

## First 30 seconds: is it healthy?

```bash
setup/jukebox_healthcheck.sh --status        # per-component up/down
systemctl --no-pager list-units 'jukebox-*'  # service states
journalctl -u jukebox-ready -b               # readiness/meow log this boot
```

**No meow on boot?** The readiness gate (`jukebox-ready`) only meows once every
component in `jukebox_healthcheck.sh` is healthy (or after a 120 s timeout, with
a warning). So "no meow" almost always means one of the services below is down —
start with the healthcheck, then dig into the named unit.

## Components, checks, and common failures

### jukebox-sonos (node-sonos-http-api, :5005)
```bash
systemctl status jukebox-sonos
journalctl -u jukebox-sonos -b --no-pager | tail -40
curl -s http://127.0.0.1:5005/zones | head -c 300      # should list Sonos rooms
```
- **`node: command not found`** → nvm node path issue. `setup/sonos_server.sh`
  resolves `~/.nvm/versions/node/*/bin`; confirm a node exists there.
- **Empty `/zones` / can't find rooms** → ran before the network/Sonos was up.
  `Restart=always` + `After=network-online.target` should recover; `systemctl
  restart jukebox-sonos`. Confirm the Jetson is on the same LAN/subnet as Sonos.
- **Port 5005 in use** → a stray `node server.js` (e.g. a manual/Claude-session
  run). `pkill -f node-sonos-http-api/server.js` then restart the unit.
- **Spotify plays wrong/nothing** → keys in `tools/node-sonos-http-api/settings.json`.
  Remember: use `/spotify/now/`, NOT `musicsearch` (see `docs/sonos-notes.md`).

### jukebox-llm (llama.cpp server, :8080)
```bash
systemctl status jukebox-llm
journalctl -u jukebox-llm -b --no-pager | tail -40
curl -s http://127.0.0.1:8080/health                    # {"status":"ok"}
```
- **CUDA / shared-lib errors** → `/etc/profile.d/cuda.sh` puts CUDA on PATH;
  `setup/llama_server.sh` also exports `LD_LIBRARY_PATH=/usr/local/cuda/lib64`.
- **`model not found`** → `models/qwen2.5-1.5b-instruct-q4_k_m.gguf` missing
  (gitignored). Re-download per `setup/README.md`.
- **Slow first response / restart loop** → model load takes a few seconds;
  `TimeoutStartSec=120` covers it. Check free GPU RAM (`tegrastats`); whisper +
  llm + others share 8GB.
- **Binary missing** → rebuild whisper/llama with CUDA (`setup/README.md`).

### jukebox-leds (ReSpeaker ring → off)
```bash
journalctl -u jukebox-leds -b --no-pager
setup/respeaker_led.sh off        # manual test (no sudo if udev rule installed)
```
- **Permission / device open failure** → udev rule missing. Re-run
  `setup/install_respeaker.sh` (installs the rule that grants non-root access).
- Mic not plugged / different port → `lsusb | grep 2886` should show it.

### jukebox-ready (health gate + meow)
```bash
journalctl -u jukebox-ready -b --no-pager
setup/play_sound.sh assets/mixkit-sweet-kitty-meow-93.wav   # test audio out
```
- **Silent meow** → wrong/absent speaker. Check `aplay -l`, set
  `JUKEBOX_AUDIO_DEVICE` in `config/jukebox.env` (Pebble = `plughw:CARD=V3,DEV=0`).
  Note: ALSA card *numbers* can shuffle (e.g. via a USB hub); we address by
  *name* (`CARD=V3`) so that's fine — don't switch to `hw:N`.
- **`aplay: audio open error: Device or resource busy`** at boot → PulseAudio
  holds the USB audio PCM during its init; exclusive `plughw` collides.
  `jukebox_ready.sh` retries for ~40 s to wait it out. If it still fails, the
  sound server may be holding the device persistently — `fuser -v /dev/snd/*`
  to see who, or play via Pulse (`paplay`) instead.
- **Meowed but services flaky** → it meows after a 120 s timeout even if not all
  healthy; re-check `jukebox_healthcheck.sh --status`.

## Manual bring-up (bypass systemd to isolate a problem)

Run each in its own terminal; tells you if the issue is the service wrapper vs.
the program itself:
```bash
setup/sonos_server.sh          # :5005
setup/llama_server.sh          # :8080
setup/jukebox_healthcheck.sh --status
```

## Recovery cheatsheet

```bash
systemctl restart jukebox.target           # restart everything
systemctl restart jukebox-llm              # just one
sudo systemctl daemon-reload && setup/install_services.sh   # after editing units
sudo journalctl -b -p err --no-pager | tail -50             # all boot errors
```

## Known issues & appliance notes

### WiFi must auto-connect headlessly (no login)
With autologin/no-login, WiFi has to come up before any desktop session. If the
password is stored in the per-user GNOME keyring it only connects after login →
password popups + services starting with no network. Fix: store it in the
**system** connection file instead. One-shot helper:
```bash
sudo setup/wifi_autoconnect.sh "YOUR_SSID"     # or omit the arg to use JUKEBOX_WIFI_SSID from config/jukebox.env; prompts for the password
```
It makes a single clean system profile (`psk-flags=0`, `permissions=""`,
autoconnect) and enables `NetworkManager-wait-online` so `network-online.target`
waits for real connectivity before `jukebox-sonos` starts. Verify with
`nmcli -t -f NAME,TYPE,AUTOCONNECT,ACTIVE connection show`; truly test by
unplugging ethernet and rebooting. (Check `psk-flags` is `0` = stored in
`/etc/NetworkManager/system-connections/<SSID>.nmconnection`, not the keyring.)

**✅ RESOLVED (2026-06-07): the dev kit ships with no WiFi antennas at all.** The
AzureWave AW-CB375NF module's **Main + Aux** u.FL ports shipped bare (no antennas
included). Snapping on an added pair of **MHF4 u.FL antennas** took the signal
from ‑76/‑91 dBm to **‑34 dBm,
2×2 MIMO (NSS 2), ~866 Mbit/s**, and WiFi-only boot now leases DHCP in seconds.
So the whole "flaky RTL8822CE" saga below was really just **missing antennas** —
check those FIRST next time. Diagnostic trail kept for reference:

**Onboard WiFi = Realtek RTL8822CE (`rtl88x2ce`) on AzureWave AW-CB375NF.**
Observed: warm reconnect leases IPv4 in ~10 s, but a *cold-boot / first-connect*
DHCP once took ~5 min (associated fine, repeated "no lease", then succeeded) —
during which there's no IPv4 and pages don't load. Quick checks:
```bash
nmcli connection down YOUR_SSID && time nmcli connection up YOUR_SSID   # warm DHCP time
ping -I wlP1p1s0 -c3 1.1.1.1                                        # internet over wifi
journalctl -u NetworkManager -b | grep -iE 'wlP1|dhcp4'            # boot DHCP timeline
```
Easy culprits to rule out (all were fine here): power-save (`iw dev wlP1p1s0 get
power_save` → off), MAC randomization (in-use MAC == hardware MAC), `rp_filter`.

**CONFIRMED (2026-06-07): WiFi-only cold boot fails.** It associates, then the
supplicant loops (`completed → associated → 4way_handshake → completed` every
~10 s) and DHCP4 never completes — WiFi stays IPv4-less (IPv6 only) indefinitely;
pages don't load. `ipv4.may-fail=yes` makes NM report the connection "activated"
on IPv6 alone, masking the missing IPv4. Easy culprits (power-save, MAC
randomization, rp_filter) were all ruled out → it's the flaky onboard radio.
Power/ASPM is already disabled (image ships `/etc/modprobe.d/rtl8822ce.conf` with
`rtw_power_mgnt=0 rtw_pci_aspm_enable=0 …`), so that's not it.

**Root cause = weak signal on BOTH bands.** 5 GHz was ‑76 dBm; forcing 2.4 GHz
(`wifi.band bg`) was *worse*, ‑91 dBm / 1 Mbit/s. So it's not band selection — the
onboard radio just can't get a usable link here. Remedies, cheapest first:
1. **Revert the band lock:** `sudo nmcli con mod YOUR_SSID wifi.band ""` (let it pick the stronger band).
2. **Add WiFi antennas (the dev kit includes none)** — the onboard M.2 card has two
   u.FL ports but ships **bare**; with nothing attached, *both* bands are weak. A
   pair of MHF4 u.FL antennas is cheap and the prime suspect when both bands are
   this poor.
3. **Relocate closer to the router** / improve line-of-sight.
4. **USB WiFi dongle with an EXTERNAL antenna** on the powered hub (in-kernel
   Mediatek MT7612U dual-band, or MT7601U 2.4-only — fine since we only send
   commands; the *antenna* matters more than the chipset). Then
   `nmcli con mod <SSID> ipv4.may-fail no`.
5. Or just use **ethernet** — most reliable.

(Power-mode note: this board's `nvpmodel.conf` defines only 15W (id 0) and 7W
(id 1) — no 25W/MAXN-SUPER mode is available to switch to without enabling the
Super power model. 15W is plenty for our light bursty STT/LLM workload.)


### `jetson-orin-nano.local` / SSH / dashboard fail from another machine (IPv6 mDNS)
Symptom: you can reach the box by **IP** (`ssh jetson@192.168.1.174`,
`http://192.168.1.174:8088/`) but the **`.local` hostname hangs/"can't be reached"**
from a Mac/other client, while an already-open SSH session keeps working.

Root cause: the box picked up **IPv6 ULA addresses** (`fd23:…`), so avahi advertised
AAAA records and clients (esp. macOS) **prefer IPv6** — but the dashboard binds
IPv4-only and SSH-over-ULA doesn't route cleanly, so new connections hang. This is
a **side effect of `setup/wifi_autoconnect.sh`**: rebuilding the `YOUR_SSID` profile
gives it NetworkManager's default `ipv6.method=auto`, which SLAACs the ULA prefix.

Fix (this is an IPv4-only appliance — Sonos/Spotify/SSH are all IPv4):
```bash
sudo nmcli connection modify YOUR_SSID ipv6.method disabled   # saved; applies on reconnect/reboot
sudo reboot                                                # or: nmcli c up YOUR_SSID (drops IPv6 sessions)
# verify: `ip -6 addr show scope global` empty; avahi-resolve -n jetson-orin-nano.local -> 192.168.1.174
```
On the client (macOS) flush the stale cache: `sudo dscacheutil -flushcache;
sudo killall -HUP mDNSResponder`. (Belt-and-suspenders done on the box too:
`use-ipv6=no` + `publish-aaaa-on-ipv4=no` in `/etc/avahi/avahi-daemon.conf`.)
Most robust of all: set a **DHCP reservation** for the box on the router.


### Headless: don't depend on the monitor (SSH instead)
The DisplayPort monitor sometimes isn't detected on a **cold boot** (black screen
even though the system booted fine and meowed). This is a known Jetson/L4T DP
detection quirk. The device is a screenless appliance anyway — **manage it over
SSH**, which is installed + enabled:
```bash
ssh jetson@192.168.1.174        # check current IP with: hostname -I
```
If you do need the local screen back without a full reboot, try:
`sudo systemctl restart gdm3` (or replug the DP cable after the monitor is on).

### Login keyring password prompt
Autologin is on (`/etc/gdm3/custom.conf: AutomaticLogin=jetson`), so PAM never
unlocks the GNOME "login" keyring → it prompts. To make it auto-unlock:
- **GUI:** Passwords and Keys (seahorse) → right-click **Login** → Change Password
  → enter current, leave the new password **empty**.
- **Headless:** remove the password-protected keyring so a new empty, auto-unlocked
  one is created on next login:
  ```bash
  rm -f ~/.local/share/keyrings/login.keyring && reboot
  ```
  (Safe here: Wi-Fi creds live in `/etc/NetworkManager`, not the user keyring.)
  Verify the prompt is gone after reboot.

### A peripheral disappears after reassembly (moving into the enclosure)
After the device was assembled into its LEGO case, the **mic and Paw Key both
vanished** — gone from `lsusb` entirely — while the Pebble still worked and the
boot meow still played (the meow only needs the speaker, so a meow does **not**
mean the mic/button are present). Root cause: **bad USB cables**, dislodged or
swapped during the build. Diagnose hardware FIRST here, not software.

**The key tell — powered but not enumerating:** the mic's **LED lit up** (it had
+5 V) but it was **absent from `lsusb`** and its boot LED setting never applied
(`jukebox-leds` drives the ring over USB via `xvf_host`; with no data link it
can't reach it). A device that **powers on / lights up but never appears in
`lsusb` = the USB data lines aren't connecting** — a charge-only cable, a
defective/marginal "data" cable, or a connector seated just far enough for the
power pins but not the data pins. (Fully dark instead = no power at all — a
different problem.) ⚠️ "Data-rated" on the box is **not** a guarantee: the
cables that failed us were advertised as *USB 2.0 480 Mbps data* 3-inch USB-A→C
cords (Amazon `a.co/d/06aaIDM7`, 2-pack) — the short braided units still wouldn't
carry data. Swapping to known-good data cables fixed it instantly.

Diagnose in this order:
```bash
lsusb                                    # is the device even on the bus?
for id in 3434:0400 2886:001a 041e:3272; do lsusb | grep -qi $id \
  && echo "✅ $id" || echo "❌ $id MISSING"; done   # pawkey / mic / pebble
lsusb -t                                 # tree: which hub/port is it under?
```
- **Missing from `lsusb`** → it's physical (cable/port/device), never software.
  A reboot will **not** fix a loose or dead cable (we confirmed — two reboots,
  no change). Don't keep rebooting; isolate the cable.
- **Isolate cable vs hub-port vs device** with a bypass test: plug the device
  **straight into a Jetson USB port**, skipping the Sabrent hub. Appears → bad
  hub port or pinched in-case cable run. Still gone → that **cable or device**
  is dead; swap the cable first (cheapest), then suspect the unit.
- **Watch the device numbers** in `lsusb` bump across a replug (e.g. Pebble
  `005`→`008`) to confirm the bus actually re-enumerated when you reconnected.

**After the hardware is back**, the boot services self-heal: `jukebox-pawkey`
has `Restart=always`, so it keeps restarting until the Paw Key exists, then
grabs `event5–8` cleanly; the udev rule re-runs `jukebox-leds` on mic replug.
Confirm with `setup/jukebox_healthcheck.sh --status` (all green) and
`journalctl -u jukebox-pawkey -b | tail` (`Paw Key on: …  Ready.`). If a service
doesn't pick the device back up, `systemctl restart jukebox-pawkey jukebox-leds`.
**Prevention:** use known-good *data* cables in the enclosure and label them so a
charge-only cord never gets swapped in.

### Mic STT hears "(buzzing)" — FOUR different root causes (don't confuse them)

Triage with the **LED ring** and the **noise floor** (`setup/mic_check.sh`):
ring **lights on command** → mic has power → it's coupling (A or **C**); ring
**stays dark** → brownout (**B**). Then use the table below.

**Cause A — electrical coupling from the Pebble (the original case).** A USB-powered
speaker (Pebble V3) drawing power from the Jetson's USB rail couples electrical
noise into the mic (the XVF3800's AGC amplifies it). Noise floor ≈ ‑41 dB; whisper
hears `(buzzing)`. **Fix:** put the *speaker* on the externally-powered hub.

**Cause B — the XVF3800 itself is browned out (insufficient power).** This one cost
us hours after the LEGO build. The ReSpeaker is power-hungry (XMOS DSP + 4 capsules
+ 12-LED ring). On a **Jetson direct USB port** (or a bus-powered hub) it can't draw
enough current, so its **audio pipeline and LEDs starve while the low-power control
core keeps answering** — a half-alive state that masquerades as "the mic is fine, the
audio is just noisy." Signature, and how to tell it apart from Cause A:

- **Identical capture stats every time** — `Pk ≈ ‑25 dB, RMS ≈ ‑34 dB, crest ≈ 2.8`
  on *every* `mic_check`, whether you're silent, speaking, or **tapping the mic**.
  Live mic audio never does that; a starved DSP emits a fixed-character noise.
- **Crest factor is the fast test.** `sox file.wav -n stats | grep Crest`. **Speech
  = crest >8** (dynamic); **dead/starved = crest <4** (steady). A clear voice that
  reads crest ~2.8 means your voice isn't being transduced at all.
- **The LED ring = a power-health indicator.** Healthy DSP → ring lights on command
  (`setup/respeaker_led.sh rainbow|breath|off`) and on paw-press. **Dark ring =
  starved.** If the ring won't light, the mic audio is dead too — same root cause.
- **"Control works" ≠ "mic works."** `xvf_host VERSION` and param reads (e.g.
  `PP_AGCONOFF`) still succeed when browned out — they run on the management core.
  Don't let a working control channel convince you the mic is healthy.
- **Immune to every DSP setting.** Writing `PP_AGCONOFF`, `PP_AGCMAXGAIN`,
  `PP_MIN_NS/NN` changes nothing — the pipeline producing the noise isn't running
  normally. If DSP tweaks do nothing, stop tuning software and check **power**.
- **A reboot does NOT fix it** (the port still can't supply the current); neither do
  AGC/noise-suppression changes. Only real power does.

**Fix (Cause B):** move the mic onto the **externally-powered hub** (NOT a Jetson
port), then **full power-cycle it** — unplug completely ~10 s so the DSP resets, then
replug. Pass criteria, both objective: the **ring lights**, and a tap/voice makes the
**crest factor jump off ~2.8 to >8** (`Born to Be Wild` transcribed cleanly once it
was on hub power). Powering the *mic* off the hub is as mandatory as powering the
Pebble off it — see `docs/peripherals.md`.

**Cause C — a ground loop after a room move (2026-06-13).** It worked, we moved it
to a new room, and the buzz came back (RMS ≈ ‑41 dB, `(buzzing)`) — but the **LED
was lit** (so NOT brownout) and nothing about the wiring had changed *except the
outlets*: the Jetson + Sonos were on a power strip on one wall outlet and the
**powered hub was plugged into a different outlet**. Two separate outlets sit at
slightly different ground potentials, and that difference couples mains hum into
the USB mic. The give-aways that distinguish C from A/B:
- LED **lit** (powered — rules out brownout/Cause B), yet buzzing.
- ‑41 dB coupling level, **not** the steady crest≈2.8 of a brownout.
- **It worked before the move** and only the *outlet arrangement* changed.

**Fix (Cause C):** put **everything on the same power strip** — Jetson, Sonos,
*and* the hub — so they share one ground reference. Moving the hub's plug onto the
Jetson's strip took it from ‑41 dB `(buzzing)` to ‑53 dB `[BLANK_AUDIO]` instantly.
A reboot does **not** help (it's electrical, not state). This is now part of the
relocation checklist below.

**Cause D — a noisy *port* on the powered hub (2026-06-15).** Same ‑41 dB
`(buzzing)`, LED **lit** (not brownout), Jetson + hub already on one strip (not a
ground loop) — yet still buzzing. The culprit was the specific **USB hub port** the
mic was in: moving the mic to a *different port on the same hub* dropped it
‑41 → ‑49 → finally **‑61 dB, crest 11** `[BLANK_AUDIO]` and speech transcribed
perfectly. Some hub ports inject more switching noise than others.
- Tell-apart: LED lit, single power strip (rules out B and C), and unplugging
  *neighbor* devices (speaker/paw) doesn't help — only **moving the mic's own
  port** does. `setup/mic_check.sh` after each move makes it obvious (crest climbs
  toward >8 as you find a clean port).
- **Fix (Cause D):** try the mic in each hub port, keep the quietest. On our
  4-port hub: **port 1 = clean, port 2 = noisy** (mic→1, speaker→3, paw→4, 2 empty).

### Relocating the jukebox to a new room (it's a portable appliance)
Moving the unit triggers several of the failure modes above at once. After any
move, run through this:
1. **One power strip.** Jetson + Sonos speaker + powered hub all on the **same
   strip/outlet** — not split across outlets (Cause C ground loop). Avoid
   switch-controlled outlets (a wall switch can silently kill the hub → brownout).
2. **Mic check.** `setup/mic_check.sh` → expect ‑50 dB or lower and `[BLANK_AUDIO]`.
   `(buzzing)` ≈ ‑41 dB = ground loop (step 1); dark LED = brownout (Cause B).
3. **Sonos reachable.** `curl -s localhost:5005/zones | python3 -m json.tool | grep roomName`
   should list the rooms; if empty, `systemctl restart jukebox-sonos` (re-discovers).
4. **WiFi / network.** If on WiFi, confirm it reconnected (the boot stack waits for
   `network-online.target`); ethernet is most reliable. See the WiFi section above.
5. **Meow on boot** confirms the *speaker + services*, not the mic — always do the
   mic check (step 2) separately.
6. **Replugged any USB on the hub? → `rjp`.** The Paw Key daemon `EVIOCGRAB`s the
   button's input devices **once at startup**. Unplugging/replugging *anything* on
   the hub re-enumerates USB and invalidates those grabbed handles, so the daemon
   goes deaf to the paw — you press it and get **no `🐾 listening…` line at all**
   (the event device numbers can even look unchanged). Fix: `rjp`
   (`sudo systemctl restart jukebox-pawkey`) re-opens/re-grabs the current devices;
   you'll see a fresh `Paw Key on: …` line. So after ANY mic/speaker/cable shuffle,
   restart the daemon.

### "It heard me but nothing plays" — check quiet hours first
Songs only play **05:00–22:00** local (the deterministic gate
`setup/within_play_hours.sh`). Outside that window a request is logged
`outcome='blocked_time'` and silently not played. Quick checks:
```bash
date +%H:%M                         # is it within 05:00-22:00?
setup/within_play_hours.sh; echo $?  # 0 = allowed, 3 = blocked
setup/within_play_hours.sh 14:00     # test a specific time
```
Change the window in `config/jukebox.env` (`JUKEBOX_PLAY_START`/`END`), then
`sudo systemctl restart jukebox-pawkey`. If it's *inside* the window and still
silent, it's not the gate — check the pawkey journal and Spotify/Sonos (above).

### Inspect the request log (DuckDB) without fighting the daemon
`data/jukebox.duckdb` is **single-writer** — connect **read-only** while the
jukebox is running, or you'll get a lock error:
```bash
python3 -c "import duckdb; [print(r) for r in duckdb.connect('data/jukebox.duckdb', read_only=True).execute('select requested_at,transcript,result_track_name,outcome from requests order by requested_at desc limit 20').fetchall()]"
```
Full schema + queries: `docs/data-logging.md`. If the daemon logs
`(db log failed: …)` it's non-fatal — playback continues; logging is best-effort.

## Resuming the Claude session (full conversation context)

From the project dir after a reboot:
```bash
claude --resume      # pick this conversation from the list
claude --continue    # resume the most recent
```
If you can't resume, a new session still auto-loads `CLAUDE.md`; combined with
this runbook, `docs/project_plan.md`, and `git log`, that's enough to continue.
