#!/usr/bin/env bash
#
# install_respeaker.sh — mic USB-access setup for the ReSpeaker XVF3800.
#   * udev rule: lets the voice app control the mic (LEDs) without root, and
#     re-runs jukebox-leds.service on (re)plug so the ring returns to idle.
#   * turns the LED ring off right now
#
# Boot-time "LEDs off" is owned by jukebox-leds.service (installed by
# setup/install_services.sh) — run that too for the full boot stack.
#
# Run once (it will prompt for your sudo password):
#   setup/install_respeaker.sh
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Installing udev rule (non-root USB access + LED reset on replug)…"
sudo install -m 0644 "$DIR/respeaker/99-respeaker-xvf3800.rules" \
  /etc/udev/rules.d/99-respeaker-xvf3800.rules
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=usb --attr-match=idVendor=2886

echo "==> Turning the LED ring off now…"
# The udev trigger above updated the device-node permissions, so no sudo needed here.
"$DIR/respeaker_led.sh" off

echo "==> Done. LED ring is off and the app can control it without sudo."
