#!/usr/bin/env bash
#
# jukebox_ready.sh — wait until all components are healthy, then meow.
#
# Run by jukebox-ready.service at boot. Polls the health check (which knows
# every component) and plays the readiness sound once everything is up, so an
# audible "meow" means the whole system is initialized and ready.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
[[ -f "$REPO/config/jukebox.env" ]] && source "$REPO/config/jukebox.env"

HEALTH="$REPO/setup/jukebox_healthcheck.sh"
MEOW="$REPO/${JUKEBOX_READY_SOUND:-assets/mixkit-sweet-kitty-meow-93.wav}"
TIMEOUT="${JUKEBOX_READY_TIMEOUT:-120}"   # seconds

echo "jukebox-ready: waiting up to ${TIMEOUT}s for all components…"
start=$SECONDS
until "$HEALTH" >/dev/null 2>&1; do
  if (( SECONDS - start > TIMEOUT )); then
    echo "jukebox-ready: timeout — some components still down; meowing anyway" >&2
    "$HEALTH" --status || true
    break
  fi
  sleep 2
done

echo "jukebox-ready: components up — playing readiness meow"
# At boot the desktop sound server (PulseAudio) briefly holds the USB audio
# device during its own init, so exclusive aplay can fail with "Device or
# resource busy". Retry until it frees up (Pulse suspends idle PCMs within a
# few seconds), rather than giving up after one try.
meowed=false
for attempt in $(seq 1 20); do
  if "$REPO/setup/play_sound.sh" "$MEOW" 2>/dev/null; then
    meowed=true
    echo "jukebox-ready: meowed (attempt $attempt)"
    break
  fi
  sleep 2
done
$meowed || echo "jukebox-ready: meow failed after retries (check JUKEBOX_AUDIO_DEVICE / sound server)" >&2
echo "jukebox-ready: READY"
