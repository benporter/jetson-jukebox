#!/usr/bin/env bash
#
# sonos_play.sh — play a song on Sonos by name, via Spotify.
#
# Resolves the query to a Spotify track id (Spotify Web API search), then plays
# it on the target room through node-sonos-http-api's working /spotify/now/
# endpoint. This deliberately bypasses the library's broken `musicsearch`
# (see docs/sonos-notes.md for why).
#
# Usage:
#   setup/sonos_play.sh "thunderstruck acdc"
#   setup/sonos_play.sh "let it go idina menzel" "Boys Room"
#   ROOM="Kids Room" setup/sonos_play.sh "baby shark"
#
# Env overrides:
#   ROOM         default room name (default: "Living Room")
#   API          node-sonos-http-api base URL (default: http://localhost:5005)
#   SETTINGS     path to node-sonos-http-api settings.json (for Spotify keys)
#   MARKET       Spotify market/country code (default: US)
#   VOLUME       volume (0-100) to set before play; "" leaves the room's volume
#                untouched (the default — playback maintains the current volume).
#                Set $JUKEBOX_DEFAULT_VOLUME to force a fixed starting volume.
#   TRACK_ID     play this Spotify track id directly, skipping search (the
#                pipeline passes this after resolving in Python); TRACK_LABEL
#                optionally sets the display name.
#
set -euo pipefail

QUERY="${1:-}"
ROOM="${2:-${ROOM:-Living Room}}"
API="${API:-http://localhost:5005}"
MARKET="${MARKET:-US}"
VOLUME="${VOLUME-${JUKEBOX_DEFAULT_VOLUME:-}}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETTINGS="${SETTINGS:-$SCRIPT_DIR/../tools/node-sonos-http-api/settings.json}"

TRACK_ID="${TRACK_ID:-}"
TRACK_LABEL="${TRACK_LABEL:-}"

if [[ -z "$QUERY" && -z "$TRACK_ID" ]]; then
  echo "usage: $0 \"song name [artist]\" [\"Room Name\"]   (or pass TRACK_ID=…)" >&2
  exit 2
fi

# Resolve the query to a track via the Python resolver — the single source of
# truth for Spotify search (handles the transient-503 retry, captures `explicit`).
# The pipeline resolves in Python and passes TRACK_ID/TRACK_LABEL to skip this,
# avoiding a duplicate search.
if [[ -z "$TRACK_ID" ]]; then
  if [[ ! -f "$SETTINGS" ]]; then
    echo "error: settings file not found: $SETTINGS" >&2
    echo "       (needs the Spotify clientId/clientSecret used by node-sonos-http-api)" >&2
    exit 1
  fi
  TRACK_JSON="$(SETTINGS="$SETTINGS" MARKET="$MARKET" \
    python3 "$SCRIPT_DIR/../src/spotify_resolve.py" "$QUERY")" || {
      echo "no Spotify match for: $QUERY" >&2; exit 1; }
  read -r TRACK_ID TRACK_LABEL < <(printf '%s' "$TRACK_JSON" | python3 -c '
import sys, json
t = json.load(sys.stdin)
print(t["id"], t["name"] + " - " + t["artist"])
')
fi

if [[ -z "${TRACK_ID:-}" ]]; then
  echo "no Spotify match for: ${QUERY:-<track id>}" >&2
  exit 1
fi
: "${TRACK_LABEL:=spotify:track:$TRACK_ID}"

# 3) Clear the existing queue first, then play the requested track.
#    /spotify/now inserts-and-skips into the current queue; clearing first
#    guarantees ONLY the requested song plays (no bleed into a prior queue).
#    Set KEEP_QUEUE=1 to skip clearing.
ROOM_ENC="$(python3 -c 'import sys,urllib.parse; print(urllib.parse.quote(sys.argv[1]))' "$ROOM")"
if [[ "${KEEP_QUEUE:-0}" != "1" ]]; then
  curl -s --max-time 15 "${API}/${ROOM_ENC}/clearqueue" >/dev/null || true
fi
# Set the default starting volume (unless VOLUME="" was passed to leave it alone),
# so every song starts at a known, kid-safe level rather than wherever it was left.
if [[ -n "$VOLUME" ]]; then
  curl -s --max-time 10 "${API}/${ROOM_ENC}/volume/${VOLUME}" >/dev/null || true
fi
# The Sonos /spotify/now play also 500s intermittently (Sonos/Spotify hiccup) —
# retry a few times before giving up.
RESP=""
for attempt in 1 2 3 4; do
  RESP="$(curl -s --max-time 25 "${API}/${ROOM_ENC}/spotify/now/spotify:track:${TRACK_ID}")" || RESP=""
  if echo "$RESP" | grep -q '"status":"success"'; then
    echo "▶ playing \"${TRACK_LABEL}\" (spotify:track:${TRACK_ID}) in ${ROOM}"
    exit 0
  fi
  echo "  sonos play failed (attempt $attempt) — retrying…" >&2
  sleep 1
done
echo "error: sonos play failed after retries: $RESP" >&2
exit 1
