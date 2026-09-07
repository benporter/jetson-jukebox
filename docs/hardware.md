# Hardware

The confirmed, locked-in hardware stack for this project. This is what we're building against — no alternatives, no "could also use."

## Components

| Component | Product | Notes |
|---|---|---|
| **Compute** | NVIDIA Jetson Orin Nano **Super** Dev Kit | 8GB RAM (shared CPU/GPU), 67 TOPS |
| **SSD (primary)** | Samsung 990 PRO w/ Heatsink 1TB NVMe M.2 | Gen4 drive; board runs it at PCIe Gen3 x4. **Everything lives here** — OS, models, app, data. |
| **microSD** | Samsung Pro Endurance 128GB | **Purchased but NOT used.** The system boots and runs entirely from NVMe; the microSD is unused/available. |
| **Microphone** | Seeed ReSpeaker XVF3800 USB 4-Mic Array | 360° far-field, USB plug-and-play, AEC/DOA/AGC built in |
| **Speaker** | Creative Pebble V3 | TTS confirmation output only (not music — that goes to Sonos). Powered via the USB hub, not the Jetson directly. |
| **Button** | Keychron Big Kitty Paw Key | USB HID device, used as push-to-talk trigger |
| **USB hub** | Sabrent 4-Port USB 3.0 Hub | All USB peripherals (mic, speaker, Paw Key) connect through this so they draw power from the hub, not the Jetson's USB rail. **Must be the externally-powered variant** (with its own DC adapter) to actually offload power — a bus-powered hub would funnel all draw through one Jetson port and make brownout *worse*. ⚠️ Verify the unit has a power brick. |
| **WiFi antennas** | Pair of u.FL / IPEX **MHF4 (4th-gen)** flat antennas, 10 cm, 2.4/5/6 GHz | ✅ Added to the onboard **AzureWave AW-CB375NF** (RTL8822CE) module's **Main** + **Aux** ports (MHF4 fit confirmed). The dev kit ships with **no WiFi antennas at all** (the u.FL ports are bare) → weak signal (‑76/‑91 dBm) and WiFi-only-boot DHCP failures; adding these took it to **‑34 dBm, 2×2 MIMO, ~866 Mbit/s** and fixed WiFi boot. |

## Existing infrastructure (already in place, not purchased for this)

- **Sonos speakers** — the music playback target, on the home LAN
- **Spotify account** — music source (played through Sonos)

## Key hardware constraints that drive the software design

- **8GB shared memory** is the hard limit. CPU and GPU draw from the same pool. whisper.cpp, llama-server, and TTS all run concurrently and compete for it — every framework dependency loaded into RAM is memory taken from inference. This is *the* reason we favor lean, native tooling over heavy Python frameworks.
- **M.2 slots**: primary is Key-M Type 2280 @ PCIe 3.0 x4 (the 990 PRO goes here); a second Key-M Type 2230 slot runs PCIe 3.0 x2.
- **No onboard eMMC** — the NVMe is the sole boot/primary drive. (The microSD was not used; everything runs from NVMe.)
- **Paw Key is a standard USB HID keyboard** — detected via `evdev` in Python, no GPIO wiring.
- **Peripheral power is offloaded to a powered USB hub**, not drawn from the Jetson. The board's `nvpmodel` budget (7/15/25 W — currently 15 W) is the *compute module* envelope and is **separate** from the carrier's 5 V USB rail; USB peripherals don't eat into it. The real constraint is per-port USB current (the Pebble V3 can spike to ~2 A at high volume). Routing the mic, speaker, and Paw Key through an externally-powered hub keeps that load off the Jetson and leaves headroom for 25 W MAXN mode later. For TTS-only confirmation volume the speaker draw is sub-1 W regardless.
- **Audio output path**: the Jetson has no analog 3.5 mm jack; TTS plays out over USB. Both the Pebble V3 (USB audio) and the ReSpeaker XVF3800 (which also presents a USB audio **output** + a 3.5 mm line-out) can serve as the sink.

## Rough memory budget (concurrent steady state)

| Consumer | Approx. usage |
|---|---|
| JetPack OS + system processes | ~0.8–1 GB |
| whisper.cpp + CUDA (base.en) | ~1–1.5 GB |
| llama-server + Qwen2.5 1.5B Q4_K_M | ~1.5–2 GB |
| Piper/Kokoro TTS | ~0.4–0.6 GB |
| Python app | the variable we keep small |

Leaves only ~2–3 GB of headroom — which is why the orchestration layer stays dependency-free.
