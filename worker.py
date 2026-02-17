import asyncio
import sys
from core.worker.utils import apply_url_cert_config
from core.worker.consumer import run_worker_loop
from core.process_launcher import setup_asyncio_policy

if __name__ == "__main__":
    setup_asyncio_policy()

    try:
        apply_url_cert_config()
        asyncio.run(run_worker_loop())
    except KeyboardInterrupt:
        pass
