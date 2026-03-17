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
cert_path="${PLAYWRIGHT_CERT_PATH:-/data/certificates/certificate.pfx}"

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

_uri_lc="$(printf '%s' "$uri" | tr '[:upper:]' '[:lower:]')"
_is_websocket_mode=0
_is_sign_mode=0
if [[ "$_uri_lc" == *"://websocket?"* ]] || [[ "$_uri_lc" == *"ports="* ]]; then
  _is_websocket_mode=1
fi
if [[ "$_uri_lc" == *"://sign?"* ]] || [[ "$_uri_lc" == *"rtservlet="* ]]; then
  _is_sign_mode=1
fi

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

# ── 3. Enrutado por modo de URI ──────────────────────────────────────────────
# websocket?ports=...  -> proxy WS (modo Redsara clásico)
# sign?...rtservlet=... -> AutoFirma protocolo nativo (modo FIRe/Valencia)
if [[ "$_is_sign_mode" -eq 1 && "$_is_websocket_mode" -eq 0 ]]; then
  capture_only="${XALOC_AFIRMA_SIGN_CAPTURE_ONLY:-0}"
  [[ -f /tmp/xaloc_afirma_sign_capture_only.flag ]] && capture_only=1
  bridge_mode="${XALOC_AFIRMA_SIGN_BRIDGE_MODE:-1}"
  bridge_fallback_native="${XALOC_AFIRMA_SIGN_BRIDGE_FALLBACK_NATIVE:-0}"
  bridge_script="${XALOC_AFIRMA_SIGN_BRIDGE_SCRIPT:-/app/infra/docker/afirma_sign_bridge.py}"
  bridge_timeout="${XALOC_AFIRMA_SIGN_BRIDGE_TIMEOUT_SEC:-90}"
  # Forense de protocolo FIRe sign/rtservlet para poder emular get->sign->put sin GUI.
  probe_enabled="${XALOC_AFIRMA_SIGN_PROBE_ACTIVE:-0}"
  [[ -f /tmp/xaloc_afirma_sign_probe_active.flag ]] && probe_enabled=1
  if [[ "${probe_enabled,,}" == "1" || "${probe_enabled,,}" == "true" || "${probe_enabled,,}" == "yes" || "${probe_enabled,,}" == "on" ]]; then
    if [[ -x "$python_bin" || $(command -v python3 >/dev/null 2>&1; echo $?) -eq 0 ]]; then
      probe_py="${XALOC_AFIRMA_SIGN_PROBE_SCRIPT:-/app/infra/docker/afirma_sign_probe.py}"
      if [[ -f "$probe_py" ]]; then
        if [[ ! -x "$python_bin" ]]; then
          python_bin="python3"
        fi
        nohup "$python_bin" "$probe_py" "$uri" >> /tmp/xaloc_afirma_sign_probe.log 2>&1 &
        echo "[afirma-handler] Probe sign ACTIVO (XALOC_AFIRMA_SIGN_PROBE_ACTIVE=1)."
      fi
    fi
  else
    echo "[afirma-handler] Probe sign desactivado para evitar consumir fileid de un solo uso."
  fi

  if [[ "${capture_only,,}" == "1" || "${capture_only,,}" == "true" || "${capture_only,,}" == "yes" || "${capture_only,,}" == "on" ]]; then
    echo "[afirma-handler] CAPTURE_ONLY activo: no se lanzara AutoFirma nativo."
    exit 0
  fi

  if [[ "${bridge_mode,,}" == "1" || "${bridge_mode,,}" == "true" || "${bridge_mode,,}" == "yes" || "${bridge_mode,,}" == "on" ]]; then
    py_bin="$python_bin"
    if [[ ! -x "$py_bin" ]]; then
      py_bin="python3"
    fi
    if command -v "$py_bin" >/dev/null 2>&1 && [[ -f "$bridge_script" ]]; then
      echo "[afirma-handler] Modo sign/rtservlet detectado. Ejecutando bridge programatico..."
      if timeout "${bridge_timeout}s" "$py_bin" "$bridge_script" "$uri" >> /tmp/xaloc_afirma_sign_bridge.log 2>&1; then
        echo "[afirma-handler] Bridge sign completado. No se lanza AutoFirma UI."
        exit 0
      else
        rc=$?
        echo "[afirma-handler] Bridge sign fallo (rc=$rc)."
        if [[ "${bridge_fallback_native,,}" != "1" && "${bridge_fallback_native,,}" != "true" && "${bridge_fallback_native,,}" != "yes" && "${bridge_fallback_native,,}" != "on" ]]; then
          echo "[afirma-handler] Fallback a AutoFirma nativo desactivado. Abortando para evitar UI."
          exit 1
        fi
        echo "[afirma-handler] Fallback a AutoFirma nativo activado."
      fi
    else
      echo "[afirma-handler] Bridge sign no disponible (python/script)."
      if [[ "${bridge_fallback_native,,}" != "1" && "${bridge_fallback_native,,}" != "true" && "${bridge_fallback_native,,}" != "yes" && "${bridge_fallback_native,,}" != "on" ]]; then
        echo "[afirma-handler] Fallback a AutoFirma nativo desactivado. Abortando para evitar UI."
        exit 1
      fi
    fi
  fi

  if ! command -v autofirma >/dev/null 2>&1; then
    echo "[afirma-handler] ERROR: URI sign detectada pero binario 'autofirma' no disponible."
    exit 1
  fi
  launch_uri="$uri"
  enrich_mode="${XALOC_AFIRMA_SIGN_URI_ENRICH_MODE:-auto}"
  if [[ "${enrich_mode,,}" == "auto" || "${enrich_mode,,}" == "1" || "${enrich_mode,,}" == "true" || "${enrich_mode,,}" == "yes" || "${enrich_mode,,}" == "on" ]]; then
    py_bin="$python_bin"
    if [[ ! -x "$py_bin" ]]; then
      py_bin="python3"
    fi
    if command -v "$py_bin" >/dev/null 2>&1; then
      launch_uri="$("$py_bin" - "$uri" "$cert_path" <<'PY'
import base64
import sys
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

uri = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
cert_path = (sys.argv[2] if len(sys.argv) > 2 else "").strip()
if not uri:
    print(uri)
    raise SystemExit(0)

work = uri.replace("xalocafirma://", "afirma://")
base = "http://x/" + work.split("://", 1)[1]
u = urlparse(base)
qs = parse_qs(u.query, keep_blank_values=True)

def _set_if_missing(k: str, v: str) -> None:
    if not qs.get(k):
        qs[k] = [v]

# Intentar reutilizar ultimo certificado sin reabrir selector.
_set_if_missing("sticky", "true")
_set_if_missing("resetsticky", "false")

# Forzar almacen PKCS#12 local para evitar NSS dialog cuando sea posible.
if cert_path:
    _set_if_missing("keystore", "pkcs12")
    _set_if_missing("ksb64", base64.b64encode(cert_path.encode("utf-8")).decode("ascii"))

new_query = urlencode(qs, doseq=True)
new_url = urlunparse((u.scheme, u.netloc, u.path, u.params, new_query, u.fragment))
out = new_url.replace("http://x/", "afirma://", 1)
print(out)
PY
      )"
    fi
  fi

  echo "[afirma-handler] Modo sign/rtservlet detectado. Lanzando AutoFirma nativo..."
  if [[ "$launch_uri" != "$uri" ]]; then
    echo "[afirma-handler] URI enriquecida (sticky/keystore) para minimizar dialogos de certificado."
  fi
  nohup autofirma "$launch_uri" >> /tmp/xaloc_afirma_native.log 2>&1 &
  af_pid=$!
  echo "[afirma-handler] AutoFirma nativo lanzado PID=$af_pid."
  exit 0
fi

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

# ── 4. Lanzar proxy en background (modo websocket) ──────────────────────────
echo "[afirma-handler] Modo websocket detectado. Lanzando autofirma_proxy.py para URI: ${uri:0:80}..."

nohup "$python_bin" "$proxy_script" "$uri" \
  >> /tmp/xaloc_afirma_proxy.log 2>&1 &

proxy_pid=$!
echo "[afirma-handler] Proxy PID=$proxy_pid lanzado."

# NO esperamos a que el proxy esté listo aquí — el handler debe salir rápido
# para que Chromium no bloquee. El código Python (Playwright) espera
# el archivo proxy_ready_file antes de continuar.

exit 0
