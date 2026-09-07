#!/usr/bin/env bash
#
# respeaker_led.sh — set the ReSpeaker XVF3800 LED ring effect mode.
#
# Modes:  off | breath | rainbow | single | doa   (or a raw integer 0-4)
#   0=off  1=breath  2=rainbow  3=single-color  4=doa (default direction-of-arrival)
#
# Usage:
#   setup/respeaker_led.sh off
#   setup/respeaker_led.sh doa
#
# Requires USB access to the mic (install the udev rule via setup/install_respeaker.sh).
set -euo pipefail

MODE="${1:-off}"
case "$MODE" in
  off)     VAL=0 ;;
  breath)  VAL=1 ;;
  rainbow) VAL=2 ;;
  single)  VAL=3 ;;
  doa)     VAL=4 ;;
  [0-4])   VAL="$MODE" ;;
  *) echo "usage: $0 {off|breath|rainbow|single|doa|0-4}" >&2; exit 2 ;;
esac

HOST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../tools/reSpeaker_XVF3800_USB_4MIC_ARRAY/host_control/jetson" 2>/dev/null && pwd || true)"
if [[ -z "$HOST_DIR" || ! -x "$HOST_DIR/xvf_host" ]]; then
  echo "error: xvf_host (jetson build) not found. Recreate the clone per setup/README.md." >&2
  exit 1
fi

exec env LD_LIBRARY_PATH="$HOST_DIR" "$HOST_DIR/xvf_host" led_effect "$VAL"
