"""
MongoDB client factory + bounded-concurrency helper + bulk-write helper.

Centralises connection settings so every worker that reads the raw data lake
uses the same resilient configuration, and provides a bounded gather so a large
backlog cannot flood the connection pool.

Why the client config exists: processing a large backlog (tens of thousands of
events) with an unbounded asyncio.gather fires hundreds of concurrent find_one
calls. That exhausts the Mongo pool; a single hiccup pauses it; and a saturated
event loop then starves the driver's server-monitor coroutine so the pool never
recovers ("connection pool paused"). Bounding concurrency keeps the loop healthy.
See CHANGELOG 2026-04-25.

Why bulk_upsert exists: per-record `update_one(..., upsert=True)` round-trips
to Mongo for every single document, which is the dominant cost of ingestion at
corpus scale (see CHANGELOG — ingestion throughput rework). Batching many
UpdateOne operations into one bulk_write call amortizes the round trip across
hundreds or thousands of documents.
"""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Iterable, TypeVar

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection
from pymongo import InsertOne, UpdateOne
from pymongo.errors import BulkWriteError

from settings import settings

T = TypeVar("T")


def make_mongo_client() -> AsyncIOMotorClient:
    """
    MongoDB client tuned for large-backlog processing.

    - maxPoolSize caps connections so we don't open hundreds at once.
    - retryReads/retryWrites let transient failures retry instead of bubbling up.
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
        retryWrites=True,
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


async def bulk_upsert_on_key(
    collection: AsyncIOMotorCollection,
    docs: list[dict[str, Any]],
    key_field: str,
    *,
    use_insert_for_fresh_load: bool = False,
) -> list[dict[str, Any]]:
    """
    Write many documents in a single round trip instead of one upsert per doc,
    and return exactly the subset that were NEWLY written — each with its real
    Mongo `_id` already populated on the dict — so the caller can build
    pointer events with zero extra round trips and without re-publishing for
    documents that already existed from a prior run.

    Two modes, chosen by `use_insert_for_fresh_load`:

    - False (default): one UpdateOne(upsert=True) per doc, keyed on
      `key_field` (e.g. "urn" — NOT "_id", since an update's $set may never
      touch an existing document's _id), sent in one bulk_write(ordered=False).
      Idempotent, matching the original per-record semantics, just batched.
      `BulkWriteResult.upserted_ids` maps operation index -> the _id Mongo
      generated, but ONLY for operations that triggered an actual insert
      (confirmed against pymongo's bulk write result contract) — so a doc
      that already existed is correctly excluded from the returned list. This
      is a deliberate improvement over the original per-record code, which
      published a pointer event on every re-run regardless of whether the
      document was new (see CHANGELOG — ingestion throughput rework).

    - True: one InsertOne per doc via bulk_write, for a first-time bulk load
      into an (assumed) empty/append-only collection. Verified directly
      against pymongo internals (_Bulk.add_insert): when a document has no
      `_id`, pymongo generates one CLIENT-SIDE with `bson.ObjectId()` and
      mutates the document dict in place *before* any network call — so after
      this call every surviving doc already carries its real `_id`, with zero
      extra round trips. Duplicate `key_field` values (e.g. re-running over
      already-ingested files) surface as write errors on a unique index over
      `key_field`; those are caught and excluded from the returned list, not
      fatal. Requires a unique index on `key_field` to still exist and be
      live during the load, or duplicates silently create extra documents
      instead of being rejected.

    `ordered=False` lets Mongo execute every operation even when some fail
    (duplicate-key errors), instead of stopping at the first error.
    """
    if not docs:
        return []

    if use_insert_for_fresh_load:
        ops = [InsertOne(doc) for doc in docs]
        try:
            await collection.bulk_write(ops, ordered=False)
            # Every surviving doc was mutated in place with its real _id.
            return docs
        except BulkWriteError as exc:
            write_errors = exc.details.get("writeErrors", [])
            other = [e for e in write_errors if e.get("code") != 11000]
            if other:
                raise
            failed_idx = {e["index"] for e in write_errors}
            return [d for i, d in enumerate(docs) if i not in failed_idx]

    ops = [
        UpdateOne({key_field: doc[key_field]}, {"$set": doc}, upsert=True)
        for doc in docs
    ]
    result = await collection.bulk_write(ops, ordered=False)
    new_docs: list[dict[str, Any]] = []
    for idx, new_id in (result.upserted_ids or {}).items():
        docs[idx]["_id"] = new_id
        new_docs.append(docs[idx])
    return new_docs
