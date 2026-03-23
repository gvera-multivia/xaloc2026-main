"""
smoke_hkcu.py â€” Wrapper de smoke para entornos Windows sin admin.

Antes de lanzar el browser aplica AutoSelectCertificateForUrls en HKCU
(sin administrador) para que el navegador seleccione el certificado de
certmgr.msc automÃ¡ticamente al llegar al login.

No modifica ningÃºn flujo de sites/. Solo aÃ±ade el paso de polÃ­tica HKCU
y delega en el main_*_payload_by_id correspondiente.

Uso:
    python scripts/smoke_hkcu.py --site atc --id 12345 --run-flow
    python scripts/smoke_hkcu.py --site terrassa --id 12345 --run-flow
    python scripts/smoke_hkcu.py --site atc --id 12345 --dump-only
    python scripts/smoke_hkcu.py --site atc --id 12345 --run-flow --cn "OTRO CN EXACTO"
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
_PS1 = Path(__file__).parent / "url-cert-config.ps1"

_SITES: dict[str, str] = {
    "atc":           "main_atc_payload_by_id.py",
    "terrassa":      "main_terrassa_payload_by_id.py",
    "diputacio-bcn": "main_diputacio_bcn_payload_by_id.py",
    "redsara":       "main_redsara_payload_by_id.py",
    "valencia":      "main_valencia_payload_by_id.py",
}

_DEFAULT_CN = "35059210B MARIA TERESA MORENTE (R: B62798210)"
_SITE_CERT_PATTERNS: dict[str, list[str]] = {
    # Terrassa autentica en aoberta y redirige por valid.aoc.cat/cert.valid.aoc.cat.
    "terrassa": [
        "https://aoberta.terrassa.cat/*",
        "https://[*.]terrassa.cat/*",
        "https://[*.]aoc.cat/*",
        "https://valid.aoc.cat:443/*",
        "https://cert.valid.aoc.cat:443/*",
        "https://[*.]gencat.cat/*",
        "https://[*.]extranet.gencat.cat/*",
    ],
}


def _apply_hkcu_policy(cn: str) -> None:
    """
    Escribe AutoSelectCertificateForUrls en HKCU via PowerShell.
    No requiere administrador. Opera siempre sobre el perfil del usuario actual.
    """
    if not _PS1.exists():
        print(f"[smoke_hkcu] AVISO: no se encuentra {_PS1} â€” se omite paso de polÃ­tica.", file=sys.stderr)
        return

    result = subprocess.run(
        [
            "powershell",
            "-ExecutionPolicy", "Bypass",
            "-NoProfile",
            "-File", str(_PS1),
            "-CN", cn,
        ],
        capture_output=True,
        text=True,
    )
    if result.stdout.strip():
        print(f"[smoke_hkcu] {result.stdout.strip()}")
    if result.stderr.strip():
        print(f"[smoke_hkcu] STDERR politica HKCU:\n{result.stderr.strip()}", file=sys.stderr)
    if result.returncode != 0:
        print(f"[smoke_hkcu] AVISO: polÃ­tica HKCU retornÃ³ cÃ³digo {result.returncode}.", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Smoke con polÃ­tica HKCU (sin admin) para certificados de certmgr.msc."
    )
    parser.add_argument("--site", required=True, choices=list(_SITES),
                        help="Site a ejecutar: atc, terrassa, diputacio-bcn, redsara, valencia")
    parser.add_argument("--id", required=True, type=int,
                        help="idRecurso en SQL Server")
    parser.add_argument("--cn", default=os.getenv("CERTIFICADO_CN", _DEFAULT_CN),
                        help="CN exacto del certificado en certmgr.msc (por defecto: CN del proyecto)")
    parser.add_argument("--run-flow", action="store_true",
                        help="Ejecutar flujo Playwright completo")
    parser.add_argument("--dump-only", action="store_true",
                        help="Solo volcar JSON de validaciÃ³n sin abrir browser")
    args, extra = parser.parse_known_args()

    print(f"[smoke_hkcu] site={args.site} id={args.id} run_flow={args.run_flow}")
    print(f"[smoke_hkcu] CN={args.cn!r}")
    print("[smoke_hkcu] Lanzando main con Edge + CLI arg + perfil efÃ­mero...")
    target = _REPO_ROOT / _SITES[args.site]
    cmd = [sys.executable, str(target), "--id", str(args.id)]
    if args.run_flow:
        cmd.append("--run-flow")
    if args.dump_only:
        cmd.append("--dump-only")
    cmd.extend(extra)

    # GPO corporativa bloquea HKCU\SOFTWARE\Policies\ y Chromium bundled no lee
    # certmgr.msc. Usamos Edge (lee Windows cert store) + CLI arg forzado +
    # perfil efÃ­mero limpio (evita crash por corrupciÃ³n que eliminarÃ­a el CLI arg).
    env = os.environ.copy()
    env["CERTIFICADO_CN"] = args.cn
    env["XALOC_WINDOWS_CERT_HINT"] = args.cn
    # Forzar que no use PFX/client_certificates: solo certmgr.msc + autoselect por CLI.
    env["PLAYWRIGHT_USE_CLIENT_CERTIFICATES"] = "0"
    env["XALOC_CERT_AUTOSELECT_VIA_POLICY"] = "0"
    site_patterns = _SITE_CERT_PATTERNS.get(args.site)
    if site_patterns:
        cert_filter = {"SUBJECT": {"CN": args.cn}} if args.cn.strip() else {}
        rules = [{"pattern": p, "filter": cert_filter} for p in site_patterns]
        env["XALOC_CERT_AUTOSELECT_RULES_JSON"] = json.dumps(
            rules, ensure_ascii=False, separators=(",", ":")
        )
    # Edge para acceder a certmgr.msc (Windows certificate store).
    env["XALOC_BROWSER_CHANNEL"] = "msedge"
    # Perfil efÃ­mero: evita reutilizar profiles/worker potencialmente corrupto.
    # Sin corrupciÃ³n no hay crash-retry â†’ el CLI arg no se elimina.
    env["XALOC_EPHEMERAL_PROFILE"] = "1"

    sys.exit(subprocess.run(cmd, cwd=str(_REPO_ROOT), env=env).returncode)


if __name__ == "__main__":
    main()

