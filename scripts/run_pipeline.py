#!/usr/bin/env python3
"""
scripts/run_pipeline.py

Runs the GraphRAG-NK pipeline in two sequential stages. Sequential staging
fixes CHANGELOG.md ⚠️ limitation 2 (signals arriving before TextUnits).

  Stage 1  Extractor  + Projector Phase 0+1
           ─ Converts raw GitHub docs → TextUnit events
           ─ Seeds artefact nodes (Phase 0) then TextUnit nodes (Phase 1)
           ─ These run concurrently: extractor produces while projector consumes.

  Stage 2  Annotator  + Projector Phase 2
           ─ Annotates TextUnits → Signal events
           ─ Projects Signals into Neo4j
           ─ These run concurrently: annotator produces while projector consumes.

Typical research workflow:
  1. python scripts/mine_one.py --repo python/cpython
  2. python scripts/run_pipeline.py
  3. python scripts/run_pipeline.py --enrich   (adds REFERENCES edges)
  4. jupyter lab notebooks/

Usage:
  python scripts/run_pipeline.py                  # full pipeline
  python scripts/run_pipeline.py --stage 1        # only extract + project artefacts
  python scripts/run_pipeline.py --stage 2        # annotate + project signals (concurrent)
  python scripts/run_pipeline.py --stage 2 --annotate-shards 8
                                                  # annotate split across 8 processes
  python scripts/run_pipeline.py --stage 2 --annotate-shards 8 --shard-index 3
                                                  # re-run ONLY shard 3 (recovery)
  python scripts/run_pipeline.py --stage 2 --skip-annotate
                                                  # drain existing stream_signals only
  python scripts/run_pipeline.py --enrich         # full pipeline + reference enrichment
  python scripts/run_pipeline.py --census         # read-only status: Mongo + Redis + Neo4j
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
# Neo4j emits informational GQL notifications (e.g. 'index already exists'
# for idempotent CREATE INDEX ... IF NOT EXISTS on startup). These are not
# errors; silence them to keep the pipeline log readable.
logging.getLogger("neo4j.notifications").setLevel(logging.WARNING)
logger = logging.getLogger("run_pipeline")


def _positive_int(value: str) -> int:
    """argparse type: reject 0/negative so --annotate-shards cannot silently
    spawn no annotator and report Stage 2 complete with nothing run."""
    try:
        n = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"must be an integer, got {value!r}") from exc
    if n < 1:
        raise argparse.ArgumentTypeError(f"must be >= 1, got {n}")
    return n


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run the GraphRAG-NK annotation pipeline.")
    p.add_argument(
        "--stage",
        type=int,
        choices=[1, 2],
        default=0,
        help="Run only stage 1 or 2. Default: run both in sequence.",
    )
    p.add_argument(
        "--enrich", action="store_true", help="Run reference enrichment after the pipeline."
    )
    p.add_argument(
        "--census",
        action="store_true",
        help="Print a read-only status dashboard (MongoDB corpus census, Redis "
        "streams, Neo4j node counts) and exit without running the pipeline.",
    )
    p.add_argument(
        "--skip-phase0",
        action="store_true",
        help="Skip Phase 0 (artefact seeding). Only meaningful with --stage 1 (or default).",
    )
    p.add_argument(
        "--skip-annotate",
        action="store_true",
        help="Skip the annotation phase of Stage 2.",
    )
    p.add_argument(
        "--annotate-shards",
        type=_positive_int,
        default=1,
        help="Split annotation across this many worker processes (each owns a "
        "disjoint keyset range of TextUnits). 1 = single process, unchanged.",
    )
    p.add_argument(
        "--shard-index",
        type=int,
        default=None,
        help="Run ONLY this shard (0..--annotate-shards-1). Recovery path: "
        "re-annotate a single crashed shard while the projector drains its "
        "signals concurrently. Requires --annotate-shards to define the partition.",
    )
    p.add_argument(
        "--resume",
        action="store_true",
        help="Resume Stage 2 from each shard's stored high-water mark instead of "
        "re-annotating from the start of its range (CHANGELOG 2026-08-23).",
    )
    p.add_argument(
        "--resume-from",
        type=str,
        default=None,
        help="One-off resume boundary: only annotate TextUnits with id >= this id. "
        "Used after scripts/find_annotation_frontier.py to pick up the un-annotated "
        "tail of an interrupted run. Shard boundaries are computed over [id, max).",
    )
    p.add_argument(
        "--only-unannotated",
        action="store_true",
        help="Incremental Stage 2: annotate ONLY TextUnits that have no "
        "ClassifierVerdict yet (and are not oversized). Backed by a per-unit "
        "Neo4j predicate, so newly-ingested data is the only work; rerunning the "
        "same command recovers from any interruption. For newly-ingested data "
        "ONLY — do NOT use when rules/lexicons/classifier have changed (those "
        "need a full re-annotate). Incompatible with --resume, --resume-from, "
        "--shard-index, and --skip-annotate.",
    )
    return p.parse_args()


async def _preflight_check(broker: Any) -> bool:
    """
    Verify stream_raw is queued before Stage 1 starts.

    Returns True to proceed. If the queue is empty but MongoDB holds curated
    documents (the common state after a Redis restart, since Redis is
    non-persistent — CHANGELOG 2026-08-16), prints the MongoDB census and the
    exact command to re-queue, then returns False so the pipeline does not spin
    up empty stages.
    """
    from settings import settings

    raw_len = await broker.stream_length(settings.stream_raw)
    if raw_len > 0:
        logger.info("Pre-flight OK: %d events queued in %s.", raw_len, settings.stream_raw)
        return True

    from scripts.corpus_census import format_census, mongo_corpus_counts, pending_corpora
    from storage import make_mongo_client

    logger.warning("Redis stream '%s' is EMPTY (0 queued events).", settings.stream_raw)
    mongo = make_mongo_client()
    db = mongo[settings.mongo_db_name]
    counts = await mongo_corpus_counts(db)
    mongo.close()
    total = sum(counts.values())
    if total == 0:
        logger.warning(
            "MongoDB also holds 0 curated documents — nothing to process. "
            "Ingest a curated dataset first."
        )
        return False
    logger.warning("MongoDB holds %d curated documents that are NOT queued:", total)
    for line in format_census(counts):
        logger.warning(line)
    missing = pending_corpora(counts)
    if missing:
        logger.warning(
            "Canonical datasets still NOT ingested: %s", ", ".join(cid for cid, _ in missing)
        )
    logger.warning("To load MongoDB data into Redis and proceed:")
    logger.warning("  python scripts/republish_events.py")
    logger.warning("then re-run this pipeline.")
    return False


def _validate_incremental_flags(args: argparse.Namespace) -> None:
    """Reject --only-unannotated combined with flags it is semantically at odds
    with (CHANGELOG 2026-08-27). Incremental selection is per-unit from the
    graph, so HWM resume, a frontier boundary, per-shard recovery, and the
    projector-only drain are all meaningless (or unsafe) in that mode."""
    incompatible: list[str] = []
    if args.resume:
        incompatible.append("--resume")
    if args.resume_from is not None:
        incompatible.append("--resume-from")
    if args.shard_index is not None:
        incompatible.append("--shard-index")
    if args.skip_annotate:
        incompatible.append("--skip-annotate")
    if incompatible:
        raise SystemExit(
            "--only-unannotated is incompatible with "
            + ", ".join(incompatible)
            + ". Rerun the same --only-unannotated command to recover: the graph "
            "itself selects which units remain un-annotated."
        )


async def _census() -> None:
    """Read-only consolidated status: MongoDB corpus census, Redis streams,
    Neo4j node counts. Never writes anything; exits after printing."""
    from settings import settings

    # ── MongoDB ────────────────────────────────────────────────────────────────
    from scripts.corpus_census import (
        CANONICAL,
        format_census,
        mongo_corpus_counts,
        pending_corpora,
    )
    from storage import make_mongo_client

    logger.info("=== MongoDB corpus census (%s) ===", settings.mongo_db_name)
    mongo = make_mongo_client()
    db = mongo[settings.mongo_db_name]
    counts = await mongo_corpus_counts(db)
    mongo.close()
    total = sum(counts.values())
    for line in format_census(counts):
        logger.info(line)
    missing = pending_corpora(counts)
    if missing:
        logger.info("Not yet ingested (%d): %s", len(missing), ", ".join(cid for cid, _ in missing))
    else:
        logger.info("All %d canonical datasets present in MongoDB.", len(CANONICAL))
    logger.info("Total curated documents in MongoDB: %d", total)

    # ── Redis ──────────────────────────────────────────────────────────────────
    from redis import asyncio as aioredis

    logger.info("=== Redis streams (%s) ===", settings.redis_url)
    client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        for name in (settings.stream_raw, settings.stream_units, settings.stream_signals):
            n = await client.xlen(name)
            logger.info("  %-18s: %d entries", name, n)
        try:
            info = await client.info("memory")
            logger.info(
                "  used_memory=%s  maxmemory=%s",
                info.get("used_memory_human"),
                info.get("maxmemory_human"),
            )
        except Exception as exc:
            logger.warning("  Redis memory info unavailable: %s", exc)
    finally:
        await client.aclose()

    # ── Neo4j ──────────────────────────────────────────────────────────────────
    from neo4j import AsyncGraphDatabase

    logger.info("=== Neo4j graph (%s) ===", settings.neo4j_uri)
    driver = AsyncGraphDatabase.driver(
        settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
    )
    try:
        async with driver.session() as session:
            for label, prop in (
                ("Artefact", "corpus_id"),
                ("TextUnit", "corpus_id"),
                ("Signal", "layer"),
            ):
                result = await session.run(
                    f"MATCH (n:{label}) RETURN coalesce(n.{prop}, '?') AS k, "
                    f"count(*) AS c ORDER BY c DESC"
                )
                rows = await result.data()
                node_total = sum(r["c"] for r in rows)
                logger.info("  %s nodes: %d", label, node_total)
                for r in rows[:12]:
                    logger.info("      %-28s: %d", r["k"], r["c"])
    finally:
        await driver.close()

    logger.info("Census complete (read-only; nothing was written).")


async def stage1(skip_phase0: bool = False) -> None:
    """
    Stage 1 runs the extractor + projector in two sub-stages.

    Sub-stage 1a — Phase 0 alone (stream_raw → artefact nodes). Phase 0 seeds
      every parent artefact before the extractor starts, so TextUnit parents
      always exist by the time Phase 1 writes them (CHANGELOG limitation 1).
      Running it alone also means stream_units is still empty while it runs.
      With `skip_phase0=True` (resume mode), this is skipped — the parents were
      seeded on the previous run and are still in Neo4j (idempotent).

    Sub-stage 1b — Extractor + Phase 1 concurrently. The extractor turns each
      raw doc into TextUnit events on stream_units while Phase 1 consumes and
      trims that stream live (batched UNWIND writes, CHANGELOG 2026-08-16). This
      keeps stream_units tiny instead of buffering the corpus in Redis — the OOM
      root cause fixed in CHANGELOG 2026-08-16.
    """
    from extractor.worker import run_extractor
    from projector.worker import run_projector_phase0, run_projector_phase1

    if not skip_phase0:
        logger.info("=== Stage 1 (Phase 0) start ===")
        await run_projector_phase0()
        logger.info("=== Stage 1 (Phase 0) complete ===")
    else:
        logger.info("=== Stage 1 (Phase 0) SKIPPED (--skip-phase0 resume mode) ===")

    logger.info("=== Stage 1 (extract+project) start ===")
    await asyncio.gather(run_extractor(), run_projector_phase1())
    logger.info("=== Stage 1 (extract+project) complete ===")


async def stage2(
    skip_annotate: bool = False,
    annotate_shards: int = 1,
    shard_index: int | None = None,
    resume: bool = False,
    resume_from: str | None = None,
    only_unannotated: bool = False,
) -> None:
    """
    Stage 2: annotate TextUnits and project Signals.

    CONCURRENT by default (CHANGELOG 2026-08-21): annotator workers run as
    spawned child processes (one per shard) while the Phase-2 projector drains
    stream_signals in the parent. This keeps Redis bounded instead of letting a
    fast producer pile the whole run into the 12 GiB noeviction limit before
    projection starts. The 2026-08-18 premature-exit bug is fixed structurally:
    the projector only stops when ALL annotator processes have exited AND the
    stream is drained (broker.read_all stop_event mode).

    `--skip-annotate` keeps the legacy standalone drain (projector only, exit
    on stream exhaustion) — used to project signals already sitting in Redis.
    """
    from projector.worker import run_projector_stage2

    if skip_annotate:
        logger.info("=== Stage 2 (project signals) start ===")
        await run_projector_stage2()
        logger.info("=== Stage 2 (project signals) complete ===")
        return

    await _run_annotate_and_project(
        annotate_shards, shard_index, resume, resume_from, only_unannotated
    )


async def _wait_for_children_or_projector(
    procs: list[tuple[int, Any]],
    projector_task: asyncio.Task | None,
) -> str:
    """
    Poll until either all annotator children exit or the projector task finishes.

    Returns "children" when every shard process has exited, or "projector" when
    the projector task completed (success or failure) first.

    The projector branch is the 2026-08-21 hang fix: if the projector fails
    while annotator children are alive, those children block forever in the
    backpressure gate (nothing is draining stream_signals). A loop that only
    watched child liveness would therefore hang the parent indefinitely with the
    projector's exception never retrieved. Returning on projector completion
    lets the caller `await projector_task` to re-raise that exception and reap
    the children.
    """
    while True:
        if projector_task is not None and projector_task.done():
            return "projector"
        if not any(p.is_alive() for _i, p in procs):
            return "children"
        await asyncio.sleep(0.5)


async def _run_annotate_and_project(
    annotate_shards: int,
    shard_index: int | None,
    resume: bool = False,
    resume_from: str | None = None,
    only_unannotated: bool = False,
) -> None:
    """
    Spawn the annotator shard process(es), drain stream_signals concurrently
    with the Phase-2 projector, then fail loudly (after draining) if any shard
    exited non-zero.

    Incremental mode (only_unannotated, CHANGELOG 2026-08-27): count the
    remaining un-annotated units first. Zero → drain any existing stream_signals
    (projector-only) and exit without spawning annotators. Fewer units than the
    requested shard count -> reduce the effective shard count so the token-
    quantile boundary scan does not try to split more shards than there is work.
    """
    import multiprocessing as mp

    from annotators.worker import (
        _run_annotator_shard,
        compute_shard_boundaries,
        count_in_scope,
    )
    from projector.worker import run_projector_stage2

    logger.info("=== Stage 2 (annotate + project concurrently) start ===")

    if only_unannotated:
        remaining = await count_in_scope(only_unannotated=True)
        logger.info("Incremental Stage 2: %d un-annotated TextUnits in scope.", remaining)
        if remaining == 0:
            logger.info(
                "No un-annotated TextUnits to process — draining existing signals "
                "and finishing Stage 2."
            )
            await run_projector_stage2()
            logger.info("=== Stage 2 (annotate + project concurrently) complete ===")
            return
        if remaining < annotate_shards:
            logger.info(
                "Only %d un-annotated units for %d requested shards — reducing to "
                "1 shard.",
                remaining,
                annotate_shards,
            )
            annotate_shards = 1

    base_lo: str | None = resume_from
    boundaries: list[str] = []
    if annotate_shards > 1:
        boundaries = await compute_shard_boundaries(
            annotate_shards, id_lo=base_lo, only_unannotated=only_unannotated
        )
        logger.info("Annotator shard boundaries (%d): %s", annotate_shards, boundaries)
    elif resume_from is not None:
        logger.info("Single-process resume from boundary: %s", resume_from)

    indices = [shard_index] if shard_index is not None else list(range(annotate_shards))
    ctx = mp.get_context("spawn")
    procs: list[tuple[int, Any]] = []
    for i in indices:
        lo = boundaries[i - 1] if i > 0 else base_lo
        hi = boundaries[i] if i < annotate_shards - 1 else None
        p = ctx.Process(
            target=_run_annotator_shard,
            args=(i, annotate_shards, lo, hi, resume, None, only_unannotated),
            name=f"annotator-shard-{i}",
        )
        p.start()
        procs.append((i, p))
    logger.info("Spawned %d annotator shard process(es).", len(procs))

    stop_event = asyncio.Event()
    projector_task: asyncio.Task | None = None
    try:
        # Start the Phase-2 projector CONCURRENTLY with the annotator children so
        # stream_signals is drained while it is produced (not after) — this keeps
        # Redis bounded. It exits only when stop_event is set AND the stream is
        # drained (broker.read_all producer-aware mode).
        projector_task = asyncio.create_task(run_projector_stage2(stop_event))
        # Poll child liveness from the event loop (never a blocking join here —
        # that would freeze Ctrl-C handling and the projector task). The projector
        # branch is the 2026-08-21 hang fix: if the projector fails while children
        # are alive, the children block forever on backpressure (nothing drains)
        # — polling only children would hang the parent indefinitely.
        await _wait_for_children_or_projector(procs, projector_task)
        stop_event.set()
        await projector_task
        projector_task = None
    finally:
        # Ensure children are always reaped, and that a projector failure or a
        # KeyboardInterrupt cannot orphan shard processes.
        stop_event.set()
        for _i, p in procs:
            if p.is_alive():
                p.terminate()
        for _i, p in procs:
            p.join()
        if projector_task is not None and not projector_task.done():
            projector_task.cancel()
            try:
                await projector_task
            except (asyncio.CancelledError, Exception):
                pass

    failed = [i for i, p in procs if p.exitcode != 0]
    if failed:
        if only_unannotated:
            # Incremental recovery is the whole-corpus rerun: the graph itself
            # selects the still-un-annotated units, and shard boundaries must be
            # recomputed over the (shrinking) remaining population — a single
            # --shard-index would re-run a now-stale partition (CHANGELOG
            # 2026-08-27).
            raise RuntimeError(
                f"Annotator shard(s) {failed} exited non-zero. "
                f"Recovery: re-run the same incremental command, e.g.: "
                f"python scripts/run_pipeline.py --stage 2 "
                f"--annotate-shards {annotate_shards} --only-unannotated"
            )
        # One command PER failed shard: a single --shard-index flag only selects
        # the last one under argparse, so collapsing them loses the earlier ones.
        # Preserve --resume-from (the resumed tail partition) so the recovered
        # shard re-runs its ORIGINAL range, not a freshly-recomputed partition.
        base = f"--stage 2 --annotate-shards {annotate_shards} --shard-index {failed[0]}"
        if resume_from is not None:
            base += f' --resume-from "{resume_from}"'
        if resume:
            base += " --resume"
        raise RuntimeError(
            f"Annotator shard(s) {failed} exited non-zero. "
            f"Re-run each failed shard, e.g.: python scripts/run_pipeline.py {base}"
        )

    logger.info("=== Stage 2 (annotate + project concurrently) complete ===")


async def main() -> None:
    args = parse_args()

    if args.census:
        await _census()
        return

    if args.only_unannotated:
        _validate_incremental_flags(args)

    from broker import get_broker

    run_stages = [args.stage] if args.stage else [1, 2]

    # Gate Stage 1 on a populated stream_raw: if Redis restarted (non-persistent)
    # the queue is empty even though MongoDB has everything — say so and stop
    # instead of running empty stages. Stage-2-only runs don't need stream_raw.
    if 1 in run_stages:
        broker = await get_broker()
        if not await _preflight_check(broker):
            logger.warning("Pipeline aborted before Stage 1 — no queued data.")
            return
        await broker.close()

    if args.shard_index is not None and not (0 <= args.shard_index < args.annotate_shards):
        logger.error(
            "--shard-index %d out of range for --annotate-shards %d.",
            args.shard_index,
            args.annotate_shards,
        )
        return

    for s in run_stages:
        if s == 1:
            await stage1(skip_phase0=args.skip_phase0)
        elif s == 2:
            await stage2(
                skip_annotate=args.skip_annotate,
                annotate_shards=args.annotate_shards,
                shard_index=args.shard_index,
                resume=args.resume,
                resume_from=args.resume_from,
                only_unannotated=args.only_unannotated,
            )

    if args.enrich:
        logger.info("=== Reference enrichment start ===")
        from enrichment.reference_extractor import run_reference_enrichment

        await run_reference_enrichment()
        logger.info("=== Reference enrichment complete ===")

        logger.info("=== Email threading enrichment start ===")
        from enrichment.email_threading import run_email_threading_enrichment

        await run_email_threading_enrichment()
        logger.info("=== Email threading enrichment complete ===")

        logger.info("=== IRC reply threading enrichment start ===")
        from enrichment.irc_threading import run_irc_threading_enrichment

        await run_irc_threading_enrichment()
        logger.info("=== IRC reply threading enrichment complete ===")

    logger.info("Pipeline done.")


if __name__ == "__main__":
    asyncio.run(main())
