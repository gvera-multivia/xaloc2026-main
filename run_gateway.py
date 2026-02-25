from __future__ import annotations

import asyncio
import os
import sys

import uvicorn
from dotenv import load_dotenv


if __name__ == "__main__":
    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    load_dotenv()
    host = (os.getenv("API_GATEWAY_HOST") or "0.0.0.0").strip() or "0.0.0.0"
    port = int((os.getenv("API_GATEWAY_PORT") or "8080").strip() or "8080")
    print(f"API Gateway listening on http://{host}:{port}")
    uvicorn.run("services.api_gateway.app:app", host=host, port=port, reload=False)
