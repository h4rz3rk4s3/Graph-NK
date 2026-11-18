#!/usr/bin/env python3
"""
scripts/republish_events.py

Rebuild `stream_raw` pointer events from Mongo (the durable source of truth).

WHY THIS EXISTS — CHANGELOG 2026-08-16 (Tier 1). Redis now runs with
`--save ""` (no RDB snapshots), so a Redis container restart wipes the stream
keys. The ingesters only publish pointer events for NEWLY inserted docs
(bulk_upsert_on_key returns just the upserted subset), so merely re-running an
ingester does NOT regenerate events for docs already in Mongo. This script
closes that gap: it iterates the raw collections and re-publishes one pointer
event per doc, deterministically, using the same event shape the ingesters
wrote. Idempotent in the sense that the projector/extractor are idempotent
(MERGE / unique-key upsert); running it twice yields the same downstream state,
just with duplicated stream entries.

Scope: the curated MSR corpora (FRAMEWORK_DESIGN.md §12). Docs are filtered at
query time to CURATED_CORPORA, so old-scope GitHub/Gmane docs are never touched.

At start it prints a MongoDB census (what is already stored), and on completion
it prints an audit (what was published per corpus + which canonical datasets are
still missing). This is the "verify the analysis has access to all data" check.

Usage:
  python scripts/republish_events.py                      # all curated corpora
  python scripts/republish_events.py --dry-run            # count only
  python scripts/republish_events.py --max 10000          # bounded (dev)
  python scripts/republish_events.py --corpus sotorrent --dry-run
                                                          # single-corpus
                                                          # (repeatable / comma-separated)
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("republish_events")

from scripts.corpus_census import (  # noqa: E402  (after sys.path setup)
    CANONICAL,
    CURATED_CORPORA,
    format_census,
    mongo_corpus_counts,
    pending_corpora,
)

# Mongo collections in the order they should be scanned (bulk first).
COLLECTIONS: tuple[str, ...] = (
    "raw_external",
    "raw_emails",
    "raw_issues",
    "raw_pull_requests",
    "raw_commits",
    "raw_repositories",
)


def build_event(collection: str, doc: dict[str, Any]) -> dict[str, Any] | None:
    """
    Reconstruct the stream_raw pointer event for one raw Mongo doc.

    Mirrors the ingesters' event contract exactly (see miner/external_common
    external_event and the per-ingester _event_for builders): item_type /
    item_subtype / repo_name / mongo_id + the v0.8 extra fields (platform_id,
    corpus_id, venue_id, artefact_kind, artefact_labels, conversation_id) that
    the projector's upsert_artefact_from_raw consumes.

    Returns None for docs that cannot be mapped to an item_type (defensive; the
    query already filters to CURATED_CORPORA, so non-curated docs never reach
    this function).
    """
    from miner.external_common import artefact_kind_to_item_type

    meta = doc.get("_meta") or {}
    item_type = meta.get("item_type") or ""
    if not item_type and doc.get("artefact_kind"):
        try:
            item_type = artefact_kind_to_item_type(doc["artefact_kind"])
        except ValueError:
            item_type = ""
    if not item_type:
        logger.warning("Skipping unmappable doc %s in %s", doc.get("_id"), collection)
        return None

    event: dict[str, Any] = {
        "item_type": item_type,
        "item_subtype": item_type,
        "repo_name": (
            doc.get("repo")
            or doc.get("venue_id")
            or doc.get("corpus_id")
            or meta.get("corpus_id")
            or ""
        ),
        "mongo_id": str(doc["_id"]),
    }
    for key in (
        "platform_id",
        "corpus_id",
        "venue_id",
        "artefact_kind",
        "artefact_labels",
        "conversation_id",
    ):
        if doc.get(key):
            event[key] = doc[key]
    return event


def _curated_filter(selected: frozenset[str] | None = None) -> dict[str, Any]:
    """Match docs whose corpus_id (top-level or _meta) is a curated corpus.

    With `selected`, restrict to the intersection of the selection with
    CURATED_CORPORA (the CLI validates the selection up front, so the
    intersection is a no-op guard, not a silent fallback)."""
    curated_sorted = sorted(CURATED_CORPORA & selected) if selected else sorted(CURATED_CORPORA)
    return {
        "$or": [
            {"corpus_id": {"$in": curated_sorted}},
            {"_meta.corpus_id": {"$in": curated_sorted}},
        ]
    }


async def republish(
    collection: str,
    max_records: int | None = None,
    corpora: frozenset[str] | None = None,
) -> dict[str, int]:
    """Publish one pointer event per curated doc in `collection` to stream_raw.

    With `corpora`, only docs of those corpus_ids are republished.

    Returns {corpus_id: events_published} for the audit summary.
    """
    from broker import get_broker
    from settings import settings
    from storage import make_mongo_client

    mongo = make_mongo_client()
    broker = await get_broker()
    coll = mongo[settings.mongo_db_name][collection]
    published_by_corpus: dict[str, int] = {}
    count = 0
    batch: list[dict[str, Any]] = []

    async for doc in coll.find(_curated_filter(corpora)).sort("_id", 1):
        if max_records is not None and count >= max_records:
            break
        event = build_event(collection, doc)
        if event is None:
            continue
        batch.append(event)
        corpus = event.get("corpus_id") or "?"
        published_by_corpus[corpus] = published_by_corpus.get(corpus, 0) + 1
        if len(batch) >= 2000:
            await broker.publish_many(settings.stream_raw, batch)
            count += len(batch)
            batch = []
            logger.info("%s: %d events republished", collection, count)
    if batch:
        await broker.publish_many(settings.stream_raw, batch)
        count += len(batch)
    mongo.close()
    return published_by_corpus


async def run(
    dry_run: bool = False,
    max_records: int | None = None,
    corpora: frozenset[str] | None = None,
) -> None:
    from settings import settings
    from storage import make_mongo_client

    mongo = make_mongo_client()
    db = mongo[settings.mongo_db_name]

    # 1) Census: what is already in MongoDB (read-only; always full so the
    #    printed picture stays the "what exists" reference, selection or not).
    logger.info("MongoDB census (curated corpora present in %s):", settings.mongo_db_name)
    counts = await mongo_corpus_counts(db)
    for line in format_census(counts):
        logger.info(line)
    missing = pending_corpora(counts)
    if missing:
        logger.info("Not yet ingested: %s", ", ".join(cid for cid, _ in missing))
    if corpora:
        logger.info("Corpus selection (republishing ONLY these): %s", ", ".join(sorted(corpora)))

    present = set(await db.list_collection_names())
    total_published: dict[str, int] = {}
    for collection in COLLECTIONS:
        if collection not in present:
            logger.info("Skipping absent collection %s", collection)
            continue
        if dry_run:
            n = await db[collection].count_documents(_curated_filter(corpora))
            logger.info("DRY-RUN %s: %d curated docs would be republished", collection, n)
            continue
        per_corpus = await republish(collection, max_records=max_records, corpora=corpora)
        for cid, n in per_corpus.items():
            total_published[cid] = total_published.get(cid, 0) + n
        logger.info(
            "%s done: %d events published to %s",
            collection,
            sum(per_corpus.values()),
            settings.stream_raw,
        )

    mongo.close()

    # 2) Audit: what was published + what is still missing from MongoDB.
    if not dry_run and total_published:
        logger.info("Republish audit (events written to %s):", settings.stream_raw)
        for cid, label in CANONICAL:
            n = total_published.get(cid, 0)
            if n:
                logger.info("  • %s (%s): %d events", label, cid, n)
        remaining = pending_corpora(counts)
        if remaining:
            logger.info("Canonical datasets with NO data in MongoDB yet (not republished):")
            for cid, label in remaining:
                logger.info("  • %s (%s)", label, cid)


if __name__ == "__main__":
    import asyncio

    p = argparse.ArgumentParser(description="Rebuild stream_raw events from Mongo.")
    p.add_argument("--dry-run", action="store_true", help="census + count only, no writes")
    p.add_argument("--max", type=int, default=None, help="bound on docs per collection")
    p.add_argument(
        "--corpus",
        action="append",
        default=None,
        metavar="ID",
        help="Restrict republishing to these curated corpus_ids (repeatable, "
        "comma-separated). Default: all curated corpora.",
    )
    args = p.parse_args()

    # Fail fast on unknown ids BEFORE any Redis/Mongo write path: an accident
    # here must degrade to an error, never to "republish everything".
    requested: list[str] = []
    for c in args.corpus or []:
        requested.extend(s.strip() for s in c.split(",") if s.strip())
    corpora = None
    if requested:
        unknown = sorted(set(requested) - CURATED_CORPORA)
        if unknown:
            p.error(f"unknown corpus id(s) {unknown}; valid: {sorted(CURATED_CORPORA)}")
        corpora = frozenset(requested)

    asyncio.run(run(dry_run=args.dry_run, max_records=args.max, corpora=corpora))
