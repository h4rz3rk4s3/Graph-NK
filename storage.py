"""
MongoDB client factory + bounded-concurrency helper.

Centralises connection settings so every worker that reads the raw data lake
uses the same resilient configuration, and provides a bounded gather so a large
backlog cannot flood the connection pool.

Why this exists: processing a large backlog (tens of thousands of events) with
an unbounded asyncio.gather fires hundreds of concurrent find_one calls. That
exhausts the Mongo pool; a single hiccup pauses it; and a saturated event loop
then starves the driver's server-monitor coroutine so the pool never recovers
("connection pool paused"). Bounding concurrency keeps the loop healthy.
See CHANGELOG 2026-04-25.
"""
from __future__ import annotations

import asyncio
from typing import Awaitable, Iterable, TypeVar

from motor.motor_asyncio import AsyncIOMotorClient

from settings import settings

T = TypeVar("T")


def make_mongo_client() -> AsyncIOMotorClient:
    """
    MongoDB client tuned for large-backlog processing.

    - maxPoolSize caps connections so we don't open hundreds at once.
    - retryReads lets transient read failures retry instead of bubbling up.
    - generous server-selection / socket timeouts tolerate brief stalls.
    """
    return AsyncIOMotorClient(
        settings.mongo_uri,
        maxPoolSize=settings.mongo_max_pool_size,
        minPoolSize=0,
        serverSelectionTimeoutMS=settings.mongo_server_selection_timeout_ms,
        waitQueueTimeoutMS=settings.mongo_server_selection_timeout_ms,
        socketTimeoutMS=settings.mongo_socket_timeout_ms,
        connectTimeoutMS=20000,
        retryReads=True,
    )


async def gather_bounded(
    coros: Iterable[Awaitable[T]], limit: int
) -> list[T | BaseException]:
    """
    Like asyncio.gather(..., return_exceptions=True) but never runs more than
    `limit` coroutines concurrently. Prevents flooding the Mongo pool and
    starving the driver's background server-monitor coroutine.
    """
    sem = asyncio.Semaphore(limit)

    async def _run(coro: Awaitable[T]) -> T:
        async with sem:
            return await coro

    return await asyncio.gather(*[_run(c) for c in coros], return_exceptions=True)
