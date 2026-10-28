#!/usr/bin/env bash
# Installs the MallT print agent as a systemd service, checks it can pair, starts it.
#
#   sudo bash install.sh --url https://... --token ...
#
# Safe to run again: that is the upgrade. The program and the token are replaced; every
# other setting in agent.toml and the printed-slip record are kept. If the server refuses
# the token or cannot be reached, nothing is left changed: a working install stays
# working and a fresh machine is left clean.
#
# --skip-service skips the system user, ownership, systemd and the live wait. It exists
# for the test suite.
set -euo pipefail

SERVICE=mallt-print-agent
SERVICE_USER=mallt-agent
INSTALL_DIR=/opt/mallt-print-agent
CONFIG_DIR=/etc/mallt-print-agent
STATE_DIR=/var/lib/mallt-print-agent
UNIT_DIR=/etc/systemd/system
LIVE_SECONDS=30
SKIP_SERVICE=0
URL=""
TOKEN=""

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

fail() {
  echo "Install stopped: $*" >&2
  exit 1
}

while [ $# -gt 0 ]; do
  case "$1" in
    --url) URL="${2:-}"; shift 2 ;;
    --token) TOKEN="${2:-}"; shift 2 ;;
    --install-dir) INSTALL_DIR="${2:-}"; shift 2 ;;
    --config-dir) CONFIG_DIR="${2:-}"; shift 2 ;;
    --state-dir) STATE_DIR="${2:-}"; shift 2 ;;
    --unit-dir) UNIT_DIR="${2:-}"; shift 2 ;;
    --live-seconds) LIVE_SECONDS="${2:-30}"; shift 2 ;;
    --skip-service) SKIP_SERVICE=1; shift ;;
    -h|--help) sed -n '2,12p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) fail "unknown option: $1" ;;
  esac
done

# --- 1. Refuse anything that is not what the dashboard generates ---------------------
# Only these characters ever need to pass, so values never need quoting in bash or TOML,
# and a pasted command that was damaged on the way is refused before a file is touched.
[ -n "$URL" ] || fail "--url is required. Paste the command from the dashboard."
[ -n "$TOKEN" ] || fail "--token is required. Paste the command from the dashboard."
[[ "$URL" =~ ^(https?|wss?)://[A-Za-z0-9.-]+(:[0-9]+)?(/[A-Za-z0-9._~%/-]*)?$ ]] \
  || fail "the address is not valid. Paste the command from the dashboard exactly as shown."
[[ "$TOKEN" =~ ^[A-Za-z0-9._~+/=-]+$ ]] \
  || fail "the token contains characters it never has. Paste the command from the dashboard exactly as shown."
if [ "$TOKEN" = "PASTE-THE-PAIRING-TOKEN-HERE" ] || [[ "$URL" == *mallt.example.com* ]]; then
  fail "that is the placeholder from the example file. Use the command the dashboard shows after \"Pair a PC\"."
fi

SOURCE="$here/print-agent"
[ -f "$SOURCE" ] || fail "print-agent is not next to install.sh. Run this from the unzipped folder."

if [ "$SKIP_SERVICE" -eq 0 ]; then
  [ "$(id -u)" -eq 0 ] || fail "run this with sudo:  sudo bash install.sh --url ... --token ..."
  if ! command -v systemctl >/dev/null 2>&1 || [ ! -d /run/systemd/system ]; then
    fail "this machine does not use systemd, which the service needs. Run print-agent by hand, or use a systemd-based distribution."
  fi
fi

BIN="$INSTALL_DIR/print-agent"
CONFIG="$CONFIG_DIR/agent.toml"
BACKUP="$INSTALL_DIR/backup"
first_install=1; [ -f "$BIN" ] && first_install=0
had_config=0;    [ -f "$CONFIG" ] && had_config=1
was_active=0

# --- 2. Stop any running copy, then keep one previous generation ---------------------
if [ "$SKIP_SERVICE" -eq 0 ] && systemctl is-active --quiet "$SERVICE"; then
  was_active=1
  systemctl stop "$SERVICE"
fi

restore_previous() {
  if [ "$first_install" -eq 1 ]; then
    rm -f "$BIN" "$INSTALL_DIR/agent.example.toml" "$INSTALL_DIR/rollback-guard.sh"
  elif [ -f "$BACKUP/print-agent" ]; then
    cp -p "$BACKUP/print-agent" "$BIN"
  fi
  if [ "$had_config" -eq 1 ] && [ -f "$BACKUP/agent.toml" ]; then
    cp -p "$BACKUP/agent.toml" "$CONFIG"
  elif [ "$had_config" -eq 0 ]; then
    rm -f "$CONFIG"
    rmdir "$CONFIG_DIR" 2>/dev/null || true
  fi
  rm -rf "$BACKUP"
  rmdir "$INSTALL_DIR" 2>/dev/null || true
  if [ "$first_install" -eq 1 ]; then
    # Empty if nothing else lives there, so a failed first install leaves no trace.
    rmdir "$STATE_DIR" 2>/dev/null || true
  fi
  if [ "$SKIP_SERVICE" -eq 0 ] && [ "$was_active" -eq 1 ]; then
    systemctl start "$SERVICE" || true
  fi
}

install -d -m 0755 "$INSTALL_DIR"
rm -rf "$BACKUP"
install -d -m 0700 "$BACKUP"
[ -f "$BIN" ] && cp -p "$BIN" "$BACKUP/"
[ -f "$CONFIG" ] && cp -p "$CONFIG" "$BACKUP/"

# --- 3. Put the new files down -------------------------------------------------------
if [ "$SKIP_SERVICE" -eq 0 ]; then
  id -u "$SERVICE_USER" >/dev/null 2>&1 \
    || useradd --system --user-group --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
  # USB printers are read by group `lp`, serial/Bluetooth ones by `dialout`.
  for group in lp dialout; do
    if getent group "$group" >/dev/null; then usermod -aG "$group" "$SERVICE_USER" || true; fi
  done
fi

# A fresh program is a fresh start: leftovers of an earlier self-update (a trial in
# progress, a rolled-back version, the previous program) must not act on it.
rm -f "$INSTALL_DIR"/print-agent.trial "$INSTALL_DIR"/print-agent.bad \
      "$INSTALL_DIR"/print-agent.old "$INSTALL_DIR"/print-agent.new \
      "$INSTALL_DIR"/print-agent.bad.tmp "$INSTALL_DIR"/print-agent.trial.tmp
install -m 0755 "$SOURCE" "$BIN"
install -m 0755 "$here/rollback-guard.sh" "$INSTALL_DIR/rollback-guard.sh"
if [ -f "$here/agent.example.toml" ]; then
  install -m 0644 "$here/agent.example.toml" "$INSTALL_DIR/agent.example.toml"
fi

if [ "$SKIP_SERVICE" -eq 0 ]; then
  # The service runs as an unprivileged user and updates itself by renaming its own
  # program, which needs the folder to be its own. Without this the update would fail
  # quietly on every Linux store PC.
  chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
fi

install -d -m 0755 "$CONFIG_DIR"
tmp="$(mktemp)"
{
  printf 'url = "%s"\n' "$URL"
  printf 'token = "%s"\n' "$TOKEN"
  # Every other line the admin may have added is kept.
  if [ -f "$CONFIG" ]; then grep -Ev '^[[:space:]]*(url|token)[[:space:]]*=' "$CONFIG" || true; fi
} > "$tmp"
install -m 0640 "$tmp" "$CONFIG"
rm -f "$tmp"

if [ "$SKIP_SERVICE" -eq 0 ]; then
  chown "root:$SERVICE_USER" "$CONFIG"
  install -d -m 0750 -o "$SERVICE_USER" -g "$SERVICE_USER" "$STATE_DIR"
else
  install -d -m 0750 "$STATE_DIR"
fi

# --- 4. Prove it can pair, as the user the service will run as -----------------------
echo "Checking the pairing with the server..."
set +e
if [ "$SKIP_SERVICE" -eq 0 ]; then
  runuser -u "$SERVICE_USER" -- env "MALLT_AGENT_STATE_DIR=$STATE_DIR" "$BIN" --config "$CONFIG" --check
else
  MALLT_AGENT_STATE_DIR="$STATE_DIR" "$BIN" --config "$CONFIG" --check
fi
check_code=$?
set -e

if [ "$check_code" -ne 0 ]; then
  restore_previous
  case "$check_code" in
    3) fail 'the server refused the token. In the dashboard go to Printers in the store dashboard, choose "New credential" for this machine, and run the new command. Nothing was changed.' ;;
    5) fail "this machine could not reach the server. Check the internet connection and the address, then run the command again. Nothing was changed." ;;
    *) fail "the new program failed its self-check (exit $check_code). Nothing was changed." ;;
  esac
fi

rm -rf "$BACKUP"

if [ "$SKIP_SERVICE" -eq 1 ]; then
  echo "Installed (service registration skipped)."
  exit 0
fi

# --- 5. Register the service, start it, wait for the server to confirm ---------------
sed -e "s|@INSTALL_DIR@|$INSTALL_DIR|g" \
    -e "s|@CONFIG@|$CONFIG|g" \
    -e "s|@STATE_DIR@|$STATE_DIR|g" \
    -e "s|@USER@|$SERVICE_USER|g" \
    "$here/mallt-print-agent.service" > "$UNIT_DIR/$SERVICE.service"
chmod 0644 "$UNIT_DIR/$SERVICE.service"

since="$(date '+%Y-%m-%d %H:%M:%S')"
systemctl daemon-reload
systemctl enable "$SERVICE" >/dev/null 2>&1
systemctl restart "$SERVICE"

live=0
for _ in $(seq 1 "$LIVE_SECONDS"); do
  if journalctl -u "$SERVICE" --since "$since" --no-pager 2>/dev/null | grep -q 'paired as agent'; then
    live=1
    break
  fi
  sleep 1
done

if [ "$live" -eq 1 ]; then
  echo "Printing is live. The dashboard should now show this machine as connected."
  echo "Logs: journalctl -u $SERVICE -f"
else
  echo "Installed and started, but the server has not confirmed the connection yet." >&2
  echo "Look at: journalctl -u $SERVICE -n 50" >&2
fi
