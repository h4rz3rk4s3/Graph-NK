"""
Thin async wrapper around Redis Streams.

Used by:
  - AsyncGitHubMiner  → publishes to stream_raw
  - extractor.worker  → publishes to stream_units
  - annotators.worker → publishes to stream_signals
  - projector.worker  → reads stream_units + stream_signals

All consumers use the simple XREAD/XREADGROUP pattern.
No fancy consumer-group acknowledgement for v0 — pipeline is run to completion
on a single machine, restart is cheap.
"""
from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

import redis.asyncio as aioredis

from settings import settings

logger = logging.getLogger(__name__)

_broker: "RedisBroker | None" = None


class RedisBroker:
    """Lightweight publish/consume interface over Redis Streams."""

    def __init__(self, client: aioredis.Redis) -> None:
        self._client = client

    async def publish(self, stream: str, event: dict[str, Any]) -> None:
        """Serialize event as JSON and append to stream."""
        await self._client.xadd(stream, {"payload": json.dumps(event, default=str)})

    async def read_all(
        self,
        stream: str,
        batch_size: int = 100,
        block_ms: int = 2000,
    ) -> AsyncIterator[list[dict[str, Any]]]:
        """
        Yield batches of events from `stream` from the beginning.
        Blocks at the tail until no new messages arrive for `block_ms` ms,
        then stops — designed for run-to-completion research runs.

        Yields lists of parsed event dicts.
        """
        last_id = "0"
        idle_rounds = 0

        while True:
            entries = await self._client.xread({stream: last_id}, count=batch_size, block=block_ms)
            if not entries:
                # No messages for block_ms — treat as end of stream for this run
                idle_rounds += 1
                if idle_rounds >= 2:
                    logger.info("Stream %s appears exhausted. Stopping consumer.", stream)
                    return
                continue

            idle_rounds = 0
            for _stream_name, messages in entries:
                batch = []
                for msg_id, fields in messages:
                    last_id = msg_id
                    try:
                        batch.append(json.loads(fields[b"payload"]))
                    except (KeyError, json.JSONDecodeError) as exc:
                        logger.warning("Skipping malformed message %s: %s", msg_id, exc)
                if batch:
                    yield batch

    async def stream_length(self, stream: str) -> int:
        return await self._client.xlen(stream)

    async def close(self) -> None:
        await self._client.aclose()


async def get_broker() -> RedisBroker:
    """Return (and lazily create) the singleton RedisBroker."""
    global _broker
    if _broker is None:
        client = aioredis.from_url(settings.redis_url, decode_responses=False)
        _broker = RedisBroker(client)
        logger.info("RedisBroker connected to %s", settings.redis_url)
    return _broker
