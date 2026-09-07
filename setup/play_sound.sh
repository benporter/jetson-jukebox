#!/usr/bin/env bash
#
# play_sound.sh — play a WAV to the configured jukebox audio device.
#   play_sound.sh assets/ready_meow.wav
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
[[ -f "$REPO/config/jukebox.env" ]] && source "$REPO/config/jukebox.env"

SND="${1:?usage: play_sound.sh <wavfile>}"
DEV="${JUKEBOX_AUDIO_DEVICE:-default}"

[[ -f "$SND" ]] || { echo "sound file not found: $SND" >&2; exit 1; }
exec aplay -q -D "$DEV" "$SND"
