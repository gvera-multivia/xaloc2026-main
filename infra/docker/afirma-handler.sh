#!/usr/bin/env bash
set -euo pipefail

uri="${1:-}"
log_file="${XALOC_AFIRMA_URI_LOG:-/tmp/xaloc_afirma_uri.log}"
latest_file="${XALOC_AFIRMA_URI_LATEST:-/tmp/xaloc_afirma_uri.latest}"

if [[ -n "$uri" ]]; then
  ts="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  printf "%s\t%s\n" "$ts" "$uri" >> "$log_file"
  printf "%s" "$uri" > "$latest_file"
fi

# Importante: no abrir UI externa. Solo capturar URI para firma programatica.
exit 0
