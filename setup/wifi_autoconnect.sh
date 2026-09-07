#!/usr/bin/env bash
#
# wifi_autoconnect.sh — make a WiFi network connect headlessly at boot.
#
# For an appliance with autologin (or no login), WiFi must come up before/without
# a desktop session. This creates ONE clean *system* connection for the SSID with:
#   * the password stored in the root-only system file (psk-flags=0), NOT the
#     per-user GNOME keyring (which only unlocks after login → password popups)
#   * connection.permissions "" → available system-wide
#   * autoconnect on
# and enables NetworkManager-wait-online so network-online.target actually waits
# for connectivity before the jukebox services start.
#
#   sudo setup/wifi_autoconnect.sh "<SSID>"
#
# The SSID can be passed as the first argument, or set as JUKEBOX_WIFI_SSID in the
# (gitignored) config/jukebox.env so it isn't hard-coded in the repo.
#
# Prompts for the password (hidden; never echoed, logged, or committed — it only
# lands in /etc/NetworkManager/system-connections/<SSID>.nmconnection, root-only).
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "Run with sudo:  sudo $0 \"<SSID>\"" >&2; exit 1; }

# SSID: arg 1, else JUKEBOX_WIFI_SSID from the local config/jukebox.env.
REPO="$(cd "$(dirname "$0")/.." && pwd)"
SSID="${1:-}"
if [[ -z "$SSID" && -f "$REPO/config/jukebox.env" ]]; then
  SSID="$(grep -E '^JUKEBOX_WIFI_SSID=' "$REPO/config/jukebox.env" | head -1 | cut -d= -f2- | tr -d '"'\''')"
fi
[[ -n "$SSID" ]] || { echo "usage: sudo $0 \"<SSID>\"  (or set JUKEBOX_WIFI_SSID in config/jukebox.env)" >&2; exit 1; }

read -rs -p "WiFi password for '$SSID': " PSK; echo
[[ -n "$PSK" ]] || { echo "empty password, aborting" >&2; exit 1; }

echo "==> Removing any existing profiles for SSID '$SSID'…"
while IFS=: read -r name type; do
  [[ "$type" == *wireless* ]] || continue
  s="$(nmcli -t -f 802-11-wireless.ssid connection show "$name" 2>/dev/null | cut -d: -f2)"
  if [[ "$s" == "$SSID" ]]; then
    echo "    deleting '$name'"
    nmcli connection delete "$name" >/dev/null || true
  fi
done < <(nmcli -t -f NAME,TYPE connection show)

echo "==> Creating clean system connection '$SSID'…"
nmcli connection add type wifi con-name "$SSID" ssid "$SSID" \
  wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$PSK" \
  connection.autoconnect yes >/dev/null
nmcli connection modify "$SSID" \
  802-11-wireless-security.psk-flags 0 \
  connection.permissions "" \
  connection.autoconnect-priority 10 \
  ipv6.method disabled >/dev/null
# ipv6.method disabled: this is an IPv4-only appliance. A fresh NM profile defaults
# to ipv6.method=auto, which SLAACs IPv6 ULA (fd23:…) addresses off the router RA;
# avahi then advertises AAAA records and macOS prefers IPv6, which breaks the
# .local hostname for SSH and the dashboard. See docs/runbook.md (IPv6 mDNS).
unset PSK

echo "==> Enabling NetworkManager-wait-online (services wait for real network)…"
systemctl enable NetworkManager-wait-online.service >/dev/null 2>&1 || true

echo "==> Done. Verify (you can unplug ethernet and reboot to truly test):"
echo "    nmcli connection up \"$SSID\"      # bring it up now"
echo "    nmcli -t -f NAME,TYPE,AUTOCONNECT,ACTIVE connection show"
