# Peripherals & I/O — how the hardware looks to the OS (and the gotchas)

Hard-won reference for the USB peripherals, how they enumerate, and the
non-obvious traps. Pairs with `docs/hardware.md` (what we bought) and
`docs/runbook.md` (debugging). Physical layout ideas: `docs/enclosure_brainstorm.md`.

## Device map (as seen by Linux)

| Device | USB ID | ALSA card | input (`/dev/input`) | Control |
|---|---|---|---|---|
| ReSpeaker XVF3800 mic | `2886:001a` | **`Array`** (capture **and** playback) | event14–16 (HID for LEDs/control) | LED via `xvf_host`; udev 0666 |
| Pebble V3 speaker | `041e:3272` | **`V3`** (playback) | event2 (`ACTIONS Pebble V3` — volume keys, unused) | none needed |
| Keychron Paw Key | `3434:0400` | — | **event3–6** (`Keychron Paw Launcher` ×4) | grabbed by daemon (EVIOCGRAB) |

(Also present in dev: a Logitech K120 keyboard `046d:c31c` and a SiGma mouse
`1c4f:0048` — those are *not* part of the appliance; don't bind to them.)

> ⚠️ **Address ALSA devices by NAME, never by number.** Card *numbers* shuffle on
> reboot / when moved between USB ports or onto the hub (e.g. the Pebble was card
> 3 directly, card 0 via the hub). All configs use `plughw:CARD=V3,DEV=0` /
> `plughw:CARD=Array,DEV=0`. Never use `hw:0`/`hw:2`.

## ReSpeaker XVF3800 (mic — and a second speaker output)

- ALSA capture card **`Array`**; the app records 16 kHz mono via
  `plughw:CARD=Array,DEV=0`.
- It **also presents an audio OUTPUT** (USB playback + a 3.5 mm line-out). So in a
  pinch the Jetson can play TTS/meow through the mic array, not just the Pebble.
- **LED ring** is controlled by the vendor binary
  `tools/reSpeaker_XVF3800_USB_4MIC_ARRAY/host_control/jetson/xvf_host` (aarch64).
  Wrapper: `setup/respeaker_led.sh off|breath|rainbow|single|doa`. Non-root access
  comes from the udev rule (`setup/respeaker/99-respeaker-xvf3800.rules`, MODE 0666).
- The LED is the **"listening" indicator** — lit while the paw is held.
- **AGC gotcha:** the XVF3800 has automatic gain control, so in silence it *boosts
  the noise floor*. When the Pebble was USB-powered off the Jetson, that injected
  hum showed up amplified as `(buzzing)` in STT. Fix = power peripherals from the
  hub (below). Use `setup/mic_check.sh` to measure the noise floor (clean ≈ −60 dB,
  buzzy ≈ −41 dB).
- ⚠️ **Brownout = "buzzing" + dark LED (it MUST be on the powered hub, not a Jetson
  port).** The XVF3800 draws real current (XMOS DSP + 4 capsules + 12 LEDs). On a
  Jetson direct USB port it browns out: the **audio pipeline and LEDs starve while
  the control core still answers**, so it looks half-alive. Tell-tale: `mic_check`
  returns the *same* stats every time (`crest ≈ 2.8`, ~−34 dB) even while you tap or
  shout at it, the **LED ring stays dark**, but `xvf_host VERSION`/param reads still
  work. **Control responding ≠ mic working.** Crest factor is the quick test (speech
  >8, starved <4) and the **LED is a live power-health light** (lit = DSP healthy,
  dark = starved). Fix: put it on the externally-powered hub and full power-cycle
  (unplug ~10 s, replug). Reboots/DSP-setting changes do NOT fix it. Full
  diagnostic walk-through in `docs/runbook.md` ("(buzzing) — TWO root causes").

## Keychron "Big Kitty" Paw Key (push-to-talk button)

The single most surprising device. Read this before touching `pawkey_listen.py`.

- Enumerates as **four** input devices (USB `3434:0400`, name "Keychron Paw
  Launcher"): event3 (keyboard), event4 (Mouse), event5 (System Control),
  event6 (Consumer Control). The daemon matches by **name** and reads all of them.
- The big paw sends **`KEY_ENTER` (code 28)** on event3 by default — i.e. it acts
  like the **Enter key**. It's a normal **held key**: `DOWN` on press, autorepeat
  (value 2) while held, `UP` (value 0) on release. That held-key behavior is what
  makes "record while held" work. (If a future paw is reconfigured in Keychron
  Launcher to fire a one-shot macro, record-while-held breaks — `--monitor` shows
  an instant DOWN+UP; then switch to tap-to-toggle or reconfigure the key.)
- ⚠️ **It leaks keystrokes.** Without intervention, pressing the paw types Enter
  into whatever has focus (your terminal!). The daemon therefore **EVIOCGRABs** the
  devices (claims them exclusively) so events go only to it. `EVIOCGRAB` is done by
  ioctl in pure Python (no `evdev` dependency) — see `src/pawkey_listen.py`.
- ⚠️ **Permissions:** `/dev/input/event*` is `root:input 0660`, and the `jetson`
  user is **not** in the `input` group. So:
  - The service reads input via `SupplementaryGroups=input` (in
    `jukebox-pawkey.service`) — no udev rule needed.
  - **Manual** runs need root: `sudo src/pawkey_listen.py` (or `--monitor`). Stop
    the service first (`sudo systemctl stop jukebox-pawkey`) so the grab is free.
- **Debugging:** `sudo src/pawkey_listen.py --monitor` prints `event3 code=28 DOWN
  / repeat / UP` so you can confirm the button and keycode.
- **Usage:** you must **hold** the paw the whole time you speak, then release. A
  tap < 0.3 s is ignored ("too quick").

## Pebble V3 (TTS / meow speaker)

- ALSA playback card **`V3`** → `plughw:CARD=V3,DEV=0` (set as
  `JUKEBOX_AUDIO_DEVICE` in `config/jukebox.env`).
- Plain USB audio, plug-and-play. Its onboard volume buttons enumerate as an input
  device (`ACTIONS Pebble V3`) but we don't use them.

## PulseAudio contention (a recurring trap)

A desktop sound server (PulseAudio, pid often ~1500s, user `jetson`) runs because
of the autologin GUI session and **grabs USB audio devices**. Our system services
use **exclusive `plughw` (ALSA hw) access**, which collides with it:

- **Symptom:** `aplay: audio open error: Device or resource busy` (seen on the boot
  meow when Pulse held the device during its init).
- **Fix pattern:** retry until the server releases the idle device — Pulse suspends
  idle PCMs after a few seconds (`jukebox_ready.sh` retries ~40 s). The capture side
  (`arecord` from the mic) generally isn't contended, but keep this in mind if mic
  capture ever returns "busy".

## Powered USB hub (Sabrent) — not optional

All USB peripherals (mic, Pebble, Paw Key) go through the **externally-powered**
hub so they draw from the hub's adapter, not the Jetson's USB rail. This isn't just
tidiness, and it bit us **twice**:
1. With the **Pebble** drawing power directly from the Jetson, electrical noise
   coupled into the mic and STT heard `(buzzing)`. The hub fixed it.
2. With the **mic** plugged into a Jetson port (during post-reassembly debugging),
   the XVF3800 **browned out** — dead audio + dark LED while control still answered
   (see the ReSpeaker brownout note above). Moving it back onto the hub fixed it.
So **every** appliance peripheral belongs on the hub — the mic especially, since its
DSP+LEDs are the most power-hungry. (Must be the powered variant with its own brick —
a bus-powered hub makes it worse. And confirm the brick is actually plugged in: a
hub still *enumerates* devices when bus-powered, so "they show up" doesn't prove the
external power is connected.)

⚠️ **Plug the hub into the SAME power strip/outlet as the Jetson — not a separate
one.** A third time it bit us (room move, 2026-06-13): the hub on a *different* wall
outlet from the Jetson+Sonos strip created a **ground loop** — a small ground-
potential difference between the two outlets coupled mains hum into the USB mic
(‑41 dB `(buzzing)`, but the LED was lit so it wasn't brownout). Consolidating all
three onto one strip (common ground) fixed it instantly. Treat "one power strip,
one outlet" as a hard rule whenever the unit is relocated — see the relocation
checklist in `docs/runbook.md`.

## See also
- **WiFi** (dev kit ships no antennas → weak signal until a pair is added): `docs/runbook.md`.
- **Audio device for the meow / TTS**: `config/jukebox.env` → `JUKEBOX_AUDIO_DEVICE`.
