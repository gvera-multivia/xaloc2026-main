#!/usr/bin/env bash
set -euo pipefail

VISUAL_DEBUG="${XALOC_VISUAL_DEBUG:-0}"
DISPLAY_NUM="${DISPLAY:-:99}"
VNC_PORT="${XALOC_VNC_PORT:-5900}"
NOVNC_PORT="${XALOC_NOVNC_PORT:-6080}"

start_visual_stack() {
  echo "[playwright-runner] Iniciando stack visual (Xvfb + x11vnc + noVNC)..."
  export DISPLAY="$DISPLAY_NUM"
  local display_id="${DISPLAY#:}"
  local lock_file="/tmp/.X${display_id}-lock"
  local socket_file="/tmp/.X11-unix/X${display_id}"

  # Si quedo un lock huérfano (Xvfb muerto), limpiarlo para poder arrancar.
  if [[ -f "$lock_file" ]]; then
    local lock_pid
    lock_pid="$(cat "$lock_file" 2>/dev/null || true)"
    if [[ -z "$lock_pid" || ! "$lock_pid" =~ ^[0-9]+$ || ! -d "/proc/$lock_pid" ]]; then
      echo "[playwright-runner] Lock huérfano detectado en $lock_file; limpiando."
      rm -f "$lock_file" "$socket_file"
    fi
  fi

  Xvfb "$DISPLAY" -screen 0 1920x1080x24 -ac +extension RANDR -nolisten tcp >/tmp/xvfb.log 2>&1 &
  # Esperar a que el socket X11 exista antes de arrancar clientes.
  local ready=0
  for _ in $(seq 1 50); do
    if [[ -S "$socket_file" ]]; then
      ready=1
      break
    fi
    sleep 0.1
  done
  if [[ "$ready" != "1" ]]; then
    echo "[playwright-runner] ERROR: Xvfb no levanto en $DISPLAY."
    echo "[playwright-runner] /tmp/xvfb.log:"
    cat /tmp/xvfb.log || true
    return 1
  fi

  (fluxbox >/tmp/fluxbox.log 2>&1 || true) &
  x11vnc -display "$DISPLAY" -rfbport "$VNC_PORT" -forever -shared -nopw -listen 0.0.0.0 >/tmp/x11vnc.log 2>&1 &
  websockify --web=/usr/share/novnc/ "0.0.0.0:${NOVNC_PORT}" "127.0.0.1:${VNC_PORT}" >/tmp/novnc.log 2>&1 &

  echo "[playwright-runner] noVNC disponible en: http://localhost:${NOVNC_PORT}/vnc.html"
  echo "[playwright-runner] VNC directo en: localhost:${VNC_PORT}"
}

if [[ "${VISUAL_DEBUG,,}" == "1" || "${VISUAL_DEBUG,,}" == "true" || "${VISUAL_DEBUG,,}" == "yes" || "${VISUAL_DEBUG,,}" == "on" ]]; then
  start_visual_stack
else
  echo "[playwright-runner] Modo visual desactivado (XALOC_VISUAL_DEBUG=$VISUAL_DEBUG)."
fi

exec /usr/local/bin/playwright-runner-entrypoint.sh "$@"
