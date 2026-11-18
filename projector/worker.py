"""
Projector Worker — three-phase Neo4j writer.

Fixes CHANGELOG.md ⚠️ limitations 1 and 2:
  1. Phase 0 consumes stream_raw to seed Repository/Actor/Issue/PR/Commit nodes
     *before* Phase 1 writes TextUnit nodes that MATCH on those parents.
  2. Phases run sequentially within each pipeline stage so signals never arrive
     before their TextUnit exists.

Phases:
  Phase 0  stream_raw    → seed artefact nodes (Repository, Actor, Issue, PR, Commit)
  Phase 1  stream_units  → write TextUnit nodes + HAS_TEXT edges
  Phase 2  stream_signals → write Signal / LexicalMarker / RhetoricalFigure /
                             ClassifierVerdict nodes

run_pipeline.py controls which phases execute:
  Stage 1 (extractor stage): run Phase 0, then Phase 1
  Stage 2 (annotation stage): run Phase 2

See FRAMEWORK_DESIGN.md §5 Module 4; BUILD_SPEC.md §6 Milestone 3.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from bson import ObjectId
from pymongo.errors import AutoReconnect

from broker import get_broker
from progress import Progress
from projector.graph_projector import GraphProjector
from settings import settings
from storage import make_mongo_client

logger = logging.getLogger(__name__)

SIGNAL_BATCH_SIZE = settings.projector_signal_batch_size


# ─────────────────────────────────────────────────────────────────────────────
# Public entry points
# ─────────────────────────────────────────────────────────────────────────────


async def run_projector_stage1() -> None:
    """
    Legacy sequential entry point: Phase 0 (seed artefact nodes from stream_raw)
    then Phase 1 (write TextUnit nodes from stream_units).
    """
    async with _projector_stage1() as (projector, db):
        logger.info("Projector Stage 1 started.")
        await _phase0_seed_artefacts(projector, db)
        await _phase1_project_units(projector)
        logger.info("Projector Stage 1 complete.")


async def run_projector_phase0() -> None:
    """
    Phase 0 alone (Tier 3, CHANGELOG 2026-08-16): seeds artefact nodes from
    stream_raw. run_pipeline.py runs this BEFORE starting the extractor so
    stream_units never buffers the whole corpus in Redis — the Redis OOM root
    cause. Phase 1 then consumes stream_units live with trim.
    """
    async with _projector_stage1() as (projector, db):
        logger.info("Projector Phase 0 started.")
        await _phase0_seed_artefacts(projector, db)
        logger.info("Projector Phase 0 complete.")


async def run_projector_phase1() -> None:
    """
    Phase 1 alone: writes TextUnit nodes from stream_units (consumed with trim).
    run after run_projector_phase0 + the extractor, so parents always exist.
    """
    async with _projector_stage1() as (projector, _db):
        logger.info("Projector Phase 1 started.")
        await _phase1_project_units(projector)
        logger.info("Projector Phase 1 complete.")


def _projector_stage1():
    """Shared GraphProjector + Mongo setup/teardown for the stage-1 phases."""

    class _Ctx:
        async def __aenter__(self):
            self.projector = await GraphProjector.create()
            self.mongo = make_mongo_client()
            self.db = self.mongo[settings.mongo_db_name]
            return (self.projector, self.db)

        async def __aexit__(self, *exc):
            await self.projector.close()
            self.mongo.close()

    return _Ctx()


async def run_projector_stage2(stop_event: asyncio.Event | None = None) -> None:
    """Stage 2: write Signals. Runs after Stage 1 is complete."""
    projector = await GraphProjector.create()
    try:
        logger.info("Projector Stage 2 started.")
        await _phase2_project_signals(projector, stop_event=stop_event)
        logger.info("Projector Stage 2 complete.")
    finally:
        await projector.close()


# ─────────────────────────────────────────────────────────────────────────────
# Phase 0
# ─────────────────────────────────────────────────────────────────────────────


async def _phase0_seed_artefacts(projector: GraphProjector, db: Any) -> None:
    """
    Read stream_raw; fetch each batch's docs from MongoDB in one $in find per
    collection; upsert the artefact nodes in per-family UNWIND statements.

    Batched end-to-end (CHANGELOG 2026-08-19): the previous per-event path did
    one Mongo find_one + one Neo4j round trip per event (9.9M events = ~10M of
    each), which collapsed to ~150/s under connection churn. Batching amortizes
    all three hops — Redis XREAD, Mongo fetch, Neo4j UNWIND — across
    `phase0_batch_size` events. Guarantees every parent node exists before
    Phase 1 writes TextUnits.
    """
    broker = await get_broker()
    total_raw = await broker.stream_length(settings.stream_raw)
    prog = Progress("Seed artefacts", total=total_raw)
    logger.info("Phase 0: seeding artefact nodes from %s", settings.stream_raw)
    count = 0
    async for batch in broker.read_all(settings.stream_raw, batch_size=settings.phase0_batch_size):
        docs = await _fetch_batch_docs(db, batch)
        await projector.upsert_artefacts_batch(batch, docs)
        count += len(batch)
        prog.add(len(batch))
        prog.maybe_log()
    prog.finish()
    logger.info("Phase 0 complete: %d raw events processed.", count)


async def _fetch_batch_docs(db: Any, batch: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """
    Fetch every doc referenced by `batch` in ONE $in find per collection.

    Events span several raw_* collections (issues / pull_requests / commits /
    emails / external), so the batch's mongo_ids are grouped by `_collection_for`
    and each group is fetched with a single indexed `_id` lookup — 1–3 round
    trips per batch instead of one per event.

    Transient pymongo `AutoReconnect` (the parent of `_OperationCancelled`,
    which killed earlier runs) is retried a few times with backoff rather than
    silently dropping the artefact — the old `_seed_one` warn-and-return lost
    records whenever Mongo connections were torn down mid-read.
    """
    ids_by_collection: dict[str, list[str]] = {}
    for event in batch:
        collection = _collection_for(event.get("item_type", ""))
        ids_by_collection.setdefault(collection, []).append(event["mongo_id"])

    docs: dict[str, dict[str, Any]] = {}
    for collection, ids in ids_by_collection.items():
        found: list[dict[str, Any]] = []
        for attempt in range(3):
            try:
                found = (
                    await db[collection]
                    .find({"_id": {"$in": [ObjectId(i) for i in ids]}})
                    .to_list(length=None)
                )
                break
            except AutoReconnect:
                if attempt == 2:
                    raise
                await asyncio.sleep(0.5 * (attempt + 1))
        for doc in found:
            docs[str(doc["_id"])] = doc
    return docs


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1
# ─────────────────────────────────────────────────────────────────────────────


async def _phase1_project_units(projector: GraphProjector) -> None:
    """Consume stream_units → write TextUnit nodes.

    Batched via GraphProjector.upsert_text_units_batch (CHANGELOG 2026-08-16):
    one UNWIND statement per ~100 units instead of one round trip per unit, so
    Phase 1 drains faster than the extractor produces and stream_units never
    buffers the corpus in Redis. On a batch failure, falls back to the per-unit
    upsert so one bad unit does not drop a whole batch (preserving the previous
    per-unit error semantics).
    """
    broker = await get_broker()
    prog = Progress("Project TextUnits")  # live-queue mode (stream still trimming)
    logger.info("Phase 1: writing TextUnit nodes from %s", settings.stream_units)
    count = 0
    buffer: list[dict[str, Any]] = []

    async def _write_batch(sub: list[dict[str, Any]]) -> None:
        nonlocal count
        try:
            await projector.upsert_text_units_batch(sub)
            count += len(sub)
        except Exception as exc:
            logger.error("Phase 1: batch failed (%d units): %s", len(sub), exc)
            for event in sub:
                try:
                    if login := event.get("author_login"):
                        await projector.upsert_actor(login)
                    await projector.upsert_text_unit(event)
                    count += 1
                except Exception as exc2:
                    logger.error("Phase 1: failed TextUnit %s: %s", event.get("text_unit_id"), exc2)

    async for batch in broker.read_all(settings.stream_units, trim=True):
        buffer.extend(batch)
        while len(buffer) >= 100:
            sub, buffer = buffer[:100], buffer[100:]
            await _write_batch(sub)
        prog.add(len(batch))
        prog.maybe_log(remaining=await broker.stream_length(settings.stream_units))
    if buffer:
        await _write_batch(buffer)
    prog.finish()
    logger.info("Phase 1 complete: %d TextUnit nodes written.", count)


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2
# ─────────────────────────────────────────────────────────────────────────────


async def _phase2_project_signals(
    projector: GraphProjector,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Consume stream_signals → batch-write Signal nodes and related nodes.

    When `stop_event` is provided (Stage 2 concurrent mode, CHANGELOG
    2026-08-21), the consumer keeps draining while producers are alive — it
    exits only once producers signal completion AND the stream is empty.
    Without it (standalone drain, --skip-annotate) it keeps the legacy
    2-idle-rounds exhaustion exit.
    """
    broker = await get_broker()
    prog = Progress("Project Signals")  # live-queue mode (stream still trimming)
    logger.info("Phase 2: writing Signal nodes from %s", settings.stream_signals)
    total = 0
    # Rolling flush-latency timer (CHANGELOG 2026-08-23): the projector is the
    # Stage-2 bottleneck when the annotator produces faster than Neo4j can
    # write. Median ms per flush is the instrument that shows whether the write
    # path (and thus the page cache / batch size) is keeping up.
    flush_times: list[float] = []
    _flush_log_last = asyncio.get_event_loop().time()

    async for batch in broker.read_all(
        settings.stream_signals,
        batch_size=SIGNAL_BATCH_SIZE,
        trim=True,
        stop_event=stop_event,
    ):
        # read_all trims a yielded batch only when this loop requests the next
        # one. Commit the whole yielded batch first: if Neo4j raises, iteration
        # stops and Redis retains these entries for recovery.
        t0 = asyncio.get_event_loop().time()
        total += await _flush(projector, batch)
        flush_times.append(asyncio.get_event_loop().time() - t0)
        prog.add(len(batch))
        now = asyncio.get_event_loop().time()
        prog.maybe_log(remaining=await broker.stream_length(settings.stream_signals))
        if now - _flush_log_last >= 30.0:
            _flush_log_last = now
            if flush_times:
                ordered = sorted(flush_times)
                mid = len(ordered) // 2
                median_ms = (
                    ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2
                ) * 1000
                logger.info(
                    "Project Signals flush latency (median of %d): %.0f ms/flush",
                    len(flush_times),
                    median_ms,
                )
                flush_times = []

    prog.finish()
    logger.info("Phase 2 complete: %d signals written.", total)


async def _flush(projector: GraphProjector, signals: list[dict[str, Any]]) -> int:
    """Commit one Redis batch; errors propagate so read_all does not trim it."""
    await projector.upsert_signals_batch(signals)
    logger.debug("Flushed %d signals.", len(signals))
    return len(signals)


# ─────────────────────────────────────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────────────────────────────────────


def _collection_for(item_type: str) -> str:
    return {
        "repository": "raw_repositories",
        "issue": "raw_issues",
        "pull_request": "raw_pull_requests",
        "commit": "raw_commits",
        "email": "raw_emails",
        # v0.8 external artefacts all live in raw_external, keyed on record_id.
        "jira_issue": "raw_external",
        "bugzilla_issue": "raw_external",
        "chat_message": "raw_external",
        "so_post": "raw_external",
    }.get(item_type, "raw_misc")
