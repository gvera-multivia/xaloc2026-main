import logging
import re
from typing import Optional

import aiohttp

logger = logging.getLogger("worker")

LOGIN_URL = "http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/login"


def extract_csrf_token(html: str) -> Optional[str]:
    match = re.search(r'name="_token"\\s+value="([^"]+)"', html)
    return match.group(1) if match else None


async def create_authenticated_session(
    email: str,
    password: str,
    login_url: str = LOGIN_URL,
    timeout_seconds: int = 30
) -> aiohttp.ClientSession:
    session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout_seconds))
    try:
        async with session.get(login_url) as response:
            login_page = await response.text()

        token = extract_csrf_token(login_page)
        if not token:
            raise RuntimeError("CSRF token not found in login page.")

        data = {
            "_token": token,
            "email": email,
            "password": password,
            "remember": "on",
        }

        async with session.post(login_url, data=data, allow_redirects=False) as response:
            if response.status in (302, 303):
                logger.info("XVIA login succeeded.")
                return session
            raise RuntimeError(f"Login failed with status {response.status}.")
    except Exception:
        await session.close()
        raise
