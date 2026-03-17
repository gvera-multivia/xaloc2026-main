from __future__ import annotations

import json
import logging
import os
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
        # IMPORTANT:
        # Default to "0-0" so a newly created consumer-group can consume
        # already enqueued entries (prevents silent skips when service restarts).
        start_id = (os.getenv("QUEUE_STREAM_GROUP_START_ID") or "0-0").strip() or "0-0"
        try:
            await self.redis.xgroup_create(name=stream, groupname=group, id=start_id, mkstream=True)
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
        try:
            rows = await self.redis.xreadgroup(
                groupname=group,
                consumername=consumer,
                streams={stream: ">"},
                count=max(1, int(count)),
                block=max(1, int(block_ms)),
            )
        except Exception as exc:
            text = str(exc).upper()
            if "NOGROUP" in text:
                # Auto-heal when stream/group was deleted externally.
                await self.ensure_group(stream=stream, group=group)
                rows = await self.redis.xreadgroup(
                    groupname=group,
                    consumername=consumer,
                    streams={stream: ">"},
                    count=max(1, int(count)),
                    block=max(1, int(block_ms)),
                )
            else:
                raise
        if not rows:
            return None

        stream_name, messages = rows[0]
        if not messages:
            return None
        message_id, fields = messages[0]
        normalized = {self._to_text(k): self._to_text(v) for k, v in (fields or {}).items()}
        return RedisStreamMessage(
            stream=self._to_text(stream_name),
            message_id=self._to_text(message_id),
            fields=normalized,
        )

    async def autoclaim_one(
        self,
        *,
        stream: str,
        group: str,
        consumer: str,
        min_idle_ms: int,
        start_id: str = "0-0",
    ) -> Optional[RedisStreamMessage]:
        try:
            result = await self.redis.xautoclaim(
                name=stream,
                groupname=group,
                consumername=consumer,
                min_idle_time=max(1, int(min_idle_ms)),
                start_id=start_id,
                count=1,
            )
        except Exception as exc:
            text = str(exc).upper()
            if "NOGROUP" in text:
                await self.ensure_group(stream=stream, group=group)
                return None
            raise

        if not result:
            return None

        # redis-py: (next_start_id, [(id, fields), ...], [deleted_ids?])
        messages = []
        try:
            messages = result[1] if len(result) > 1 else []
        except Exception:
            messages = []
        if not messages:
            return None

        message_id, fields = messages[0]
        normalized = {self._to_text(k): self._to_text(v) for k, v in (fields or {}).items()}
        return RedisStreamMessage(
            stream=self._to_text(stream),
            message_id=self._to_text(message_id),
            fields=normalized,
        )

    async def ack(self, *, stream: str, group: str, message_id: str) -> int:
        return int(await self.redis.xack(stream, group, message_id) or 0)

    async def delete(self, *, stream: str, message_id: str) -> int:
        return int(await self.redis.xdel(stream, message_id) or 0)

    @staticmethod
    def _to_text(value: Any) -> str:
        if isinstance(value, bytes):
            try:
                return value.decode("utf-8", errors="replace")
            except Exception:
                return str(value)
        return str(value)
