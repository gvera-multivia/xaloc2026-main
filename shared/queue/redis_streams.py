from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Optional


@dataclass(slots=True)
class RedisStreamMessage:
    stream: str
    message_id: str
    fields: dict[str, str]


class RedisStreamsClient:
    def __init__(self, redis_client, logger: Optional[logging.Logger] = None):
        self.redis = redis_client
        self.logger = logger or logging.getLogger("redis_streams")

    async def ensure_group(self, *, stream: str, group: str) -> None:
        try:
            await self.redis.xgroup_create(name=stream, groupname=group, id="$", mkstream=True)
        except Exception as exc:
            text = str(exc).upper()
            if "BUSYGROUP" in text:
                return
            raise

    async def publish_json(self, *, stream: str, payload: dict[str, Any], maxlen: Optional[int] = None) -> str:
        mapping: dict[str, str] = {
            key: value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            for key, value in (payload or {}).items()
        }
        kwargs: dict[str, Any] = {}
        if maxlen and int(maxlen) > 0:
            kwargs["maxlen"] = int(maxlen)
            kwargs["approximate"] = True
        return await self.redis.xadd(stream, fields=mapping, **kwargs)

    async def read_group(
        self,
        *,
        stream: str,
        group: str,
        consumer: str,
        block_ms: int = 5000,
        count: int = 1,
    ) -> Optional[RedisStreamMessage]:
        rows = await self.redis.xreadgroup(
            groupname=group,
            consumername=consumer,
            streams={stream: ">"},
            count=max(1, int(count)),
            block=max(1, int(block_ms)),
        )
        if not rows:
            return None

        stream_name, messages = rows[0]
        if not messages:
            return None
        message_id, fields = messages[0]
        normalized = {str(k): str(v) for k, v in (fields or {}).items()}
        return RedisStreamMessage(
            stream=str(stream_name),
            message_id=str(message_id),
            fields=normalized,
        )

    async def ack(self, *, stream: str, group: str, message_id: str) -> int:
        return int(await self.redis.xack(stream, group, message_id) or 0)

    async def delete(self, *, stream: str, message_id: str) -> int:
        return int(await self.redis.xdel(stream, message_id) or 0)

