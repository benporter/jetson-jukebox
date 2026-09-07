#!/usr/bin/env bash
#
# within_play_hours.sh — deterministic quiet-hours gate for the jukebox.
#
# Exit 0 if the current LOCAL system time is inside the allowed play window;
# exit 3 (and print the reason to stderr) if it's outside. No LLM, no guessing —
# just the system clock compared to a fixed range. The pipeline calls this before
# playing a song; outside the window the request is logged as 'blocked_time' and
# not played.
#
# Window (inclusive start, exclusive end), from config/jukebox.env or env:
#   JUKEBOX_PLAY_START  (default 05:00)  music allowed from here …
#   JUKEBOX_PLAY_END    (default 22:00)  … until here (10:00 PM)
#
# Usage:
#   setup/within_play_hours.sh            # checks the real clock now
#   setup/within_play_hours.sh 23:15      # test against a specific HH:MM
#   echo $?                               # 0 = allowed, 3 = blocked
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/../config/jukebox.env"

# Precedence: an already-set environment variable wins (the daemon provides these
# via systemd EnvironmentFile); fall back to config/jukebox.env for standalone CLI
# use; finally hardcoded defaults. We read just our two keys from the file so
# sourcing it can't clobber a caller-provided override.
START="${JUKEBOX_PLAY_START:-}"
END="${JUKEBOX_PLAY_END:-}"
if [[ -f "$ENV_FILE" ]]; then
  read_key() { grep -E "^$1=" "$ENV_FILE" | tail -1 | cut -d= -f2- | tr -d '"'; }
  START="${START:-$(read_key JUKEBOX_PLAY_START)}"
  END="${END:-$(read_key JUKEBOX_PLAY_END)}"
fi
START="${START:-05:00}"
END="${END:-22:00}"
NOW="${1:-$(date +%H:%M)}"

# HH:MM -> minutes since midnight (10# forces base-10 so "08"/"09" don't error).
to_min() { local h="${1%%:*}" m="${1##*:}"; echo $(( 10#$h * 60 + 10#$m )); }
n="$(to_min "$NOW")"; s="$(to_min "$START")"; e="$(to_min "$END")"

if (( s <= e )); then
  (( n >= s && n < e )) && ok=1 || ok=0          # same-day window
else
  (( n >= s || n < e )) && ok=1 || ok=0          # window wraps midnight
fi

if (( ok )); then
  exit 0
fi
echo "outside play hours ${START}-${END} (now ${NOW})" >&2
exit 3
