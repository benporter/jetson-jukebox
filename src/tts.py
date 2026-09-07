#!/usr/bin/env python3
"""
tts.py — local neural TTS (Piper) for spoken feedback.

First use: when a song is refused for explicit lyrics, speak the **retrieved**
song + artist on the local Pebble. STT/intent often mishear, so reading back what
was actually found bridges the disconnect ("oh, that's not what I asked for").

Uses the standalone Piper aarch64 binary under tools/piper/ (setup/install_piper.sh).
Synthesizes to a WAV cached by text+voice (so repeats are instant), which the
caller plays locally. Best-effort: returns None if Piper isn't installed or synth
fails — callers fall back to the static blocked sound, so blocking still works.
"""
import hashlib
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _cfg_path(env: str, default: Path) -> Path:
    """Path from env (repo-relative or absolute), else default."""
    val = os.environ.get(env)
    if not val:
        return Path(default)
    p = Path(val)
    return p if p.is_absolute() else (REPO / p)


PIPER_BIN = _cfg_path("JUKEBOX_PIPER_BIN", REPO / "tools/piper/piper/piper")
PIPER_VOICE = _cfg_path("JUKEBOX_PIPER_VOICE",
                        REPO / "tools/piper/voices/en_US-lessac-medium.onnx")
CACHE = Path(os.environ.get("JUKEBOX_TTS_CACHE", REPO / "data/tts-cache"))


def available() -> bool:
    return PIPER_BIN.exists() and PIPER_VOICE.exists()


def speak_to_wav(text: str) -> str | None:
    """Synthesize `text` to a (cached) WAV; return its path, or None on failure."""
    text = (text or "").strip()
    if not text:
        return None
    if not available():
        print("(tts: piper not installed — run setup/install_piper.sh)",
              file=sys.stderr)
        return None
    CACHE.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(f"{PIPER_VOICE.name}:{text}".encode()).hexdigest()[:16]
    out = CACHE / f"{key}.wav"
    if out.exists():
        return str(out)
    try:
        subprocess.run(
            [str(PIPER_BIN), "-m", str(PIPER_VOICE), "-f", str(out)],
            input=text.encode(), check=True, timeout=30,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return str(out) if out.exists() else None
    except Exception as e:
        print(f"(tts synth failed: {e})", file=sys.stderr)
        return None


if __name__ == "__main__":
    msg = " ".join(sys.argv[1:]) or "Sorry, that song isn't allowed."
    w = speak_to_wav(msg)
    print(w or "TTS unavailable", file=sys.stderr if not w else sys.stdout)
    sys.exit(0 if w else 1)
