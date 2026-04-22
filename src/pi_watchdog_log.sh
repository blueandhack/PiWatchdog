#!/usr/bin/env bash
set -euo pipefail

LOG_PATH="${PI_WATCHDOG_LOG_PATH:-/var/log/pi-watchdog.log}"
HOSTNAME_FQ="${HOSTNAME:-$(hostname)}"
NOW="$(date --iso-8601=seconds)"

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
  ping -c 1 -W 2 "${gw}" 2>&1
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

  out
} >> "${LOG_PATH}"
