#!/usr/bin/env bash
set -euo pipefail

VISUAL_DEBUG="${XALOC_VISUAL_DEBUG:-0}"
DISPLAY_NUM="${DISPLAY:-:99}"
VNC_PORT="${XALOC_VNC_PORT:-5900}"
NOVNC_PORT="${XALOC_NOVNC_PORT:-6080}"

start_visual_stack() {
  echo "[playwright-runner] Iniciando stack visual (Xvfb + x11vnc + noVNC)..."
  export DISPLAY="$DISPLAY_NUM"

  Xvfb "$DISPLAY" -screen 0 1920x1080x24 -ac +extension RANDR >/tmp/xvfb.log 2>&1 &
  fluxbox >/tmp/fluxbox.log 2>&1 &
  x11vnc -display "$DISPLAY" -rfbport "$VNC_PORT" -forever -shared -nopw -listen 0.0.0.0 >/tmp/x11vnc.log 2>&1 &
  websockify --web=/usr/share/novnc/ "$NOVNC_PORT" "0.0.0.0:$VNC_PORT" >/tmp/novnc.log 2>&1 &

  echo "[playwright-runner] noVNC disponible en: http://localhost:${NOVNC_PORT}/vnc.html"
  echo "[playwright-runner] VNC directo en: localhost:${VNC_PORT}"
}

if [[ "${VISUAL_DEBUG,,}" == "1" || "${VISUAL_DEBUG,,}" == "true" || "${VISUAL_DEBUG,,}" == "yes" || "${VISUAL_DEBUG,,}" == "on" ]]; then
  start_visual_stack
else
  echo "[playwright-runner] Modo visual desactivado (XALOC_VISUAL_DEBUG=$VISUAL_DEBUG)."
fi

exec /usr/local/bin/playwright-runner-entrypoint.sh "$@"

