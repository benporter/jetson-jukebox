#!/usr/bin/env python3
"""
listen_and_play.py — fixed-window voice tester.

Records a fixed number of seconds from the mic, then runs the shared pipeline
(transcribe → intent → Sonos action: play / pause / resume / volume). The Paw
Key push-to-talk daemon (pawkey_listen.py) is the normal trigger; this stays as
a handy manual test.

Usage:
    src/listen_and_play.py                 # 5s, Living Room
    src/listen_and_play.py --seconds 6 --room "Boys Room"
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pipeline  # noqa: E402

MIC_DEVICE = "plughw:CARD=Array,DEV=0"


def record(path: Path, seconds: int) -> None:
    print(f"\N{STUDIO MICROPHONE} listening for {seconds}s … (speak your request)")
    subprocess.run(
        ["arecord", "-D", MIC_DEVICE, "-f", "S16_LE", "-r", "16000",
         "-c", "1", "-d", str(seconds), str(path)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=int, default=5, help="record duration")
    ap.add_argument("--room", default="Living Room", help="Sonos room name")
    args = ap.parse_args()

    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "request.wav"
        pipeline.set_led("breath")          # listening
        try:
            record(wav, args.seconds)
        finally:
            pipeline.set_led("off")         # done listening
        return pipeline.process_wav(wav, args.room, source="cli")


if __name__ == "__main__":
    raise SystemExit(main())
