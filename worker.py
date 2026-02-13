import asyncio
import sys
from core.worker.utils import apply_url_cert_config
from core.worker.consumer import run_worker_loop

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    try:
        apply_url_cert_config()
        asyncio.run(run_worker_loop())
    except KeyboardInterrupt:
        pass
