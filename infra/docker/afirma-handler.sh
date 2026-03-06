#!/usr/bin/env bash
# afirma-handler.sh
# -----------------
# Handler XDG para protocolo afirma:// y xalocafirma://
#
# En Docker/headless NO hay AutoFirma GUI. Este handler:
#   1. Guarda la URI en .latest (comportamiento original, para compatibilidad)
#   2. Lanza autofirma_proxy.py en background, que:
#      - Escucha en los puertos que la página espera (wss://127.0.0.1:PORT/)
#      - Firma con AutoFirma CLI cuando la página envía el documento
#      - Devuelve la firma en el protocolo @firma exacto
#
# La página (AutoScript @firma de Redsara) conecta vía WebSocket y obtiene
# su firma sin necesidad de GUI ni daemon AutoFirma real.
#
# Variables de entorno relevantes:
#   XALOC_AFIRMA_URI_LATEST   (default: /tmp/xaloc_afirma_uri.latest)
#   XALOC_AFIRMA_URI_LOG      (default: /tmp/xaloc_afirma_uri.log)
#   XALOC_AFIRMA_PROXY_PID    (default: /tmp/xaloc_afirma_proxy.pid)
#   XALOC_AFIRMA_PROXY_READY  (default: /tmp/xaloc_afirma_proxy.ready)
#   XALOC_AFIRMA_PROXY_SCRIPT (default: /app/autofirma_proxy.py)
#   PLAYWRIGHT_CERT_PATH       certificado PFX para AutoFirma CLI
#   PLAYWRIGHT_CERT_PASSWORD   password del PFX

set -euo pipefail

uri="${1:-}"
log_file="${XALOC_AFIRMA_URI_LOG:-/tmp/xaloc_afirma_uri.log}"
latest_file="${XALOC_AFIRMA_URI_LATEST:-/tmp/xaloc_afirma_uri.latest}"
proxy_pid_file="${XALOC_AFIRMA_PROXY_PID:-/tmp/xaloc_afirma_proxy.pid}"
proxy_ready_file="${XALOC_AFIRMA_PROXY_READY:-/tmp/xaloc_afirma_proxy.ready}"
python_bin="${XALOC_PYTHON_BIN:-/opt/venv/bin/python3}"

# Buscar autofirma_proxy.py en múltiples rutas candidatas.
# El override explícito tiene prioridad; si no, se prueban las rutas conocidas.
_find_proxy_script() {
  local candidates=(
    "${XALOC_AFIRMA_PROXY_SCRIPT:-}"
    "/app/infra/docker/autofirma_proxy.py"
    "/app/autofirma_proxy.py"
    "/opt/venv/autofirma_proxy.py"
  )
  for c in "${candidates[@]}"; do
    [[ -n "$c" && -f "$c" ]] && echo "$c" && return 0
  done
  return 1
}
proxy_script="$(_find_proxy_script || true)"

# ── 1. Guardar URI (compatibilidad con código existente) ─────────────────────
if [[ -n "$uri" ]]; then
  ts="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  printf "%s\t%s\n" "$ts" "$uri" >> "$log_file"
  printf "%s" "$uri" > "$latest_file"
  echo "[afirma-handler] URI capturada: ${uri:0:100}..."
fi

# ── 2. Matar proxy anterior si sigue vivo ────────────────────────────────────
if [[ -f "$proxy_pid_file" ]]; then
  old_pid="$(cat "$proxy_pid_file" 2>/dev/null || true)"
  if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
    echo "[afirma-handler] Matando proxy anterior (PID=$old_pid)..."
    kill "$old_pid" 2>/dev/null || true
    sleep 0.3
  fi
  rm -f "$proxy_pid_file"
fi
rm -f "$proxy_ready_file"

# ── 3. Verificar que el script proxy existe ───────────────────────────────────
if [[ -z "$proxy_script" ]]; then
  echo "[afirma-handler] Aviso: autofirma_proxy.py no encontrado en ninguna ruta candidata."
  echo "[afirma-handler] Funcionando en modo legado (solo URI guardada, sin proxy)."
  exit 0
fi
echo "[afirma-handler] Usando proxy script: $proxy_script"

if [[ ! -x "$python_bin" ]] && ! command -v python3 &>/dev/null; then
  echo "[afirma-handler] ERROR: python3 no encontrado."
  exit 1
fi

# Usar python del venv si existe, si no el del sistema
if [[ ! -x "$python_bin" ]]; then
  python_bin="python3"
fi

# ── 4. Lanzar proxy en background ────────────────────────────────────────────
echo "[afirma-handler] Lanzando autofirma_proxy.py para URI: ${uri:0:80}..."

nohup "$python_bin" "$proxy_script" "$uri" \
  >> /tmp/xaloc_afirma_proxy.log 2>&1 &

proxy_pid=$!
echo "[afirma-handler] Proxy PID=$proxy_pid lanzado."

# NO esperamos a que el proxy esté listo aquí — el handler debe salir rápido
# para que Chromium no bloquee. El código Python (Playwright) espera
# el archivo proxy_ready_file antes de continuar.

exit 0
