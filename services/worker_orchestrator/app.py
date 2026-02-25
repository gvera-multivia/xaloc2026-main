from __future__ import annotations

import asyncio
import logging

from core.worker.consumer import run_worker_loop


async def _main_async() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [worker-orchestrator] %(levelname)s %(message)s")
    await run_worker_loop()


def main() -> None:
    asyncio.run(_main_async())


if __name__ == "__main__":
    main()
