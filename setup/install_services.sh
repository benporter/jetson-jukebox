#!/usr/bin/env bash
#
# install_services.sh — install/enable the whole jukebox boot stack.
#
# Idempotent. Installs every services/jukebox-*.service (+ jukebox.target),
# enables ALL of them, and starts the target. Re-run after adding a new unit —
# it auto-discovers and enables it, so new components can't slip past startup.
#
#   setup/install_services.sh
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$REPO/services"
DEST=/etc/systemd/system

echo "==> Migrating any old standalone units…"
# Superseded by jukebox-leds.service.
sudo systemctl disable --now respeaker-leds.service 2>/dev/null || true
sudo rm -f "$DEST/respeaker-leds.service"

echo "==> Installing units from $SRC …"
sudo install -m 0644 "$SRC/jukebox.target" "$DEST/"
for unit in "$SRC"/jukebox-*.service; do
  echo "    $(basename "$unit")"
  sudo install -m 0644 "$unit" "$DEST/"
done

sudo systemctl daemon-reload

echo "==> Enabling target + every jukebox service…"
sudo systemctl enable jukebox.target
for unit in "$DEST"/jukebox-*.service; do
  sudo systemctl enable "$(basename "$unit")"
done

echo "==> Starting jukebox.target now…"
sudo systemctl start jukebox.target

echo
echo "==> Status:"
systemctl --no-pager --type=service list-units 'jukebox-*' || true
echo
echo "Done. The stack now starts on boot. You should hear a meow once everything"
echo "is healthy. Check anytime with:  setup/jukebox_healthcheck.sh --status"
