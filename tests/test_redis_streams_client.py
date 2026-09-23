from __future__ import annotations

import asyncio

from shared.queue.redis_streams import RedisStreamsClient


RedisTimeout = type("TimeoutError", (Exception,), {"__module__": "redis.exceptions"})


class _TimeoutRedis:
    async def xreadgroup(self, **kwargs):
        raise RedisTimeout("Timeout reading from redis:6379")


def test_blocking_read_timeout_is_treated_as_empty_poll() -> None:
    streams = RedisStreamsClient(_TimeoutRedis())

    message = asyncio.run(
        streams.read_group(
            stream="candidates",
            group="validator_group",
            consumer="validator-test",
            block_ms=5000,
        )
    )

    assert message is None
