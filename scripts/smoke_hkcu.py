"""
smoke_hkcu.py — Wrapper de smoke para entornos Windows sin admin.

Antes de lanzar el browser aplica AutoSelectCertificateForUrls en HKCU
(sin administrador) para que el navegador seleccione el certificado de
certmgr.msc automáticamente al llegar al login.

No modifica ningún flujo de sites/. Solo añade el paso de política HKCU
y delega en el main_*_payload_by_id correspondiente.

Uso:
    python scripts/smoke_hkcu.py --site atc --id 12345 --run-flow
    python scripts/smoke_hkcu.py --site terrassa --id 12345 --run-flow
    python scripts/smoke_hkcu.py --site atc --id 12345 --dump-only
    python scripts/smoke_hkcu.py --site atc --id 12345 --run-flow --cn "OTRO CN EXACTO"
"""
from __future__ import annotations

import argparse
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


def _apply_hkcu_policy(cn: str) -> None:
    """
    Escribe AutoSelectCertificateForUrls en HKCU via PowerShell.
    No requiere administrador. Opera siempre sobre el perfil del usuario actual.
    """
    if not _PS1.exists():
        print(f"[smoke_hkcu] AVISO: no se encuentra {_PS1} — se omite paso de política.", file=sys.stderr)
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
    if result.returncode != 0:
        print(f"[smoke_hkcu] AVISO: política HKCU retornó código {result.returncode}.", file=sys.stderr)
        if result.stderr.strip():
            print(result.stderr.strip(), file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Smoke con política HKCU (sin admin) para certificados de certmgr.msc."
    )
    parser.add_argument("--site", required=True, choices=list(_SITES),
                        help="Site a ejecutar: atc, terrassa, diputacio-bcn, redsara, valencia")
    parser.add_argument("--id", required=True, type=int,
                        help="idRecurso en SQL Server")
    parser.add_argument("--cn", default=_DEFAULT_CN,
                        help="CN exacto del certificado en certmgr.msc (por defecto: CN del proyecto)")
    parser.add_argument("--run-flow", action="store_true",
                        help="Ejecutar flujo Playwright completo")
    parser.add_argument("--dump-only", action="store_true",
                        help="Solo volcar JSON de validación sin abrir browser")
    args, extra = parser.parse_known_args()

    print(f"[smoke_hkcu] site={args.site} id={args.id} run_flow={args.run_flow}")
    print(f"[smoke_hkcu] CN={args.cn!r}")
    print("[smoke_hkcu] Lanzando main con Edge + CLI arg + perfil efímero...")

    target = _REPO_ROOT / _SITES[args.site]
    cmd = [sys.executable, str(target), "--id", str(args.id)]
    if args.run_flow:
        cmd.append("--run-flow")
    if args.dump_only:
        cmd.append("--dump-only")
    cmd.extend(extra)

    # GPO corporativa bloquea HKCU\SOFTWARE\Policies\ y Chromium bundled no lee
    # certmgr.msc. Usamos Edge (lee Windows cert store) + CLI arg forzado +
    # perfil efímero limpio (evita crash por corrupción que eliminaría el CLI arg).
    env = os.environ.copy()
    env["XALOC_CERT_AUTOSELECT_VIA_POLICY"] = "0"
    # Edge para acceder a certmgr.msc (Windows certificate store).
    env["XALOC_BROWSER_CHANNEL"] = "msedge"
    # Perfil efímero: evita reutilizar profiles/worker potencialmente corrupto.
    # Sin corrupción no hay crash-retry → el CLI arg no se elimina.
    env["XALOC_EPHEMERAL_PROFILE"] = "1"

    sys.exit(subprocess.run(cmd, cwd=str(_REPO_ROOT), env=env).returncode)


if __name__ == "__main__":
    main()
