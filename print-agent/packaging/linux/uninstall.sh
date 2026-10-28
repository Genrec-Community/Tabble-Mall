#!/usr/bin/env bash
# Stops and removes the MallT print agent.
#
#   sudo bash uninstall.sh [--purge]
#
# Keeps the settings and printed-jobs.log unless --purge is given: deleting
# printed-jobs.log is what makes a machine reprint slips the kitchen already cooked from.
set -euo pipefail

SERVICE=mallt-print-agent
SERVICE_USER=mallt-agent
INSTALL_DIR=/opt/mallt-print-agent
CONFIG_DIR=/etc/mallt-print-agent
STATE_DIR=/var/lib/mallt-print-agent
UNIT_DIR=/etc/systemd/system
PURGE=0
SKIP_SERVICE=0

while [ $# -gt 0 ]; do
  case "$1" in
    --purge) PURGE=1; shift ;;
    --install-dir) INSTALL_DIR="${2:-}"; shift 2 ;;
    --config-dir) CONFIG_DIR="${2:-}"; shift 2 ;;
    --state-dir) STATE_DIR="${2:-}"; shift 2 ;;
    --unit-dir) UNIT_DIR="${2:-}"; shift 2 ;;
    --skip-service) SKIP_SERVICE=1; shift ;;
    *) echo "unknown option: $1" >&2; exit 1 ;;
  esac
done

if [ "$SKIP_SERVICE" -eq 0 ]; then
  [ "$(id -u)" -eq 0 ] || { echo "run this with sudo:  sudo bash uninstall.sh" >&2; exit 1; }
  if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
    systemctl disable --now "$SERVICE" >/dev/null 2>&1 || true
  fi
  rm -f "$UNIT_DIR/$SERVICE.service"
  if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
    systemctl daemon-reload || true
  fi
fi

rm -f "$INSTALL_DIR/print-agent" "$INSTALL_DIR/agent.example.toml" "$INSTALL_DIR/rollback-guard.sh"
rm -f "$INSTALL_DIR"/print-agent.old "$INSTALL_DIR"/print-agent.new "$INSTALL_DIR"/print-agent.bad \
      "$INSTALL_DIR"/print-agent.trial "$INSTALL_DIR"/print-agent.part
rm -rf "$INSTALL_DIR/backup"
rmdir "$INSTALL_DIR" 2>/dev/null || true

if [ "$PURGE" -eq 1 ]; then
  rm -rf "$CONFIG_DIR" "$STATE_DIR"
  if [ "$SKIP_SERVICE" -eq 0 ] && id -u "$SERVICE_USER" >/dev/null 2>&1; then
    userdel "$SERVICE_USER" 2>/dev/null || true
  fi
  echo "Removed, including the settings and the printed-slip record."
else
  echo "Removed. Settings and the printed-slip record were kept in $CONFIG_DIR and $STATE_DIR (add --purge to delete them)."
fi
