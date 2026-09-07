#!/usr/bin/env python3
"""
pawkey_listen.py — push-to-talk daemon for the Keychron "Big Kitty" Paw Key.

Hold the paw → it records (ring lit) for the whole press; release → it
transcribes and acts (play / pause / resume / volume) via the shared pipeline.

Reads the input device directly (struct-parses /dev/input/event*), so it needs
no extra Python packages — but it needs read access to /dev/input (run as a
service with SupplementaryGroups=input, or `sudo` for manual testing).

    src/pawkey_listen.py              # run the daemon (needs input access)
    src/pawkey_listen.py --monitor    # just print key events (identify the button)
"""
import argparse
import fcntl
import os
import select
import signal
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pipeline  # noqa: E402

MIC_DEVICE = os.environ.get("JUKEBOX_MIC_DEVICE", "plughw:CARD=Array,DEV=0")
ROOM = os.environ.get("JUKEBOX_ROOM", "Living Room")
DEVICE_NAME_MATCH = "Paw Launcher"     # matches the Keychron paw's input devices
MAX_RECORD_SECONDS = 30                # safety cap if a key sticks
MIN_RECORD_SECONDS = 0.3               # shorter press = treat as a mis-tap

# struct input_event on 64-bit: long sec, long usec, u16 type, u16 code, s32 value
_EV_FMT = "llHHi"
_EV_SIZE = struct.calcsize(_EV_FMT)
EV_KEY = 0x01


def _iow(t, nr, size):
    return (1 << 30) | (size << 16) | (ord(t) << 8) | nr


# EVIOCGRAB: claim the device exclusively so its keystrokes go ONLY to us
# (otherwise the paw's "Enter" leaks to the focused terminal/desktop).
EVIOCGRAB = _iow("E", 0x90, 4)


def find_paw_event_devices() -> list[str]:
    """Return /dev/input/eventN paths for the paw key (matched by device name)."""
    paths, name = [], ""
    try:
        info = Path("/proc/bus/input/devices").read_text()
    except OSError:
        return paths
    for line in info.splitlines():
        if line.startswith("N: Name="):
            name = line
        elif line.startswith("H: Handlers=") and DEVICE_NAME_MATCH in name:
            for tok in line.split("=", 1)[1].split():
                if tok.startswith("event"):
                    paths.append(f"/dev/input/{tok}")
    return paths


def open_devices(paths: list[str], grab: bool = False) -> dict:
    fds = {}
    for p in paths:
        try:
            fd = os.open(p, os.O_RDONLY | os.O_NONBLOCK)
            if grab:
                try:
                    fcntl.ioctl(fd, EVIOCGRAB, 1)   # exclusive — no leak to terminal
                except OSError as e:
                    print(f"  warning: could not grab {p}: {e}", file=sys.stderr)
            fds[fd] = p
        except OSError as e:
            print(f"  cannot open {p}: {e}", file=sys.stderr)
    return fds


class Recorder:
    def __init__(self, room: str):
        self.room = room
        self.proc = None
        self.tmp = None
        self.wav = None
        self.start = 0.0

    def start_recording(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.wav = Path(self.tmp.name) / "request.wav"
        self.start = time.monotonic()
        pipeline.set_led("breath")
        print("\N{PAW PRINTS} listening… (hold the paw)")
        self.proc = subprocess.Popen(
            ["arecord", "-D", MIC_DEVICE, "-f", "S16_LE", "-r", "16000",
             "-c", "1", "-d", str(MAX_RECORD_SECONDS), str(self.wav)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    def stop_and_process(self):
        if self.proc is None:
            return
        held = time.monotonic() - self.start
        self.proc.send_signal(signal.SIGINT)   # let arecord finalize the WAV
        try:
            self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        pipeline.set_led("off")
        proc_wav, tmp = self.wav, self.tmp
        self.proc = self.wav = self.tmp = None
        if held < MIN_RECORD_SECONDS:
            print("(too quick — hold the paw down while you talk)")
        else:
            try:
                pipeline.process_wav(proc_wav, self.room,
                                     source="pawkey", held_seconds=held)
            except Exception as e:                       # never crash the daemon
                print(f"pipeline error: {e}", file=sys.stderr)
        tmp.cleanup()


def run(room: str):
    paths = find_paw_event_devices()
    if not paths:
        print(f"No '{DEVICE_NAME_MATCH}' input device found — is the Paw Key plugged in?",
              file=sys.stderr)
        return 1
    print(f"Paw Key on: {', '.join(paths)}  → room: {room!r}")
    fds = open_devices(paths, grab=True)   # capture the paw so Enter doesn't leak
    if not fds:
        print("No input devices opened (need read access to /dev/input — run as the "
              "jukebox-pawkey service or with sudo).", file=sys.stderr)
        return 1

    rec = Recorder(room)
    pressed: set[tuple[int, int]] = set()      # (fd, keycode) currently down
    print("Ready. Hold the paw to talk. (Ctrl-C to quit.)")
    while True:
        r, _, _ = select.select(list(fds), [], [])
        for fd in r:
            try:
                data = os.read(fd, _EV_SIZE * 64)
            except OSError:
                continue
            for off in range(0, len(data) - _EV_SIZE + 1, _EV_SIZE):
                _, _, etype, code, value = struct.unpack(
                    _EV_FMT, data[off:off + _EV_SIZE])
                if etype != EV_KEY:
                    continue
                was_empty = not pressed
                if value == 1:
                    pressed.add((fd, code))
                elif value == 0:
                    pressed.discard((fd, code))
                # value == 2 (autorepeat) ignored
                if was_empty and pressed:
                    rec.start_recording()
                elif not pressed and not was_empty:
                    rec.stop_and_process()


def monitor():
    paths = find_paw_event_devices()
    print(f"watching: {paths or '(none found)'}  — press the paw; Ctrl-C to stop")
    fds = open_devices(paths)
    if not fds:
        return 1
    while True:
        r, _, _ = select.select(list(fds), [], [])
        for fd in r:
            data = os.read(fd, _EV_SIZE * 64)
            for off in range(0, len(data) - _EV_SIZE + 1, _EV_SIZE):
                _, _, etype, code, value = struct.unpack(
                    _EV_FMT, data[off:off + _EV_SIZE])
                if etype == EV_KEY:
                    state = {1: "DOWN", 0: "UP", 2: "repeat"}.get(value, value)
                    print(f"  {fds[fd].split('/')[-1]}  code={code}  {state}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--room", default=ROOM, help="Sonos room name")
    ap.add_argument("--monitor", action="store_true", help="print key events only")
    args = ap.parse_args()
    try:
        return monitor() if args.monitor else run(args.room)
    except KeyboardInterrupt:
        print("\nbye")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
