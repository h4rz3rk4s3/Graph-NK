#!/usr/bin/env python3
"""
scripts/find_annotation_frontier.py

Find the resume boundary for an interrupted Stage 2 run, so it can be resumed
with `--resume-from <id>` without re-annotating the work already in Neo4j.

Rationale (CHANGELOG 2026-08-23): the annotation walk is id-ordered, and every
unit the annotator *would* parse (in scope AND not oversized) gets a
ClassifierVerdict (CLASSIFIED_AS edge) unless the run stopped first. The resume
boundary is therefore:

    min(id) over in-scope, non-oversized units with NO verdict.

This is the earliest unit the interrupted run did not finish. Resuming from it
(inclusive) re-annotates from the first gap onward — Signal MERGEs are
idempotent, so re-doing any already-done units is safe, and nothing is skipped.

Oversized units (> annotate_max_chars) are deliberately skipped BEFORE parsing,
so they carry no verdict. They are excluded from the hole definition: the
annotator re-skips them on the resumed run, so they never need re-annotating and
must not pull the frontier backward.

We use `min(un-annotated-non-oversized)` NOT `max(annotated)`: the maximum
annotated id is only a valid frontier for a single-process (K=1) run. Under
concurrent shards, a high-id shard can finish before a low-id one, leaving a
gap — resuming from max() would silently skip it. The min-non-oversized-hole is
correct for both K=1 and sharded interruption.

Run BEFORE restarting containers (it reads the graph as-is):
    python scripts/find_annotation_frontier.py

Prints:
    frontier=...        (first non-oversized in-scope unit with no verdict)
    remaining_units=... (in-scope units at id >= frontier)
    remaining_tokens=...

This is the recovery tool for an interrupted, id-ordered FULL run. It is NOT
the incremental selector for newly-ingested data: the frontier is a minimum-id
boundary, so it cannot skip already-annotated units that sort above it. For new
data use `python scripts/run_pipeline.py --stage 2 --only-unannotated`
(CHANGELOG 2026-08-27) — the graph itself selects the units lacking a verdict.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")
logger = logging.getLogger("find_frontier")


async def _main() -> None:
    from neo4j import AsyncGraphDatabase

    from annotators.worker import _scope_filter
    from settings import settings

    driver = AsyncGraphDatabase.driver(
        settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
    )

    # Reuse the exact annotation-scope filter so the frontier matches the scope
    # the annotator itself uses. _scope_filter returns ("WHERE ...", params).
    where, params = _scope_filter()
    clauses = where[len("WHERE ") :] if where.startswith("WHERE ") else where
    # Exclude oversized units: they are skipped before parsing (no verdict), so
    # they must not count as holes.
    size_guard = "size(u.text) <= $max_chars"
    no_verdict = "NOT EXISTS { MATCH (u)-[:CLASSIFIED_AS]->() }"
    if clauses:
        unparsed_clause = f"{clauses} AND {size_guard} AND {no_verdict}"
    else:
        unparsed_clause = f"{size_guard} AND {no_verdict}"

    try:
        async with driver.session() as session:
            frontier = (
                await (
                    await session.run(
                        f"MATCH (u:TextUnit) WHERE {unparsed_clause} RETURN min(u.id) AS F",
                        max_chars=settings.annotate_max_chars,
                        **params,
                    )
                ).single()
            )["F"]
            if frontier is None:
                logger.info(
                    "The configured annotation scope is complete: no eligible, "
                    "non-oversized in-scope TextUnit lacks a verdict. "
                    "(For newly ingested data, use: python scripts/run_pipeline.py "
                    "--stage 2 --only-unannotated — do NOT interrupt a run and "
                    "compute a frontier.)"
                )
                return

            # Remaining work at id >= frontier (the boundary unit is re-annotated
            # by the inclusive resume, so it is included here).
            rem = await (
                await session.run(
                    f"MATCH (u:TextUnit) WHERE {clauses} AND u.id >= $f "
                    "RETURN count(*) AS n, coalesce(sum(u.token_count), 0) AS toks",
                    f=frontier,
                    **params,
                )
            ).single()

            logger.info("frontier=%s", frontier)
            logger.info("remaining_units=%d", rem["n"])
            logger.info("remaining_tokens=%d", rem["toks"])
            logger.info(
                "Resume with: python scripts/run_pipeline.py --stage 2 "
                '--annotate-shards <K> --resume-from "%s"',
                frontier,
            )
    finally:
        await driver.close()


if __name__ == "__main__":
    asyncio.run(_main())
