#!/usr/bin/env bash
#
# install_piper.sh — local neural TTS (Piper) for spoken feedback, e.g. the
# explicit-block message "<song> by <artist> can't be played". Downloads the
# aarch64 binary + one voice model into tools/piper/ (gitignored, like the other
# external tools). No sudo, idempotent.
#
#   setup/install_piper.sh [voice]      # default voice: en_US-lessac-medium
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIR="$REPO/tools/piper"
VOICE="${1:-en_US-lessac-medium}"
mkdir -p "$DIR/voices"

BIN_URL="https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_aarch64.tar.gz"
if [[ ! -x "$DIR/piper/piper" ]]; then
  echo "==> downloading piper aarch64 binary…"
  curl -fsSL "$BIN_URL" -o /tmp/piper.tgz
  tar -xzf /tmp/piper.tgz -C "$DIR"        # → $DIR/piper/{piper,libs,espeak-ng-data}
  rm -f /tmp/piper.tgz
fi

# Derive the HF path from the voice name, e.g.
#   en_US-lessac-medium      -> en/en_US/lessac/medium
#   en_GB-jenny_dioco-medium -> en/en_GB/jenny_dioco/medium
locale="${VOICE%%-*}"          # en_US / en_GB
rest="${VOICE#*-}"             # lessac-medium / jenny_dioco-medium
name="${rest%-*}"              # lessac / jenny_dioco
quality="${rest##*-}"          # medium
lang="${locale%%_*}"           # en
VPATH="$lang/$locale/$name/$quality"
BASE="https://huggingface.co/rhasspy/piper-voices/resolve/main/$VPATH/$VOICE"
for ext in onnx onnx.json; do
  if [[ ! -f "$DIR/voices/$VOICE.$ext" ]]; then
    echo "==> downloading voice $VOICE.$ext…"
    curl -fsSL "$BASE.$ext?download=true" -o "$DIR/voices/$VOICE.$ext"
  fi
done

echo "==> done. quick test:"
echo "  echo 'hello there' | '$DIR/piper/piper' -m '$DIR/voices/$VOICE.onnx' -f /tmp/piper_test.wav"