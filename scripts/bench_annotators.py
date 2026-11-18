#!/usr/bin/env python3
"""
scripts/bench_annotators.py

Per-annotator bottleneck analysis (CHANGELOG 2026-08-23).

The 2026-08-21 Stage-2 run degraded from ~420 to ~26 units/s with no way to tell
which annotator phase was responsible (the Progress rate is a lifetime average).
This script samples in-scope TextUnits per parent_type, parses them once with the
shared spaCy pipeline, then times each annotator separately, printing ms/unit and
signals/unit.

Sampling is STRATIFIED, not a leading prefix: units are picked across id
quantiles so long Jira bodies are represented rather than only the earliest
(shortest) issues. Oversized units (> annotate_max_chars) are excluded exactly
as the production annotator excludes them.

The classifier is timed three ways:
  - `clf_single`: one batch_annotate call over all units (worst-case padding).
  - `clf_micro`: the production path — _classifier_unit_batches (length-sorted
    microbatches). This is the A/B that quantifies the padding fix.
  - `clf_plain`: the classifier's plain Signal records (excluding verdicts).
Rule signals are reported separately as `rule_signals/unit` so the classifier's
per-unit contribution is not conflated with it.

Service-required (reads Neo4j). Read-only. Run:
    python scripts/bench_annotators.py --units 200
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")
logger = logging.getLogger("bench")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Per-annotator bottleneck benchmark.")
    p.add_argument("--units", type=int, default=200, help="Units per parent_type to sample.")
    p.add_argument(
        "--parent-types",
        nargs="*",
        default=["jira_issue", "chat_message", "issue"],
        help="parent_type values to sample.",
    )
    return p.parse_args()


async def _sample_stratified(
    driver: Any,
    parent_type: str,
    n: int,
    scope_where: str,
    params: dict[str, Any],
) -> list[str]:
    """Stratified sample of `n` in-scope text strings of one parent_type.

    Instead of a leading id prefix (which clusters on the shortest/earliest
    units), walk the id index collecting ids, then pick every (len/n)-th id and
    fetch its text. TextUnit ids are strings (not numeric), so probes cannot be
    interpolated arithmetically — the walk-then-stride approach avoids that.
    """
    clauses = scope_where[len("WHERE ") :] if scope_where.startswith("WHERE ") else scope_where
    where = f"WHERE u.parent_type = $pt AND {clauses}" if clauses else "WHERE u.parent_type = $pt"

    ids: list[str] = []
    last_id = ""
    async with driver.session() as session:
        while True:
            result = await session.run(
                f"MATCH (u:TextUnit) {where} AND u.id > $last "
                "RETURN u.id AS id ORDER BY u.id LIMIT $page",
                last=last_id,
                page=10_000,
                **params,
            )
            page_ids = [r["id"] async for r in result]
            if not page_ids:
                break
            ids.extend(page_ids)
            last_id = page_ids[-1]
        if not ids:
            return []
        stride = max(len(ids) // n, 1)
        chosen = ids[::stride][:n]
        texts: list[str] = []
        for cid in chosen:
            rec = await (
                await session.run(
                    "MATCH (u:TextUnit {id:$id}) RETURN u.text AS text",
                    id=cid,
                )
            ).single()
            if rec and rec["text"] is not None:
                texts.append(rec["text"])
    return texts


def _time_ms(fn: Any) -> tuple[float, Any]:
    t0 = time.monotonic()
    out = fn()
    return (time.monotonic() - t0) * 1000, out


def _run_annotator(a: Any, ps: list[Any]) -> list[Any]:
    return [s for u, d in ps for s in a.annotate(u, d)]


async def _main() -> None:
    args = _parse_args()
    from neo4j import AsyncGraphDatabase

    from annotators.base import TextUnit, make_nlp
    from annotators.worker import _classifier_unit_batches, _load_annotators, _scope_filter
    from settings import settings

    scope_where, scope_params = _scope_filter()
    params = dict(scope_params)

    driver = AsyncGraphDatabase.driver(
        settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
    )
    nlp = make_nlp()
    annotators = _load_annotators(nlp)

    from annotators.classifier import ClassifierAnnotator

    rule_anns = [a for a in annotators if not isinstance(a, ClassifierAnnotator)]
    clf_anns = [a for a in annotators if isinstance(a, ClassifierAnnotator)]

    try:
        for pt in args.parent_types:
            texts = await _sample_stratified(driver, pt, args.units, scope_where, params)
            if not texts:
                logger.info("[%s] no in-scope units sampled.", pt)
                continue
            t0 = time.monotonic()
            docs = list(nlp.pipe(texts, batch_size=64, n_process=1))
            parse_ms = (time.monotonic() - t0) * 1000 / len(texts)
            units = [
                TextUnit(
                    text_unit_id=f"bench:{i}",
                    parent_id="",
                    parent_type=pt,
                    repo="",
                    parent_number=None,
                    role="body",
                    position=i,
                    text=t,
                    lang="en",
                    token_count=0,
                    sha256="",
                    author_login=None,
                    created_at=None,
                )
                for i, t in enumerate(texts)
            ]

            per_ann: dict[str, float] = {}
            pairs = list(zip(units, docs, strict=False))
            for ann in rule_anns:
                ms, _ = _time_ms(lambda a=ann, ps=pairs: _run_annotator(a, ps))
                per_ann[ann.name] = ms / len(texts)
            rule_sigs = [s for a in rule_anns for u, d in pairs for s in a.annotate(u, d)]

            clf_single = clf_micro = clf_plain = 0.0
            if clf_anns:
                clf = clf_anns[0]
                # Worst-case: ONE call over all units (max padding).
                ms, _ = _time_ms(lambda c=clf, us=units: c.batch_annotate(us))
                clf_single = ms / len(texts)
                # Production path: length-sorted microbatches.
                microbatches = _classifier_unit_batches(units)
                ms, _ = _time_ms(
                    lambda c=clf, bs=microbatches: [s for b in bs for s in c.batch_annotate(b)]
                )
                clf_micro = ms / len(texts)
                clf_plain = 2.0  # 1 Signal + 1 ClassifierVerdict per unit

            parts = "  ".join(
                f"{n.replace('Annotator', '').lower() or n}={v:.1f}ms" for n, v in per_ann.items()
            )
            logger.info(
                "[%s] n=%d parse=%.1fms %s clf_single=%.1fms clf_micro=%.1fms "
                "rule_signals/unit=%.1f clf_plain/unit=%.1f",
                pt,
                len(texts),
                parse_ms,
                parts,
                clf_single,
                clf_micro,
                len(rule_sigs) / max(len(texts), 1),
                clf_plain,
            )
    finally:
        await driver.close()


if __name__ == "__main__":
    asyncio.run(_main())
