import os
import logging
from typing import Optional

try:
    import redis.asyncio as redis
except ImportError:
    redis = None

logger = logging.getLogger("redis_client")

_redis_client: Optional["redis.Redis"] = None
_redis_pool: Optional["redis.ConnectionPool"] = None

def get_redis_client() -> Optional["redis.Redis"]:
    """
    Returns a singleton Redis client instance.
    If 'redis' package is not installed or REDIS_URL is not set/valid, returns None.
    """
    global _redis_client, _redis_pool

    if redis is None:
        logger.warning("Redis package not installed. Redis features will be disabled.")
        return None

    if _redis_client is not None:
        return _redis_client

    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0").strip()
    if not redis_url:
        logger.warning("REDIS_URL is empty. Redis features will be disabled.")
        return None

    try:
        # Use a connection pool for better performance
        if _redis_pool is None:
            _redis_pool = redis.ConnectionPool.from_url(redis_url, decode_responses=True)

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
