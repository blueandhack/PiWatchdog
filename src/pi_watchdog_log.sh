#!/usr/bin/env bash
set -euo pipefail

LOG_PATH="${PI_WATCHDOG_LOG_PATH:-/var/log/pi-watchdog.log}"
HOSTNAME_FQ="${HOSTNAME:-$(hostname)}"
NOW="$(date --iso-8601=seconds)"
WIFI_RECOVERY="${PI_WATCHDOG_WIFI_RECOVERY:-0}"
WIFI_DEVICE="${PI_WATCHDOG_WIFI_DEVICE:-wlan0}"
WIFI_CONNECTION="${PI_WATCHDOG_WIFI_CONNECTION:-}"
WIFI_FAILURE_THRESHOLD="${PI_WATCHDOG_WIFI_FAILURE_THRESHOLD:-2}"
WIFI_RECOVERY_COOLDOWN_SECONDS="${PI_WATCHDOG_WIFI_RECOVERY_COOLDOWN_SECONDS:-600}"
WIFI_REBOOT="${PI_WATCHDOG_WIFI_REBOOT:-0}"
WIFI_REBOOT_AFTER_RECOVERIES="${PI_WATCHDOG_WIFI_REBOOT_AFTER_RECOVERIES:-3}"
WIFI_REBOOT_COOLDOWN_SECONDS="${PI_WATCHDOG_WIFI_REBOOT_COOLDOWN_SECONDS:-21600}"
STATE_DIR="${PI_WATCHDOG_STATE_DIR:-/run/pi-watchdog}"

PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

out() {
  printf '%s\n' "$*"
}

section() {
  out "-- $1 --"
}

run_or_true() {
  "$@" 2>&1 || true
}

has_cmd() {
  command -v "$1" >/dev/null 2>&1
}

gateway_ip() {
  ip route show default 2>/dev/null | awk '/default/ {print $3; exit}'
}

wifi_summary() {
  if has_cmd nmcli; then
    nmcli -t -f DEVICE,TYPE,STATE,CONNECTION device 2>/dev/null || true
  else
    out "nmcli not available"
  fi
}

docker_summary() {
  if has_cmd docker; then
    docker ps --format 'table {{.Names}}\t{{.Status}}' 2>/dev/null || true
  else
    out "docker not available"
  fi
}

temp_summary() {
  local found=0
  local tz
  for tz in /sys/class/thermal/thermal_zone*/temp; do
    [[ -f "${tz}" ]] || continue
    found=1
    out "${tz}=$(cat "${tz}")"
  done
  if [[ "${found}" -eq 0 ]]; then
    out "no thermal zones found"
  fi
}

dns_check() {
  local ok=0
  local host
  for host in changelogs.ubuntu.com google.com; do
    if getent ahosts "${host}" 2>/dev/null; then
      ok=1
    fi
  done
  return $(( ok == 1 ? 0 : 1 ))
}

ping_check() {
  local gw
  gw="$(gateway_ip)"
  if [[ -z "${gw}" ]]; then
    out "no default gateway found"
    return 1
  fi
  ping -c 5 -W 2 "${gw}" 2>&1
}

recent_brcmf_timeouts() {
  has_cmd journalctl || return 1
  journalctl -k --since "10 minutes ago" --no-pager 2>/dev/null \
    | grep -Eiq 'brcmf.*(status -110|err=-110|timed out|timeout)'
}

state_value() {
  local name="$1"
  local path="${STATE_DIR}/${name}"
  [[ -f "${path}" ]] || { printf '0\n'; return; }
  cat "${path}" 2>/dev/null || printf '0\n'
}

write_state() {
  local name="$1"
  local value="$2"
  mkdir -p "${STATE_DIR}" 2>/dev/null || return 0
  printf '%s\n' "${value}" > "${STATE_DIR}/${name}" 2>/dev/null || true
}

reset_wifi_failure_state() {
  write_state "wifi-failures" "0"
  write_state "wifi-recoveries" "0"
}

wifi_connection_name() {
  if [[ -n "${WIFI_CONNECTION}" ]]; then
    printf '%s\n' "${WIFI_CONNECTION}"
    return 0
  fi
  has_cmd nmcli || return 1
  nmcli -t -f NAME,TYPE,AUTOCONNECT connection show 2>/dev/null \
    | awk -F: '$2 == "802-11-wireless" && $3 == "yes" {print $1; exit}'
}

network_healthy_quick() {
  local gw
  gw="$(gateway_ip)"
  [[ -n "${gw}" ]] || return 1
  ping -c 1 -W 2 "${gw}" >/dev/null 2>&1
}

maybe_reboot_for_wifi() {
  local recoveries="$1"
  local now="$2"
  local last_reboot elapsed

  [[ "${WIFI_REBOOT}" == "1" ]] || return 0
  if (( recoveries < WIFI_REBOOT_AFTER_RECOVERIES )); then
    out "reboot=waiting for ${WIFI_REBOOT_AFTER_RECOVERIES} recovery attempts"
    return 0
  fi

  last_reboot="$(state_value "wifi-last-reboot")"
  [[ "${last_reboot}" =~ ^[0-9]+$ ]] || last_reboot=0
  elapsed=$((now - last_reboot))
  if (( elapsed < WIFI_REBOOT_COOLDOWN_SECONDS )); then
    out "reboot=cooldown ${elapsed}/${WIFI_REBOOT_COOLDOWN_SECONDS}s"
    return 0
  fi

  write_state "wifi-last-reboot" "${now}"
  out "reboot=systemctl reboot"
  out "reboot_reason=persistent brcmfmac timeout after ${recoveries} recovery attempts"
  sync
  systemctl reboot
}

maybe_recover_wifi() {
  local ping_output="$1"
  local dns_output="$2"
  local failed=0
  local failures recoveries last_recovery now elapsed connection_name

  [[ "${WIFI_RECOVERY}" == "1" ]] || return 0
  if ! grep -q '0% packet loss' <<<"${ping_output}" || ! grep -q 'google.com' <<<"${dns_output}"; then
    failed=1
  fi
  [[ "${failed}" -eq 1 ]] || { reset_wifi_failure_state; return 0; }
  recent_brcmf_timeouts || return 0

  failures="$(state_value "wifi-failures")"
  [[ "${failures}" =~ ^[0-9]+$ ]] || failures=0
  failures=$((failures + 1))
  write_state "wifi-failures" "${failures}"

  section "wifi recovery"
  out "failure_count=${failures}"
  out "reason=network failure with recent brcmfmac timeout"

  if (( failures < WIFI_FAILURE_THRESHOLD )); then
    out "action=waiting for threshold ${WIFI_FAILURE_THRESHOLD}"
    return 0
  fi

  now="$(date +%s)"
  last_recovery="$(state_value "wifi-last-recovery")"
  [[ "${last_recovery}" =~ ^[0-9]+$ ]] || last_recovery=0
  elapsed=$((now - last_recovery))
  if (( elapsed < WIFI_RECOVERY_COOLDOWN_SECONDS )); then
    out "action=cooldown ${elapsed}/${WIFI_RECOVERY_COOLDOWN_SECONDS}s"
    return 0
  fi

  write_state "wifi-last-recovery" "${now}"
  write_state "wifi-failures" "0"
  recoveries="$(state_value "wifi-recoveries")"
  [[ "${recoveries}" =~ ^[0-9]+$ ]] || recoveries=0
  recoveries=$((recoveries + 1))
  write_state "wifi-recoveries" "${recoveries}"
  out "recovery_attempts=${recoveries}"

  if has_cmd nmcli; then
    connection_name="$(wifi_connection_name || true)"
    out "action=nmcli radio wifi off/on"
    if [[ -n "${connection_name}" ]]; then
      out "connection=${connection_name}"
    fi
    run_or_true nmcli radio wifi off
    sleep 5
    run_or_true nmcli radio wifi on
    sleep 5
    if [[ -n "${connection_name}" ]]; then
      run_or_true nmcli connection up "${connection_name}" ifname "${WIFI_DEVICE}"
    else
      run_or_true nmcli device wifi rescan ifname "${WIFI_DEVICE}"
      run_or_true nmcli device connect "${WIFI_DEVICE}"
    fi
    run_or_true iw dev "${WIFI_DEVICE}" set power_save off
  else
    out "action=ip link bounce ${WIFI_DEVICE}"
    run_or_true ip link set "${WIFI_DEVICE}" down
    sleep 5
    run_or_true ip link set "${WIFI_DEVICE}" up
  fi

  if network_healthy_quick; then
    out "recovery_result=network healthy"
    reset_wifi_failure_state
  else
    out "recovery_result=network still unhealthy"
    maybe_reboot_for_wifi "${recoveries}" "${now}"
  fi
}

emit_failure_diagnostics() {
  local gw
  gw="$(gateway_ip)"

  section "failure diagnostics"

  section "resolvectl status"
  if has_cmd resolvectl; then
    run_or_true resolvectl status
  else
    out "resolvectl not available"
  fi

  section "nmcli general status"
  if has_cmd nmcli; then
    run_or_true nmcli general status
  else
    out "nmcli not available"
  fi

  section "nmcli device show wlan0"
  if has_cmd nmcli; then
    run_or_true nmcli device show wlan0
  else
    out "nmcli not available"
  fi

  section "ip -s link show wlan0"
  run_or_true ip -s link show wlan0

  section "gateway neighbor"
  if [[ -n "${gw}" ]]; then
    run_or_true ip neigh show "${gw}"
  else
    out "no default gateway found"
  fi

  section "recent network journals"
  if has_cmd journalctl; then
    run_or_true journalctl -u NetworkManager -u wpa_supplicant -u systemd-resolved -u dhcpcd -n 80 --no-pager
  else
    out "journalctl not available"
  fi

  section "recent kernel network warnings"
  if has_cmd journalctl; then
    run_or_true journalctl -k -n 80 --no-pager
  else
    out "journalctl not available"
  fi
}

{
  out "=== ${NOW} ${HOSTNAME_FQ} ==="

  section "uptime"
  run_or_true uptime

  section "loadavg"
  run_or_true cat /proc/loadavg

  section "memory"
  run_or_true free -h

  section "filesystem"
  run_or_true df -h /

  section "interfaces"
  run_or_true ip -brief address

  section "routes"
  run_or_true ip route

  section "wifi"
  wifi_summary

  section "sockets"
  run_or_true ss -s

  section "docker"
  docker_summary

  section "temperature"
  temp_summary

  section "ping gateway"
  ping_output="$(ping_check || true)"
  out "${ping_output}"

  section "dns"
  dns_output="$(dns_check 2>&1 || true)"
  out "${dns_output}"

  section "recent kernel warnings"
  if has_cmd journalctl; then
    run_or_true journalctl -k -p warning -n 40 --no-pager
  else
    out "journalctl not available"
  fi

  if ! grep -q '0% packet loss' <<<"${ping_output}" || ! grep -q 'google.com' <<<"${dns_output}"; then
    emit_failure_diagnostics
  fi

  maybe_recover_wifi "${ping_output}" "${dns_output}"

  out
} >> "${LOG_PATH}"
