#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True)


def _fail(msg: str) -> int:
    print(f"[ERROR] {msg}", file=sys.stderr)
    return 1


def _check_command(name: str) -> int:
    path = shutil.which(name)
    if not path:
        return _fail(f"No se encontro '{name}' en PATH.")
    print(f"[OK] {name}: {path}")
    return 0


def _check_docker() -> int:
    proc = _run(["docker", "info"])
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        return _fail(f"Docker no esta disponible o el daemon no responde. {detail}")
    print("[OK] Docker daemon accesible.")
    proc = _run(["docker", "compose", "version"])
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        return _fail(f"Docker Compose no esta disponible. {detail}")
    version = (proc.stdout or proc.stderr or "").strip()
    print(f"[OK] {version}")
    return 0


def _check_path(path: Path, *, label: str, expect_file: bool | None = None) -> int:
    if not path.exists():
        return _fail(f"No existe {label}: {path}")
    if expect_file is True and not path.is_file():
        return _fail(f"{label} no es un fichero: {path}")
    if expect_file is False and not path.is_dir():
        return _fail(f"{label} no es un directorio: {path}")
    print(f"[OK] {label}: {path}")
    return 0


def _check_git_repo(repo_path: Path) -> int:
    proc = _run(["git", "-C", str(repo_path), "rev-parse", "--is-inside-work-tree"])
    if proc.returncode != 0 or (proc.stdout or "").strip() != "true":
        detail = (proc.stderr or proc.stdout or "").strip()
        return _fail(f"Ruta de repo invalida para git: {repo_path}. {detail}")
    proc = _run(["git", "-C", str(repo_path), "remote", "get-url", "origin"])
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        return _fail(f"No se pudo leer remote origin en {repo_path}. {detail}")
    print(f"[OK] Git origin: {(proc.stdout or '').strip()}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Prechecks minimos para deploy en runner self-hosted.")
    parser.add_argument("--repo-path", required=True, help="Ruta fija del checkout persistente en la VM.")
    parser.add_argument("--env-file", required=True, help="Ruta del .env operativo en la VM.")
    parser.add_argument("--compose-file", required=True, help="Ruta del docker-compose operativo.")
    args = parser.parse_args()

    repo_path = Path(args.repo_path).resolve()
    env_file = Path(args.env_file).resolve()
    compose_file = Path(args.compose_file).resolve()
    stack_control = repo_path / "scripts" / "stack_control.py"

    for cmd in ("git", "docker", "python3"):
        rc = _check_command(cmd)
        if rc != 0:
            return rc

    rc = _check_docker()
    if rc != 0:
        return rc

    for path, label, expect_file in (
        (repo_path, "repo-path", False),
        (env_file, "env-file", True),
        (compose_file, "compose-file", True),
        (stack_control, "stack_control.py", True),
    ):
        rc = _check_path(path, label=label, expect_file=expect_file)
        if rc != 0:
            return rc

    rc = _check_git_repo(repo_path)
    if rc != 0:
        return rc

    proc = _run(["python3", str(stack_control), "--help"])
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        return _fail(f"stack_control.py no es ejecutable. {detail}")
    print("[OK] stack_control.py accesible.")
    print("[READY] Prechecks completados.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
