#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_ENV_FILE = ROOT_DIR / ".env"
DEFAULT_COMPOSE_FILE = ROOT_DIR / "infra" / "docker" / "docker-compose.microservices.yml"


def _compose_base_cmd(env_file: Path, compose_file: Path) -> list[str]:
    return [
        "docker",
        "compose",
        "--env-file",
        str(env_file),
        "-f",
        str(compose_file),
    ]


def _run_cmd(cmd: list[str], *, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        text=True,
        capture_output=True,
        check=check,
    )


def _check_docker_daemon() -> str | None:
    """Devuelve un mensaje de error si Docker no esta disponible o el daemon no responde."""
    try:
        proc = _run_cmd(["docker", "info"])
    except FileNotFoundError:
        return "No se encontro el ejecutable 'docker' en PATH."
    except subprocess.TimeoutExpired:
        return "Docker no responde dentro del tiempo esperado."

    if proc.returncode == 0:
        return None

    stderr = (proc.stderr or "").strip()
    stdout = (proc.stdout or "").strip()
    combined = "\n".join(part for part in (stderr, stdout) if part).strip()
    lowered = combined.lower()

    if "dockerdesktoplinuxengine" in lowered or "cannot connect to the docker daemon" in lowered:
        return (
            "Docker Desktop no esta arrancado o el daemon de Docker no responde. "
            "Abre Docker Desktop y espera a que el motor Linux quede en estado Running."
        )
    if "the system cannot find the file specified" in lowered:
        return (
            "Docker Desktop no esta arrancado o el pipe del daemon no existe. "
            "Abre Docker Desktop y espera a que el motor Linux arranque."
        )
    if combined:
        return f"Docker no esta disponible: {combined}"
    return "Docker no esta disponible."


def _compose_ps_json(env_file: Path, compose_file: Path) -> list[dict[str, Any]]:
    cmd = _compose_base_cmd(env_file, compose_file) + ["ps", "--format", "json"]
    proc = _run_cmd(cmd)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "docker compose ps failed")
    raw = (proc.stdout or "").strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            return [parsed]
    except json.JSONDecodeError:
        # Docker Compose en Windows suele devolver NDJSON:
        # una línea JSON por servicio, no un array.
        services: list[dict[str, Any]] = []
        bad_lines: list[str] = []
        for line in raw.splitlines():
            txt = line.strip()
            if not txt:
                continue
            try:
                item = json.loads(txt)
                if isinstance(item, dict):
                    services.append(item)
            except json.JSONDecodeError:
                bad_lines.append(txt)
        if services:
            return services
        preview = "\n".join(bad_lines[:3]) if bad_lines else raw[:500]
        raise RuntimeError(f"No se pudo parsear 'docker compose ps --format json': {preview}")
    return []


def _is_bad_state(state: str) -> bool:
    s = (state or "").strip().lower()
    # "restarting" can be transient right after compose up; let timeout logic decide.
    return any(x in s for x in ("exited", "dead", "created"))


def _is_ready(service: dict[str, Any]) -> bool:
    state = str(service.get("State") or "")
    status = str(service.get("Status") or "")
    health = str(service.get("Health") or "").strip().lower()
    if not state:
        state = status
    s = state.strip().lower()
    if not s.startswith("running"):
        return False
    # If the service exposes health, require healthy to avoid returning too early.
    if health:
        return health == "healthy"
    if "health" in status.lower():
        return "healthy" in status.lower()
    return True


def _summarize_services(services: list[dict[str, Any]]) -> str:
    if not services:
        return "(sin servicios)"
    chunks: list[str] = []
    for item in services:
        name = str(item.get("Service") or item.get("Name") or "?")
        state = str(item.get("State") or item.get("Status") or "?")
        health = str(item.get("Health") or "").strip()
        if health:
            chunks.append(f"{name}={state}({health})")
        else:
            chunks.append(f"{name}={state}")
    return ", ".join(chunks)


def _wait_for_start(env_file: Path, compose_file: Path, timeout: int, interval: float) -> int:
    deadline = time.time() + timeout
    while True:
        services = _compose_ps_json(env_file, compose_file)
        if services and all(_is_ready(s) for s in services):
            print("[OK] Todos los servicios estan arriba y saludables.")
            print(f"[STATE] {_summarize_services(services)}")
            return 0
        if any(
            _is_bad_state(str(s.get("State") or s.get("Status") or ""))
            or str(s.get("Health") or "").strip().lower() == "unhealthy"
            for s in services
        ):
            print("[FAILED] Uno o mas servicios estan en estado fallido.")
            print(f"[STATE] {_summarize_services(services)}")
            return 2
        if time.time() >= deadline:
            print("[TIMEOUT] No llegaron a estado listo dentro del tiempo limite.")
            print(f"[STATE] {_summarize_services(services)}")
            return 3
        summary = _summarize_services(services)
        if "minio" in summary.lower():
             print(f"[WAIT] Esperando arranque (MinIO integrado)... {summary}")
        else:
             print(f"[WAIT] Esperando arranque... {summary}")
        time.sleep(interval)


def _wait_for_stop(env_file: Path, compose_file: Path, timeout: int, interval: float) -> int:
    deadline = time.time() + timeout
    while True:
        services = _compose_ps_json(env_file, compose_file)
        if not services:
            print("[OK] Stack apagado. No hay contenedores del compose activos.")
            return 0
        if time.time() >= deadline:
            print("[TIMEOUT] Aun hay contenedores activos tras el tiempo limite.")
            print(f"[STATE] {_summarize_services(services)}")
            return 3
        print(f"[WAIT] Esperando apagado... {_summarize_services(services)}")
        time.sleep(interval)


def _check_client_docs_mount(
    env_file: Path,
    compose_file: Path,
    *,
    service: str,
    path: str,
) -> int:
    cmd = _compose_base_cmd(env_file, compose_file) + [
        "exec",
        "-T",
        service,
        "sh",
        "-lc",
        f"ls -1 {path}",
    ]
    proc = _run_cmd(cmd)
    if proc.returncode != 0:
        msg = proc.stderr.strip() or proc.stdout.strip() or "error ejecutando check de montaje"
        print(f"[FAILED] No se puede validar compartido de clientes en {service}:{path}: {msg}")
        return 2

    entries = [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]
    expected_alpha_dirs = {"0-9 (NUMEROS)", "A-C", "D-E", "F-J", "K-L", "M-O", "P-U", "V-Z"}
    visible = {name for name in entries if name in expected_alpha_dirs}
    if not visible:
        print(f"[FAILED] Compartido de clientes no montado o vacío en runtime: {service}:{path}")
        print(f"[STATE] Entradas visibles: {', '.join(entries[:20]) if entries else '(sin entradas)'}")
        return 2

    print(f"[OK] Compartido de clientes montado en {service}:{path} ({len(entries)} entradas).")
    return 0


def _run_compose_action(env_file: Path, compose_file: Path, action: str) -> None:
    if action == "start":
        cmd = _compose_base_cmd(env_file, compose_file) + ["up", "-d"]
    elif action == "stop":
        cmd = _compose_base_cmd(env_file, compose_file) + ["down"]
    elif action == "build":
        cmd = _compose_base_cmd(env_file, compose_file) + ["build"]
    else:
        raise ValueError(f"Accion no soportada: {action}")
    print(f"[CMD] {' '.join(cmd)}")
    if action == "build":
        # Build streams lots of binary/UTF-8 output — run it directly to avoid encoding issues
        rc = subprocess.call(cmd)
        if rc != 0:
            raise RuntimeError(f"docker compose build fallo con returncode={rc}")
        return
    proc = _run_cmd(cmd)
    if proc.stdout and proc.stdout.strip():
        print(proc.stdout.strip())
    if proc.returncode != 0:
        if proc.stderr and proc.stderr.strip():
            print(proc.stderr.strip(), file=sys.stderr)
        raise RuntimeError(f"docker compose {action} fallo con returncode={proc.returncode}")


def _run_multi_compose_action(env_file: Path, compose_files: list[Path], action: str) -> None:
    for cf in compose_files:
        _run_compose_action(env_file, cf, action)


def _wait_multi_for_start(env_file: Path, compose_files: list[Path], timeout: int, interval: float) -> int:
    for cf in compose_files:
        print(f"[WAIT] Verificando arranque compose: {cf}")
        rc = _wait_for_start(env_file, cf, timeout=timeout, interval=interval)
        if rc != 0:
            return rc
    return 0


def _wait_multi_for_stop(env_file: Path, compose_files: list[Path], timeout: int, interval: float) -> int:
    for cf in compose_files:
        print(f"[WAIT] Verificando apagado compose: {cf}")
        rc = _wait_for_stop(env_file, cf, timeout=timeout, interval=interval)
        if rc != 0:
            return rc
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Controla stack Docker Compose (start/stop/restart) con espera activa.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--start", action="store_true", help="Levanta el stack y espera hasta estado listo.")
    mode.add_argument("--stop", action="store_true", help="Apaga el stack y espera hasta que no queden contenedores.")
    mode.add_argument("--restart", action="store_true", help="Reinicia el stack (down + up) y espera listo.")
    mode.add_argument("--restart-rebuild", action="store_true", help="Reinicia el stack con rebuild (down + build + up) y espera listo.")
    parser.add_argument("--timeout", type=int, default=600, help="Timeout total en segundos (default: 600).")
    parser.add_argument("--interval", type=float, default=3.0, help="Intervalo de polling en segundos (default: 3).")
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE), help="Ruta a .env.")
    parser.add_argument("--compose-file", default=str(DEFAULT_COMPOSE_FILE), help="Ruta a docker-compose.")
    parser.add_argument(
        "--skip-client-docs-check",
        action="store_true",
        help="No valida montaje del compartido de clientes tras start/restart.",
    )
    parser.add_argument(
        "--client-docs-service",
        default="worker-orchestrator-service",
        help="Servicio a usar para validar /mnt/clientes (default: worker-orchestrator-service).",
    )
    parser.add_argument(
        "--client-docs-path",
        default="/mnt/clientes",
        help="Ruta dentro del contenedor para validar compartido de clientes (default: /mnt/clientes).",
    )
    args = parser.parse_args()

    env_file = Path(args.env_file).resolve()
    compose_file = Path(args.compose_file).resolve()
    if not env_file.exists():
        print(f"[ERROR] No existe env file: {env_file}", file=sys.stderr)
        return 1
    if not compose_file.exists():
        print(f"[ERROR] No existe compose file: {compose_file}", file=sys.stderr)
        return 1
    compose_files: list[Path] = [compose_file]

    docker_error = _check_docker_daemon()
    if docker_error is not None:
        print(f"[ERROR] {docker_error}", file=sys.stderr)
        return 1

    try:
        if args.start:
            _run_multi_compose_action(env_file, compose_files, "start")
            rc = _wait_multi_for_start(env_file, compose_files, timeout=args.timeout, interval=args.interval)
            if rc != 0:
                return rc
            if not args.skip_client_docs_check:
                return _check_client_docs_mount(
                    env_file,
                    compose_file,
                    service=args.client_docs_service,
                    path=args.client_docs_path,
                )
            return 0
        if args.stop:
            _run_multi_compose_action(env_file, compose_files, "stop")
            return _wait_multi_for_stop(env_file, compose_files, timeout=args.timeout, interval=args.interval)
        if args.restart_rebuild:
            # restart-rebuild: down + build + up
            _run_multi_compose_action(env_file, compose_files, "stop")
            rc = _wait_multi_for_stop(env_file, compose_files, timeout=args.timeout, interval=args.interval)
            if rc != 0:
                return rc
            print("[BUILD] Rebuilding images...")
            _run_multi_compose_action(env_file, compose_files, "build")
            _run_multi_compose_action(env_file, compose_files, "start")
            rc = _wait_multi_for_start(env_file, compose_files, timeout=args.timeout, interval=args.interval)
            if rc != 0:
                return rc
            if not args.skip_client_docs_check:
                return _check_client_docs_mount(
                    env_file,
                    compose_file,
                    service=args.client_docs_service,
                    path=args.client_docs_path,
                )
            return 0
        # restart
        _run_multi_compose_action(env_file, compose_files, "stop")
        rc = _wait_multi_for_stop(env_file, compose_files, timeout=args.timeout, interval=args.interval)
        if rc != 0:
            return rc
        _run_multi_compose_action(env_file, compose_files, "start")
        rc = _wait_multi_for_start(env_file, compose_files, timeout=args.timeout, interval=args.interval)
        if rc != 0:
            return rc
        if not args.skip_client_docs_check:
            return _check_client_docs_mount(
                env_file,
                compose_file,
                service=args.client_docs_service,
                path=args.client_docs_path,
            )
        return 0
    except RuntimeError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
