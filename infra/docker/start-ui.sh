#!/usr/bin/env bash
set -euo pipefail

VISUAL_DEBUG="${XALOC_VISUAL_DEBUG:-1}"
export DISPLAY="${DISPLAY:-:99}"
WIDTH="${UI_WIDTH:-2560}"
HEIGHT="${UI_HEIGHT:-1440}"
DEPTH="${UI_DEPTH:-24}"
VNC_PORT="${VNC_PORT:-${XALOC_VNC_PORT:-5900}}"
NOVNC_PORT="${NOVNC_PORT:-${XALOC_NOVNC_PORT:-6080}}"

is_truthy() {
  local v="${1:-}"
  v="${v,,}"
  [[ "$v" == "1" || "$v" == "true" || "$v" == "yes" || "$v" == "on" ]]
}

start_visual_stack() {
  echo "[playwright-runner] Starting visual stack (Xvfb + openbox + x11vnc + noVNC)..."
  echo "[playwright-runner] Xvfb geometry: ${WIDTH}x${HEIGHT}x${DEPTH} on DISPLAY=${DISPLAY}"

  local display_id="${DISPLAY#:}"
  local lock_file="/tmp/.X${display_id}-lock"
  local socket_file="/tmp/.X11-unix/X${display_id}"

  if [[ -f "$lock_file" ]]; then
    local lock_pid
    lock_pid="$(cat "$lock_file" 2>/dev/null || true)"
    if [[ -z "$lock_pid" || ! "$lock_pid" =~ ^[0-9]+$ || ! -d "/proc/$lock_pid" ]]; then
      echo "[playwright-runner] Cleaning stale X lock: $lock_file"
      rm -f "$lock_file" "$socket_file"
    fi
  fi

  Xvfb "$DISPLAY" -screen 0 "${WIDTH}x${HEIGHT}x${DEPTH}" -ac +extension RANDR >/tmp/xvfb.log 2>&1 &

  local ready=0
  for _ in $(seq 1 50); do
    if [[ -S "$socket_file" ]]; then
      ready=1
      break
    fi
    sleep 0.1
  done
  if [[ "$ready" != "1" ]]; then
    echo "[playwright-runner] ERROR: Xvfb did not start on $DISPLAY"
    cat /tmp/xvfb.log || true
    return 1
  fi

  openbox >/tmp/openbox.log 2>&1 &
  x11vnc -display "$DISPLAY" \
    -forever -shared \
    -rfbport "$VNC_PORT" \
    -nopw -noxdamage -xkb -listen 0.0.0.0 >/tmp/x11vnc.log 2>&1 &
  websockify --web=/usr/share/novnc/ "0.0.0.0:${NOVNC_PORT}" "127.0.0.1:${VNC_PORT}" >/tmp/novnc.log 2>&1 &

  echo "[playwright-runner] UI ready:"
  echo "[playwright-runner] - noVNC: http://localhost:${NOVNC_PORT}/vnc.html"
  echo "[playwright-runner] - VNC: localhost:${VNC_PORT}"
}

if is_truthy "$VISUAL_DEBUG"; then
  start_visual_stack
else
  echo "[playwright-runner] Visual mode disabled (XALOC_VISUAL_DEBUG=$VISUAL_DEBUG)."
fi

exec /usr/local/bin/playwright-runner-entrypoint.sh "$@"
