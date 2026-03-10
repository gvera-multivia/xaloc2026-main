#!/usr/bin/env bash
set -euo pipefail

CERT_PATH="${PLAYWRIGHT_CERT_PATH:-/data/certificates/certificate.pfx}"
PROFILE_DIR="${PLAYWRIGHT_PROFILE_DIR:-/app/profiles/worker}"
NSS_DB_DIR="${PLAYWRIGHT_NSS_DB_DIR:-$PROFILE_DIR}"
CERT_REQUIRED="${PLAYWRIGHT_CERT_REQUIRED:-1}"
CERT_CN="${CERTIFICADO_CN:-35059210B MARIA TERESA MORENTE (R: B62798210)}"
CERT_FILTER_BY_CN="${XALOC_CERT_FILTER_BY_CN:-0}"
AUTOSELECT_POLICY_ENABLED="${XALOC_CERT_AUTOSELECT_VIA_POLICY:-1}"
AUTOSELECT_RULES_JSON="${XALOC_CERT_AUTOSELECT_RULES_JSON:-}"
AUTOSELECT_PATTERN="${XALOC_CERT_AUTOSELECT_PATTERN:-}"
URL_CERT_CONFIG_BAT="${XALOC_URL_CERT_CONFIG_BAT_PATH:-/app/url-cert-config.bat}"
AFIRMA_ORIGIN="${XALOC_AUTOFIRMA_ORIGIN:-https://palma.sedipualba.es}"
AFIRMA_ALLOWED_ORIGINS="${XALOC_AUTOFIRMA_ALLOWED_ORIGINS:-}"
AFIRMA_PROTOCOLS="${XALOC_AUTOFIRMA_PROTOCOLS:-afirma,xalocafirma}"
AFIRMA_PROTOCOL_POLICY_ENABLED="${XALOC_AUTOFIRMA_PROTOCOL_POLICY_ENABLED:-1}"

# En algunos entornos compose/Windows, HOME puede llegar corrupto (ej. C:Users...).
# Forzamos un HOME Linux estable para que Chromium localice NSS correctamente.
if [[ -z "${HOME:-}" || "$HOME" == *:* ]]; then
  export HOME=/root
fi
GLOBAL_NSS_DB_DIR="${PLAYWRIGHT_GLOBAL_NSS_DB_DIR:-$HOME/.pki/nssdb}"

write_autoselect_policy() {
  if [[ "${AUTOSELECT_POLICY_ENABLED,,}" != "1" && "${AUTOSELECT_POLICY_ENABLED,,}" != "true" && "${AUTOSELECT_POLICY_ENABLED,,}" != "yes" && "${AUTOSELECT_POLICY_ENABLED,,}" != "on" ]]; then
    echo "[playwright-runner] AutoSelect policy desactivada (XALOC_CERT_AUTOSELECT_VIA_POLICY=$AUTOSELECT_POLICY_ENABLED)."
    return 0
  fi

  mkdir -p /etc/chromium/policies/managed /etc/opt/chrome/policies/managed /etc/opt/chrome_for_testing/policies/managed /etc/opt/edge/policies/managed

  local filter_mode="none"
  if [[ "${CERT_FILTER_BY_CN,,}" == "1" || "${CERT_FILTER_BY_CN,,}" == "true" || "${CERT_FILTER_BY_CN,,}" == "yes" || "${CERT_FILTER_BY_CN,,}" == "on" ]]; then
    filter_mode="subject_cn"
  fi

  export CERT_CN CERT_FILTER_BY_CN AUTOSELECT_RULES_JSON AUTOSELECT_PATTERN URL_CERT_CONFIG_BAT filter_mode
  python3 <<'PY'
import json
import os
import pathlib
import re

cert_cn = (os.getenv("CERT_CN") or "").strip()
filter_mode = (os.getenv("filter_mode") or "none").strip().lower()
rules_json_env = (os.getenv("AUTOSELECT_RULES_JSON") or "").strip()
single_pattern = (os.getenv("AUTOSELECT_PATTERN") or "").strip()
bat_path = pathlib.Path((os.getenv("URL_CERT_CONFIG_BAT") or "/app/url-cert-config.bat").strip())

default_patterns = [
    "https://sede.madrid.es/*",
    "https://servcla.madrid.es/*",
    "https://servpub.madrid.es/*",
    "https://www.xalocgirona.cat/*",
    "https://seu.xalocgirona.cat/*",
    "https://www.base.cat/*",
    "https://www.baseonline.cat/*",
    "https://valid.aoc.cat/*",
    "https://cert.valid.aoc.cat/*",
    "https://cas.madrid.es/*",
    "https://pasarela.clave.gob.es/*",
    "https://[*.]madrid.es/*",
    "https://[*.]clave.gob.es/*",
    "https://cas.madrid.es:443/*",
    "https://pasarela.clave.gob.es:443/*",
    "https://cert.valid.aoc.cat:443/*",
    "https://palma.sedipualba.es/*",
    "https://identificacionssl.sedipualba.es/*",
    "https://aoberta.terrassa.cat/*",
]

def _parse_rules_from_bat(path: pathlib.Path):
    if not path.exists():
        return []
    txt = path.read_text(encoding="utf-8", errors="ignore")
    pattern_re = re.compile(r'\\"pattern\\":\\"([^"]+)\\"')
    patterns = pattern_re.findall(txt)
    seen = set()
    out = []
    for p in patterns:
        p = p.strip()
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return out

if rules_json_env:
    rendered = rules_json_env.replace("__CERT_CN__", cert_cn).replace("${CERTIFICADO_CN}", cert_cn)
    parsed = json.loads(rendered)
    if not isinstance(parsed, list):
        raise ValueError("XALOC_CERT_AUTOSELECT_RULES_JSON debe ser una lista JSON")
    rules = parsed
else:
    if single_pattern:
        patterns = [single_pattern]
    else:
        patterns = _parse_rules_from_bat(bat_path) or default_patterns
    if filter_mode == "subject_cn" and cert_cn:
        cert_filter = {"SUBJECT": {"CN": cert_cn}}
    else:
        cert_filter = {}
    rules = [{"pattern": p, "filter": cert_filter} for p in patterns]

stringified_rules = [json.dumps(item, ensure_ascii=False, separators=(",", ":")) for item in rules]
policy_doc = {"AutoSelectCertificateForUrls": stringified_rules}

for out_file in [
    pathlib.Path("/etc/chromium/policies/managed/xaloc-cert-policy.json"),
    pathlib.Path("/etc/opt/chrome/policies/managed/xaloc-cert-policy.json"),
    pathlib.Path("/etc/opt/chrome_for_testing/policies/managed/xaloc-cert-policy.json"),
    pathlib.Path("/etc/opt/edge/policies/managed/xaloc-cert-policy.json"),
]:
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(policy_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[playwright-runner] Policy escrita: {out_file}")

print("[playwright-runner] AutoSelectCertificateForUrls aplicado con", len(stringified_rules), "reglas.")
print("[playwright-runner] filter_mode =", filter_mode)
if cert_cn:
    print("[playwright-runner] CERT_CN =", cert_cn)
PY
}

write_afirma_protocol_policy() {
  if [[ "${AFIRMA_PROTOCOL_POLICY_ENABLED,,}" != "1" && "${AFIRMA_PROTOCOL_POLICY_ENABLED,,}" != "true" && "${AFIRMA_PROTOCOL_POLICY_ENABLED,,}" != "yes" && "${AFIRMA_PROTOCOL_POLICY_ENABLED,,}" != "on" ]]; then
    echo "[playwright-runner] AutoLaunchProtocolsFromOrigins desactivada (XALOC_AUTOFIRMA_PROTOCOL_POLICY_ENABLED=$AFIRMA_PROTOCOL_POLICY_ENABLED)."
    return 0
  fi

  mkdir -p /etc/chromium/policies/managed /etc/opt/chrome/policies/managed /etc/opt/chrome_for_testing/policies/managed /etc/opt/edge/policies/managed
  export AFIRMA_ORIGIN AFIRMA_ALLOWED_ORIGINS AFIRMA_PROTOCOLS
  python3 <<'PY'
import json
import os
import pathlib

default_origin = (os.getenv("AFIRMA_ORIGIN") or "https://palma.sedipualba.es").strip()
origins_csv = (os.getenv("AFIRMA_ALLOWED_ORIGINS") or "").strip()
protocols_csv = (os.getenv("AFIRMA_PROTOCOLS") or "afirma,xalocafirma").strip()

origins = [x.strip() for x in origins_csv.split(",") if x.strip()] if origins_csv else [default_origin]
protocols = [x.strip() for x in protocols_csv.split(",") if x.strip()]
if not protocols:
    protocols = ["afirma", "xalocafirma"]

rules = [{"protocol": proto, "allowed_origins": origins} for proto in protocols]
policy_doc = {"AutoLaunchProtocolsFromOrigins": rules}

for out_file in [
    pathlib.Path("/etc/chromium/policies/managed/xaloc-afirma-policy.json"),
    pathlib.Path("/etc/opt/chrome/policies/managed/xaloc-afirma-policy.json"),
    pathlib.Path("/etc/opt/chrome_for_testing/policies/managed/xaloc-afirma-policy.json"),
    pathlib.Path("/etc/opt/edge/policies/managed/xaloc-afirma-policy.json"),
]:
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(policy_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[playwright-runner] Policy escrita: {out_file}")

print("[playwright-runner] AutoLaunchProtocolsFromOrigins aplicado. protocols=", protocols, "origins=", origins)
PY
}

register_afirma_xdg_handler() {
  local app_file="/usr/share/applications/xaloc-afirma-handler.desktop"
  if [[ ! -f "$app_file" ]]; then
    echo "[playwright-runner] Handler desktop no encontrado: $app_file"
    return 0
  fi

  update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
  xdg-mime default xaloc-afirma-handler.desktop x-scheme-handler/afirma >/dev/null 2>&1 || true
  xdg-mime default xaloc-afirma-handler.desktop x-scheme-handler/xalocafirma >/dev/null 2>&1 || true
  echo "[playwright-runner] x-scheme-handler/afirma y x-scheme-handler/xalocafirma registrados con xaloc-afirma-handler.desktop"
}

start_autofirma_always_on() {
  local always_on="${XALOC_AUTOFIRMA_ALWAYS_ON:-1}"
  if [[ "${always_on,,}" != "1" && "${always_on,,}" != "true" && "${always_on,,}" != "yes" && "${always_on,,}" != "on" ]]; then
    echo "[playwright-runner] AutoFirma always-on desactivado (XALOC_AUTOFIRMA_ALWAYS_ON=$always_on)."
    return 0
  fi

  if ! command -v autofirma >/dev/null 2>&1; then
    echo "[playwright-runner] Aviso: binario 'autofirma' no encontrado, no se arranca always-on."
    return 0
  fi

  if pgrep -f "(^|/| )autofirma( |$)" >/dev/null 2>&1; then
    echo "[playwright-runner] AutoFirma ya estaba en ejecución (always-on)."
    return 0
  fi

  echo "[playwright-runner] Arrancando AutoFirma en modo always-on..."
  nohup autofirma >/tmp/autofirma-always-on.log 2>&1 &
  sleep 1
  if pgrep -f "(^|/| )autofirma( |$)" >/dev/null 2>&1; then
    echo "[playwright-runner] AutoFirma iniciado en background."
  else
    echo "[playwright-runner] Aviso: no se pudo confirmar proceso AutoFirma tras arranque."
  fi
}

if [[ ! -f "$CERT_PATH" ]]; then
  echo "[playwright-runner] Certificado no encontrado: $CERT_PATH"
  if [[ "$CERT_REQUIRED" == "1" ]]; then
    echo "[playwright-runner] PLAYWRIGHT_CERT_REQUIRED=1 => abortando arranque."
    exit 1
  fi
  echo "[playwright-runner] Continuando sin certificado (PLAYWRIGHT_CERT_REQUIRED!=1)."
  exec "$@"
fi

mkdir -p "$NSS_DB_DIR" "$GLOBAL_NSS_DB_DIR"
write_autoselect_policy
write_afirma_protocol_policy
register_afirma_xdg_handler
start_autofirma_always_on

if [[ ! -f "$NSS_DB_DIR/cert9.db" ]]; then
  certutil -N --empty-password -d "sql:$NSS_DB_DIR"
fi
if [[ ! -f "$GLOBAL_NSS_DB_DIR/cert9.db" ]]; then
  certutil -N --empty-password -d "sql:$GLOBAL_NSS_DB_DIR"
fi

# Importar PKCS#12 en NSS (perfil Chromium usado por Playwright).
# Si PLAYWRIGHT_CERT_PASSWORD no existe, intentamos password vacío.
p12_pass_file="$(mktemp)"
db_pass_file="$(mktemp)"
trap 'rm -f "$p12_pass_file" "$db_pass_file"' EXIT
if [[ -n "${PLAYWRIGHT_CERT_PASSWORD:-}" ]]; then
  printf "%s" "${PLAYWRIGHT_CERT_PASSWORD}" > "$p12_pass_file"
else
  # pk12util necesita un fichero no vacio para password vacio.
  printf "\n" > "$p12_pass_file"
fi
printf "\n" > "$db_pass_file"

import_ok=0
for db in "$NSS_DB_DIR" "$GLOBAL_NSS_DB_DIR"; do
  if pk12util -i "$CERT_PATH" -d "sql:$db" -w "$p12_pass_file" -k "$db_pass_file" >/tmp/pk12util.log 2>&1; then
    echo "[playwright-runner] Certificado importado en NSS db=$db"
    import_ok=1
  else
    echo "[playwright-runner] Aviso importando certificado en db=$db:"
    cat /tmp/pk12util.log || true
  fi
done

if [[ "$import_ok" != "1" && "$CERT_REQUIRED" == "1" ]]; then
  echo "[playwright-runner] PLAYWRIGHT_CERT_REQUIRED=1 => abortando arranque por error de import en todas las DB."
  exit 1
fi

echo "[playwright-runner] Certificados disponibles en NSS perfil ($NSS_DB_DIR):"
certutil -L -d "sql:$NSS_DB_DIR" || true
echo "[playwright-runner] Certificados disponibles en NSS global ($GLOBAL_NSS_DB_DIR):"
certutil -L -d "sql:$GLOBAL_NSS_DB_DIR" || true

exec "$@"
