#!/usr/bin/env bash
#
# sonos_server.sh — launch node-sonos-http-api (Sonos/Spotify control on :5005).
# Resolves the nvm-installed node automatically so it works from systemd.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_DIR="$REPO/tools/node-sonos-http-api"

# Pick the newest node installed under nvm (no need to source nvm.sh).
NODE_BIN="$(ls -d "$HOME"/.nvm/versions/node/*/bin 2>/dev/null | sort -V | tail -1)"
[[ -n "$NODE_BIN" ]] && export PATH="$NODE_BIN:$PATH"

command -v node >/dev/null || { echo "node not found (nvm install --lts)" >&2; exit 1; }
[[ -f "$API_DIR/server.js" ]] || { echo "node-sonos-http-api not present (see setup/README.md)" >&2; exit 1; }

cd "$API_DIR"
exec node server.js
