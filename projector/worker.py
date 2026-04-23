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
from motor.motor_asyncio import AsyncIOMotorClient

from broker import get_broker
from projector.graph_projector import GraphProjector
from settings import settings

logger = logging.getLogger(__name__)

SIGNAL_BATCH_SIZE = 100
SIGNAL_FLUSH_SEC  = 2.0


# ─────────────────────────────────────────────────────────────────────────────
# Public entry points
# ─────────────────────────────────────────────────────────────────────────────

async def run_projector_stage1() -> None:
    """
    Stage 1: Phase 0 (seed artefact nodes from stream_raw) then
    Phase 1 (write TextUnit nodes from stream_units). Sequential.
    """
    projector = await GraphProjector.create()
    mongo     = AsyncIOMotorClient(settings.mongo_uri)
    db        = mongo[settings.mongo_db_name]
    try:
        logger.info("Projector Stage 1 started.")
        await _phase0_seed_artefacts(projector, db)
        await _phase1_project_units(projector)
        logger.info("Projector Stage 1 complete.")
    finally:
        await projector.close()
        mongo.close()


async def run_projector_stage2() -> None:
    """Stage 2: write Signals. Runs after Stage 1 is complete."""
    projector = await GraphProjector.create()
    try:
        logger.info("Projector Stage 2 started.")
        await _phase2_project_signals(projector)
        logger.info("Projector Stage 2 complete.")
    finally:
        await projector.close()


# ─────────────────────────────────────────────────────────────────────────────
# Phase 0
# ─────────────────────────────────────────────────────────────────────────────

async def _phase0_seed_artefacts(projector: GraphProjector, db: Any) -> None:
    """
    Read stream_raw; fetch each doc from MongoDB; upsert artefact node.
    Guarantees every parent node exists before Phase 1 writes TextUnits.
    """
    broker = await get_broker()
    logger.info("Phase 0: seeding artefact nodes from %s", settings.stream_raw)
    count = 0
    async for batch in broker.read_all(settings.stream_raw):
        results = await asyncio.gather(
            *[_seed_one(projector, db, e) for e in batch],
            return_exceptions=True,
        )
        for r in results:
            if isinstance(r, Exception):
                logger.error("Phase 0 error: %s", r)
        count += len(batch)
    logger.info("Phase 0 complete: %d raw events processed.", count)


async def _seed_one(projector: GraphProjector, db: Any, event: dict[str, Any]) -> None:
    item_type    = event.get("item_type", "")
    item_subtype = event.get("item_subtype", item_type)
    repo         = event.get("repo_name", "")
    mongo_id     = event.get("mongo_id")
    collection   = _collection_for(item_type)

    try:
        doc = await db[collection].find_one({"_id": ObjectId(mongo_id)})
    except Exception as exc:
        logger.warning("Phase 0: bad mongo_id %s: %s", mongo_id, exc)
        return

    if doc is None:
        logger.warning("Phase 0: doc not found: %s / %s", collection, mongo_id)
        return

    await projector.upsert_artefact_from_raw(item_type, item_subtype, repo, doc)


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1
# ─────────────────────────────────────────────────────────────────────────────

async def _phase1_project_units(projector: GraphProjector) -> None:
    """Consume stream_units → write TextUnit nodes."""
    broker = await get_broker()
    logger.info("Phase 1: writing TextUnit nodes from %s", settings.stream_units)
    count = 0
    async for batch in broker.read_all(settings.stream_units):
        for event in batch:
            try:
                if login := event.get("author_login"):
                    await projector.upsert_actor(login)
                await projector.upsert_text_unit(event)
                count += 1
            except Exception as exc:
                logger.error(
                    "Phase 1: failed TextUnit %s: %s",
                    event.get("text_unit_id"), exc,
                )
    logger.info("Phase 1 complete: %d TextUnit nodes written.", count)


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2
# ─────────────────────────────────────────────────────────────────────────────

async def _phase2_project_signals(projector: GraphProjector) -> None:
    """Consume stream_signals → batch-write Signal nodes and related nodes."""
    broker = await get_broker()
    logger.info("Phase 2: writing Signal nodes from %s", settings.stream_signals)
    buffer: list[dict[str, Any]] = []
    last_flush = asyncio.get_event_loop().time()
    total = 0

    async for batch in broker.read_all(settings.stream_signals):
        buffer.extend(batch)
        now = asyncio.get_event_loop().time()
        if len(buffer) >= SIGNAL_BATCH_SIZE or (now - last_flush) >= SIGNAL_FLUSH_SEC:
            total += await _flush(projector, buffer)
            buffer = []
            last_flush = now

    if buffer:
        total += await _flush(projector, buffer)
    logger.info("Phase 2 complete: %d signals written.", total)


async def _flush(projector: GraphProjector, signals: list[dict[str, Any]]) -> int:
    try:
        await projector.upsert_signals_batch(signals)
        logger.debug("Flushed %d signals.", len(signals))
        return len(signals)
    except Exception as exc:
        logger.error("Signal flush failed (%d): %s", len(signals), exc)
        return 0


# ─────────────────────────────────────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────────────────────────────────────

def _collection_for(item_type: str) -> str:
    return {
        "repository":   "raw_repositories",
        "issue":        "raw_issues",
        "pull_request": "raw_pull_requests",
        "commit":       "raw_commits",
    }.get(item_type, "raw_misc")
