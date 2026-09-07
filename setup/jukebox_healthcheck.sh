#!/usr/bin/env bash
#
# jukebox_healthcheck.sh — probe every long-running component.
#
# THIS IS THE SINGLE SOURCE OF TRUTH for "what must be healthy". When you add a
# new persistent server, add ONE line to COMPONENTS below (and a matching
# systemd unit in services/ — see services/README.md). The readiness/meow gate
# and `--status` reporting then cover it automatically.
#
# Usage:
#   jukebox_healthcheck.sh           # exit 0 iff all healthy (quiet-ish)
#   jukebox_healthcheck.sh --status  # human-readable table
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
[[ -f "$REPO/config/jukebox.env" ]] && source "$REPO/config/jukebox.env"

# name|kind|target   (add a line per component)
#   kind=url  → HTTP 2xx from target;   kind=unit → systemd unit is active
COMPONENTS=(
  "sonos|url|http://127.0.0.1:${SONOS_PORT:-5005}/zones"
  "llm|url|http://127.0.0.1:${LLAMA_PORT:-8080}/health"
  "pawkey|unit|jukebox-pawkey.service"
  "dashboard|url|http://127.0.0.1:${JUKEBOX_DASH_PORT:-8088}/healthz"
)

status_mode=0
[[ "${1:-}" == "--status" ]] && status_mode=1

probe() {  # kind target -> 0 if healthy
  case "$1" in
    url)  curl -fsS --max-time 3 "$2" >/dev/null 2>&1 ;;
    unit) systemctl is-active --quiet "$2" ;;
    *)    return 1 ;;
  esac
}

rc=0
for entry in "${COMPONENTS[@]}"; do
  IFS='|' read -r name kind target <<<"$entry"
  if probe "$kind" "$target"; then
    (( status_mode )) && printf "  \033[32m[ok]\033[0m    %-8s %s\n" "$name" "$target"
  else
    rc=1
    (( status_mode )) && printf "  \033[31m[DOWN]\033[0m  %-8s %s\n" "$name" "$target"
  fi
done

(( status_mode )) && { (( rc == 0 )) && echo "all components healthy" || echo "some components DOWN"; }
exit $rc
