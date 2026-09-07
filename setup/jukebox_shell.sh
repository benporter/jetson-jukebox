# Jetson Jukebox — interactive shell setup (alias + SSH welcome banner).
# Sourced from ~/.bashrc. Lives in the repo so it's version-controlled.
# Edit here, not in ~/.bashrc.

# ── Aliases ────────────────────────────────────────────────────────────────
# rjp = "restart jukebox pawkey": reload the paw-key daemon so edits to src/ or
# config/ take effect (the daemon imports the pipeline once at startup).
alias rjp='sudo systemctl restart jukebox-pawkey'

# rjs = "restart jukebox sonos": restart the Sonos bridge so it re-discovers and
# re-reads favorites/zones (e.g. after adding a Sonos favorite).
alias rjs='sudo systemctl restart jukebox-sonos'

# rjd = "restart jukebox dashboard": reload the web dashboard after editing
# src/dashboard/ or dashboard config (e.g. the table row limit).
alias rjd='sudo systemctl restart jukebox-dashboard'

# cc = "continue Claude": jump to /home and resume the Claude Code session.
alias cc='cd /home && claude --continue'

# ── SSH welcome banner ───────────────────────────────────────────────────────
# Print once per interactive SSH login (not on every subshell).
_jukebox_welcome() {
    case $- in *i*) ;; *) return ;; esac        # interactive shells only
    [ -n "$SSH_CONNECTION" ] || return            # SSH logins only
    [ -n "$JUKEBOX_MOTD_SHOWN" ] && return        # once per session
    export JUKEBOX_MOTD_SHOWN=1

    local e=$'\033'
    local b="${e}[1m" c="${e}[36m" g="${e}[32m" y="${e}[33m" d="${e}[2m" r="${e}[0m"

    # Dashboard URL: mDNS hostname (jetson-orin-nano.local) + configured port.
    # Using the .local name instead of the IP keeps the link valid even if DHCP
    # hands the box a new address. Wrapped in an OSC 8 hyperlink so it's
    # click-to-open in modern terminals (and still readable as plain text where
    # that's unsupported).
    local host ip port url link ipurl iplink
    host="$(hostname 2>/dev/null).local"
    ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
    port="$(grep -E '^JUKEBOX_DASH_PORT' /home/jetson/development/config/jukebox.env 2>/dev/null | cut -d= -f2 | tr -d ' "')"
    url="http://${host}:${port:-8088}/"
    ipurl="http://${ip:-127.0.0.1}:${port:-8088}/"
    link="${e}]8;;${url}${e}\\${g}${url}${e}]8;;${e}\\${r}"
    iplink="${e}]8;;${ipurl}${e}\\${g}${ipurl}${e}]8;;${e}\\${r}"

    cat <<EOF

${c}${b}  🐱 Jetson Jukebox${r}  ${d}— screenless voice jukebox for kids${r}

  ${b}Continue the Claude Code session:${r}
      ${g}cd /home && claude --continue${r}   ${d}(or just: ${y}cc${d})${r}

  ${b}Git project:${r}
      ${g}/home/jetson/development${r}

  ${b}Dashboard${r} ${d}(requests played / failed / blocked, disk health):${r}
      ${link}   ${d}(hostname)${r}
      ${iplink}   ${d}(IP — use if .local doesn't resolve)${r}

  ${b}Aliases:${r}
      ${y}cc${r}   →  ${g}cd /home && claude --continue${r}
           ${d}Resume the Claude Code session.${r}
      ${y}rjp${r}  →  ${g}sudo systemctl restart jukebox-pawkey${r}
           ${d}Reload the paw-key daemon after editing src/ or config/ (it loads${r}
           ${d}the pipeline once at startup, so changes aren't live until restart).${r}
      ${y}rjs${r}  →  ${g}sudo systemctl restart jukebox-sonos${r}
           ${d}Restart the Sonos bridge to re-read favorites/zones.${r}
      ${y}rjd${r}  →  ${g}sudo systemctl restart jukebox-dashboard${r}
           ${d}Reload the web dashboard after editing src/dashboard/ or its config.${r}

EOF
}
_jukebox_welcome
