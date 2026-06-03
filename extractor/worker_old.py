"""
Module 2 — Extractor Worker (async I/O layer).

Consumes events from stream_raw, fetches full documents from MongoDB,
dispatches to the appropriate extract_from_* function, and publishes
TextUnit events to stream_units.

See FRAMEWORK_DESIGN.md §5 Module 2 for design rationale.
"""
from __future__ import annotations

import asyncio
import dataclasses
import logging
from typing import Any

from broker import get_broker
from extractor.text_unit_extractor import (
    TextUnit,
    extract_from_commit,
    extract_from_issue,
    extract_from_pull_request,
)
from settings import settings
from storage import gather_bounded, make_mongo_client

logger = logging.getLogger(__name__)


async def run_extractor() -> None:
    """
    Main entry point. Reads stream_raw to exhaustion and publishes
    TextUnit events to stream_units.
    Called from scripts/run_pipeline.py.
    """
    broker = await get_broker()
    mongo = make_mongo_client()
    db = mongo[settings.mongo_db_name]

    logger.info("Extractor worker started. Consuming %s", settings.stream_raw)

    async for batch in broker.read_all(settings.stream_raw):
        results = await gather_bounded(
            (_process_event(event, db, broker) for event in batch),
            settings.mongo_fetch_concurrency,
        )
        for r in results:
            if isinstance(r, Exception):
                logger.error("Event processing failed: %s", r)

    mongo.close()
    logger.info("Extractor worker finished.")


async def _process_event(
    event: dict[str, Any],
    db: Any,
    broker: Any,
) -> None:
    """Fetch raw document from MongoDB and publish its TextUnit events."""
    item_type    = event.get("item_type", "")
    item_subtype = event.get("item_subtype", item_type)
    repo         = event.get("repo_name", "")
    mongo_id     = event.get("mongo_id")

    # Fetch full document from Mongo
    collection_name = _collection_for(item_type)
    from bson import ObjectId
    doc = await db[collection_name].find_one({"_id": ObjectId(mongo_id)})
    if doc is None:
        logger.warning("Document not found: mongo_id=%s collection=%s", mongo_id, collection_name)
        return

    # Dispatch to the right extractor
    units: list[TextUnit] = []
    if item_subtype == "pull_request":
        units = extract_from_pull_request(doc, repo)
    elif item_subtype == "issue":
        units = extract_from_issue(doc, repo)
    elif item_type == "commit":
        units = extract_from_commit(doc, repo)
    else:
        logger.debug("Skipping item_type=%s (no extractor)", item_type)
        return

    # Publish one event per TextUnit
    for unit in units:
        await broker.publish(settings.stream_units, dataclasses.asdict(unit))

    logger.debug(
        "Published %d TextUnits for %s/%s",
        len(units), item_type, event.get("item_id")
    )


def _collection_for(item_type: str) -> str:
    return {
        "repository":   "raw_repositories",
        "issue":        "raw_issues",
        "pull_request": "raw_pull_requests",
        "commit":       "raw_commits",
    }.get(item_type, "raw_misc")
