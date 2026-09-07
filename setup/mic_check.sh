#!/usr/bin/env bash
#
# mic_check.sh — record from the mic and report noise level + what whisper hears.
# Use it to diagnose interference, e.g. A/B test with and without the Pebble
# plugged in:  stay quiet during the recording to measure the noise floor.
#
#   setup/mic_check.sh [seconds]
#
# Reading the RMS:  ~< -55 dB = quiet/clean,  ~> -45 dB = noisy (hum/buzz).
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SECS="${1:-4}"
DEV="${MIC_DEVICE:-plughw:CARD=Array,DEV=0}"
WHISPER="$REPO/tools/whisper.cpp/build/bin/whisper-cli"
MODEL="$REPO/tools/whisper.cpp/models/ggml-base.en.bin"
WAV="$(mktemp --suffix=.wav)"
trap 'rm -f "$WAV"' EXIT

echo "Recording ${SECS}s from $DEV — stay quiet to measure the noise floor…"
arecord -D "$DEV" -f S16_LE -r 16000 -c 1 -d "$SECS" "$WAV" 2>/dev/null

echo "Signal:"
sox "$WAV" -n stats 2>&1 | grep -E "Pk lev dB|RMS lev dB|Crest factor" | sed 's/^/  /'

if [[ -x "$WHISPER" && -f "$MODEL" ]]; then
  echo "Whisper hears:"
  printf '  '
  "$WHISPER" -m "$MODEL" -f "$WAV" -nt -l en --no-prints 2>/dev/null
fi
echo "  ([BLANK_AUDIO] = clean silence; (buzzing)/garbled = electrical noise)"
