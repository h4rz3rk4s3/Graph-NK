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
  python scripts/run_pipeline.py --stage 2        # only annotate + project signals
  python scripts/run_pipeline.py --enrich         # full pipeline + reference enrichment
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("run_pipeline")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run the GraphRAG-NK annotation pipeline.")
    p.add_argument(
        "--stage", type=int, choices=[1, 2], default=0,
        help="Run only stage 1 or 2. Default: run both in sequence.",
    )
    p.add_argument("--enrich", action="store_true",
                   help="Run reference enrichment after the pipeline.")
    return p.parse_args()


async def stage1() -> None:
    """
    Stage 1: Extractor (stream_raw → stream_units) runs concurrently with
    Projector Stage 1 (Phase 0: stream_raw → artefact nodes;
                        Phase 1: stream_units → TextUnit nodes).
    Both exhaust their streams before this coroutine returns.
    """
    from extractor.worker import run_extractor
    from projector.worker import run_projector_stage1

    logger.info("=== Stage 1 start ===")
    await asyncio.gather(run_extractor(), run_projector_stage1())
    logger.info("=== Stage 1 complete ===")


async def stage2() -> None:
    """
    Stage 2: Annotator (stream_units → stream_signals) runs concurrently with
    Projector Stage 2 (stream_signals → Signal nodes).
    """
    from annotators.worker import run_annotator_worker
    from projector.worker import run_projector_stage2

    logger.info("=== Stage 2 start ===")
    await asyncio.gather(run_annotator_worker(), run_projector_stage2())
    logger.info("=== Stage 2 complete ===")


async def main() -> None:
    args = parse_args()
    run_stages = [args.stage] if args.stage else [1, 2]

    for s in run_stages:
        if s == 1:
            await stage1()
        elif s == 2:
            await stage2()

    if args.enrich:
        logger.info("=== Reference enrichment start ===")
        from enrichment.reference_extractor import run_reference_enrichment
        await run_reference_enrichment()
        logger.info("=== Reference enrichment complete ===")

        logger.info("=== Email threading enrichment start ===")
        from enrichment.email_threading import run_email_threading_enrichment
        await run_email_threading_enrichment()
        logger.info("=== Email threading enrichment complete ===")

    logger.info("Pipeline done.")


if __name__ == "__main__":
    asyncio.run(main())
