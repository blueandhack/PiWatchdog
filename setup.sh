#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PI_WATCHDOG_USER="${PI_WATCHDOG_USER:-${SUDO_USER:-$(id -un)}}"
PI_WATCHDOG_PORT="${PI_WATCHDOG_PORT:-8098}"
PI_WATCHDOG_INSTALL_DIR="${PI_WATCHDOG_INSTALL_DIR:-/opt/pi-watchdog}"
PI_WATCHDOG_LOG_PATH="${PI_WATCHDOG_LOG_PATH:-/var/log/pi-watchdog.log}"

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    echo "Run with sudo."
    exit 1
  fi
}

render_template() {
  local src="$1"
  local dst="$2"
  sed \
    -e "s|@PI_WATCHDOG_USER@|${PI_WATCHDOG_USER}|g" \
    -e "s|@PI_WATCHDOG_PORT@|${PI_WATCHDOG_PORT}|g" \
    -e "s|@PI_WATCHDOG_INSTALL_DIR@|${PI_WATCHDOG_INSTALL_DIR}|g" \
    -e "s|@PI_WATCHDOG_LOG_PATH@|${PI_WATCHDOG_LOG_PATH}|g" \
    "$src" > "$dst"
}

require_root

echo "Installing PiWatchdog"
echo "  user: ${PI_WATCHDOG_USER}"
echo "  port: ${PI_WATCHDOG_PORT}"
echo "  install dir: ${PI_WATCHDOG_INSTALL_DIR}"
echo "  log path: ${PI_WATCHDOG_LOG_PATH}"

install -d -m 755 "${PI_WATCHDOG_INSTALL_DIR}"
install -d -m 755 "${PI_WATCHDOG_INSTALL_DIR}/bin"

install -m 755 "${PROJECT_DIR}/src/pi_watchdog_log.sh" "${PI_WATCHDOG_INSTALL_DIR}/bin/pi_watchdog_log.sh"
install -m 644 "${PROJECT_DIR}/src/pi_watchdog_ui.py" "${PI_WATCHDOG_INSTALL_DIR}/pi_watchdog_ui.py"

touch "${PI_WATCHDOG_LOG_PATH}"
chmod 644 "${PI_WATCHDOG_LOG_PATH}"

tmp_dir="$(mktemp -d)"
trap 'rm -rf "${tmp_dir}"' EXIT

render_template "${PROJECT_DIR}/systemd/pi-watchdog-log.service" "${tmp_dir}/pi-watchdog-log.service"
render_template "${PROJECT_DIR}/systemd/pi-watchdog-log.timer" "${tmp_dir}/pi-watchdog-log.timer"
render_template "${PROJECT_DIR}/systemd/pi-watchdog-ui.service" "${tmp_dir}/pi-watchdog-ui.service"

install -m 644 "${tmp_dir}/pi-watchdog-log.service" /etc/systemd/system/pi-watchdog-log.service
install -m 644 "${tmp_dir}/pi-watchdog-log.timer" /etc/systemd/system/pi-watchdog-log.timer
install -m 644 "${tmp_dir}/pi-watchdog-ui.service" /etc/systemd/system/pi-watchdog-ui.service

systemctl daemon-reload
systemctl enable --now pi-watchdog-log.timer
systemctl restart pi-watchdog-log.service
systemctl enable --now pi-watchdog-ui.service

echo
echo "PiWatchdog is installed."
echo "Open: http://$(hostname -I | awk '{print $1}'):${PI_WATCHDOG_PORT}/"
