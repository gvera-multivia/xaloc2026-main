import os
import logging
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

try:
    import redis.asyncio as redis
except ImportError:
    redis = None

logger = logging.getLogger("redis_client")

_redis_client: Optional["redis.Redis"] = None
_redis_pool: Optional["redis.ConnectionPool"] = None

_DEFAULT_SOCKET_TIMEOUT_SECONDS = 30.0
_DEFAULT_CONNECT_TIMEOUT_SECONDS = 5.0


def _positive_float_env(name: str, default: float) -> float:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning("%s=%r no es un numero valido; se usara %.1fs.", name, raw, default)
        return default
    if value <= 0:
        logger.warning("%s=%r debe ser mayor que cero; se usara %.1fs.", name, raw, default)
        return default
    return value


def _normalize_redis_url(redis_url: str) -> str:
    raw = str(redis_url or "").strip()
    if not raw or os.name != "nt":
        return raw

    parsed = urlsplit(raw)
    if (parsed.hostname or "").strip().lower() != "redis":
        return raw

    port = f":{parsed.port}" if parsed.port else ""
    userinfo = ""
    if parsed.username:
        userinfo = parsed.username
        if parsed.password is not None:
            userinfo += f":{parsed.password}"
        userinfo += "@"

    netloc = f"{userinfo}localhost{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))

def get_redis_client() -> Optional["redis.Redis"]:
    """
    Returns a singleton Redis client instance.
    If 'redis' package is not installed or REDIS_URL is not set/valid, returns None.
    """
    global _redis_client, _redis_pool

    redis_enabled = (os.getenv("REDIS_ENABLED") or "0").strip().lower() in {"1", "true", "yes", "on"}
    if not redis_enabled:
        return None

    if redis is None:
        logger.warning("Redis package not installed. Redis features will be disabled.")
        return None

    if _redis_client is not None:
        return _redis_client

    redis_url = _normalize_redis_url((os.getenv("REDIS_URL") or "").strip())
    if not redis_url:
        logger.warning("REDIS_ENABLED=1 pero REDIS_URL vacío. Redis desactivado.")
        return None

    try:
        # Use a connection pool for better performance
        if _redis_pool is None:
            # redis-py 8.x may install a five-second read timeout when none is
            # supplied.  That races with our blocking XREADGROUP calls (the
            # validator blocks for five seconds by default), turning an empty
            # poll into a process-killing TimeoutError.  Keep the read timeout
            # comfortably above every blocking read currently used by the
            # services, while retaining a short connection timeout.
            socket_timeout = _positive_float_env(
                "REDIS_SOCKET_TIMEOUT_SECONDS",
                _DEFAULT_SOCKET_TIMEOUT_SECONDS,
            )
            socket_connect_timeout = _positive_float_env(
                "REDIS_CONNECT_TIMEOUT_SECONDS",
                _DEFAULT_CONNECT_TIMEOUT_SECONDS,
            )
            _redis_pool = redis.ConnectionPool.from_url(
                redis_url,
                decode_responses=True,
                socket_timeout=socket_timeout,
                socket_connect_timeout=socket_connect_timeout,
            )

        _redis_client = redis.Redis(connection_pool=_redis_pool)
        logger.info(f"Redis client initialized with URL: {redis_url}")
        return _redis_client
    except Exception as e:
        logger.error(f"Failed to initialize Redis client: {e}")
        return None

async def close_redis_client():
    """
    Closes the Redis client and connection pool.
    """
    global _redis_client, _redis_pool
    if _redis_client:
        await _redis_client.close()
        _redis_client = None
    if _redis_pool:
        await _redis_pool.disconnect()
        _redis_pool = None
    logger.info("Redis client closed.")
