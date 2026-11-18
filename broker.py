"""
Thin async wrapper around Redis Streams.

Used by:
  - AsyncGitHubMiner  → publishes to stream_raw
  - miner.gmane_ingester → publishes to stream_raw
  - extractor.worker  → publishes to stream_units
  - annotators.worker → publishes to stream_signals
  - projector.worker  → reads stream_units + stream_signals

All consumers use the simple XREAD/XREADGROUP pattern.
No fancy consumer-group acknowledgement for v0 — pipeline is run to completion
on a single machine, restart is cheap.
"""

from __future__ import annotations

import asyncio
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

    async def publish_many(self, stream: str, events: list[dict[str, Any]]) -> None:
        """
        Append many events to `stream` in a single round trip via a Redis
        pipeline, instead of one XADD per event.

        Ingest-time throughput matters here: at corpus scale, awaiting one
        XADD per record serializes a full network round trip per email. A
        pipeline batches N XADDs into one write/flush, which is the same
        latency-hiding trick as the Mongo bulk_write below. Order is
        preserved within the pipeline.
        """
        if not events:
            return
        pipe = self._client.pipeline(transaction=False)
        for event in events:
            pipe.xadd(stream, {"payload": json.dumps(event, default=str)})
        await pipe.execute()

    async def read_all(
        self,
        stream: str,
        batch_size: int = 100,
        block_ms: int = 2000,
        trim: bool = False,
        stop_event: asyncio.Event | None = None,
    ) -> AsyncIterator[list[dict[str, Any]]]:
        """
        Yield batches of events from `stream` from the beginning.
        Blocks at the tail until no new messages arrive for `block_ms` ms,
        then stops — designed for run-to-completion research runs.

        If `trim=True`, each batch's messages are deleted (XDEL) once the
        consumer has finished processing them — i.e. on the next iteration.
        This reclaims Redis memory as the stream is drained. Only enable trim
        for SINGLE-consumer streams; deleting entries another consumer still
        needs would lose data.

        `stop_event` (CHANGELOG 2026-08-21, Milestone C): producer-aware exit.
        When provided, idle rounds no longer terminate the consumer — it keeps
        blocking at the tail until the event is SET *and* the stream is drained.
        This lets Phase 2 run concurrently with producers that may be silent for
        seconds (model loading) without the premature-exit failure of 2026-08-18.
        Without it the old 2-idle-rounds exit is preserved for standalone drains.

        Yields lists of parsed event dicts.
        """
        last_id = "0"
        idle_rounds = 0
        pending_trim: list[bytes] = []  # ids yielded but not yet processed

        while True:
            # The consumer has finished the previously-yielded batch by now —
            # safe to delete those entries and free their memory.
            if trim and pending_trim:
                await self._client.xdel(stream, *pending_trim)
                pending_trim = []

            entries = await self._client.xread({stream: last_id}, count=batch_size, block=block_ms)
            if not entries:
                # No messages for block_ms — end of stream. With a stop_event,
                # only exit once the producers have signalled they are done AND
                # the stream is empty (nothing left to drain); otherwise keep
                # waiting — producers may legitimately be silent for a while.
                if stop_event is not None:
                    if stop_event.is_set() and await self.stream_length(stream) == 0:
                        if trim and pending_trim:
                            await self._client.xdel(stream, *pending_trim)
                        logger.info("Stream %s drained; producers done. Stopping consumer.", stream)
                        return
                    idle_rounds = 0
                    continue
                # Old behaviour: two idle rounds = exhausted.
                idle_rounds += 1
                if idle_rounds >= 2:
                    if trim and pending_trim:
                        await self._client.xdel(stream, *pending_trim)
                    logger.info("Stream %s appears exhausted. Stopping consumer.", stream)
                    return
                continue

            idle_rounds = 0
            for _stream_name, messages in entries:
                batch = []
                ids: list[bytes] = []
                for msg_id, fields in messages:
                    last_id = msg_id
                    ids.append(msg_id)
                    try:
                        batch.append(json.loads(fields[b"payload"]))
                    except (KeyError, json.JSONDecodeError) as exc:
                        logger.warning("Skipping malformed message %s: %s", msg_id, exc)
                # Trim the IDs regardless of whether any payload parsed: a batch
                # of ALL-malformed messages must still be consumed, or the stream
                # never drains and stop_event-aware read_all hangs forever.
                if trim:
                    pending_trim = ids
                if batch:
                    yield batch

    async def stream_length(self, stream: str) -> int:
        return await self._client.xlen(stream)

    async def set(self, key: str, value: str) -> None:
        """Store a string scalar (used for the annotator resume high-water mark)."""
        await self._client.set(key, value)

    async def get(self, key: str) -> str | None:
        """Read a string scalar previously stored with set(); None if absent."""
        raw = await self._client.get(key)
        return raw.decode() if isinstance(raw, bytes) else raw

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
