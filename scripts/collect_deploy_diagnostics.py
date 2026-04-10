#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def _run(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, text=True, capture_output=True)
    text = []
    text.append(f"$ {' '.join(cmd)}")
    text.append(f"exit_code={proc.returncode}")
    if proc.stdout:
        text.append("stdout:")
        text.append(proc.stdout.strip())
    if proc.stderr:
        text.append("stderr:")
        text.append(proc.stderr.strip())
    return "\n".join(part for part in text if part).strip() + "\n"


def _write(output_dir: Path, name: str, content: str) -> None:
    (output_dir / name).write_text(content, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Recolecta diagnostico basico tras un deploy fallido.")
    parser.add_argument("--repo-path", required=True)
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--compose-file", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--log-tail", type=int, default=200)
    args = parser.parse_args()

    repo_path = Path(args.repo_path).resolve()
    env_file = Path(args.env_file).resolve()
    compose_file = Path(args.compose_file).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    base = [
        "docker",
        "compose",
        "--env-file",
        str(env_file),
        "-f",
        str(compose_file),
    ]

    _write(output_dir, "pwd.txt", str(repo_path) + "\n")
    _write(output_dir, "git-status.txt", _run(["git", "-C", str(repo_path), "status", "--short", "--branch"]))
    _write(output_dir, "git-head.txt", _run(["git", "-C", str(repo_path), "rev-parse", "HEAD"]))
    _write(output_dir, "docker-info.txt", _run(["docker", "info"]))
    _write(output_dir, "compose-ps.txt", _run(base + ["ps"]))
    _write(output_dir, "compose-ps-json.txt", _run(base + ["ps", "--format", "json"]))
    _write(output_dir, "compose-logs.txt", _run(base + ["logs", "--tail", str(args.log_tail), "--no-color"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
