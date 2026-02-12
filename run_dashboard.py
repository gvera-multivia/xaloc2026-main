from __future__ import annotations

import os
import socket

import uvicorn
from dotenv import load_dotenv


def find_free_port(host: str = "127.0.0.1", start_port: int = 8787, end_port: int = 8999) -> int:
    for port in range(start_port, end_port + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, port))
                return port
            except OSError:
                continue
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


if __name__ == "__main__":
    load_dotenv()
    host = os.getenv("DASHBOARD_HOST", "127.0.0.1")
    start_port = int(os.getenv("DASHBOARD_PORT_START", "8787"))
    end_port = int(os.getenv("DASHBOARD_PORT_END", "8999"))
    fixed_port = (os.getenv("DASHBOARD_PORT_FIXED") or "").strip()
    if fixed_port:
        port = int(fixed_port)
    else:
        port = find_free_port(host=host, start_port=start_port, end_port=end_port)
        os.environ["DASHBOARD_PORT_FIXED"] = str(port)
    print(f"Dashboard listening on http://{host}:{port}")
    uvicorn.run("dashboard_api:app", host=host, port=port, reload=False)
